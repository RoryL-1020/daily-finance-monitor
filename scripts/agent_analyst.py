#!/usr/bin/env python3
"""
每日金融情报官 — LangGraph Agent 工作流 v3.0
══════════════════════════════════════════════════════════════

三层架构:
  Layer 1: 并行采集 (fan-out via Send) → 并行 LLM 分析 (fan-out via Send)
  Layer 2: 多空辩论 Agent (待接入)
  Layer 3: 人工审批 + 状态持久化 (待接入)

工作流示意:
  START → init_state
        → route_fetch [Send] → fetch_asset × N (并行)
        → log_results
        → route_analyze [Send] → analyze_asset × N (并行, LLM)
        → synthesize_report (LLM)
        → [Phase2 placeholder: debate]
        → [Phase3 placeholder: wait_approval]
        → END

用法:
    python -c "from scripts.agent_analyst import run_agent_workflow; run_agent_workflow()"
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, TypedDict, Annotated
from pathlib import Path

import requests
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from langgraph.checkpoint.memory import MemorySaver
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

# ── 路径常量 ───────────────────────────────────────
CST = timezone(timedelta(hours=8))
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_DIR = SCRIPT_DIR.parent
REPORTS_DIR = PROJECT_DIR / 'reports'

REQ_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0'
    )
}


# ════════════════════════════════════════════════════════
#  资产配置（可自由增删）
# ════════════════════════════════════════════════════════

ASSETS = [
    {"symbol": "USDCNY",   "name": "美元兑人民币",    "type": "forex",     "unit": "人民币/美元",      "enabled": True},
    {"symbol": "TENCENT",  "name": "腾讯控股",        "type": "stock",     "unit": "港元",            "enabled": True},
    {"symbol": "GOLD",     "name": "黄金 XAU/USD",    "type": "commodity", "unit": "美元/盎司",       "enabled": True},
    {"symbol": "SP500",    "name": "标普500指数",     "type": "index",     "unit": "点",              "enabled": True},
    {"symbol": "CSI300",   "name": "沪深300指数",     "type": "index",     "unit": "点",              "enabled": True},
    {"symbol": "BTC",      "name": "比特币",          "type": "crypto",    "unit": "美元",            "enabled": True},
    {"symbol": "US10Y",    "name": "10年期美债收益率", "type": "bond",     "unit": "%",               "enabled": True},
]


# ════════════════════════════════════════════════════════
#  State 定义（with reducer for 并行 fan-in）
# ════════════════════════════════════════════════════════

def _dict_merge(a: Dict, b: Dict) -> Dict:
    """Reducer: 合并两个 dict，b 覆盖 a"""
    return {**a, **b}


class FinanceState(TypedDict):
    """LangGraph 全局状态"""
    date: str                                          # YYYY-MM-DD
    assets_config: List[Dict]                           # 待处理资产列表
    raw_data: Annotated[Dict[str, Dict], _dict_merge]   # {symbol: 原始数据}
    errors: Annotated[Dict[str, str], _dict_merge]      # {symbol: 错误信息}
    analyses: Annotated[Dict[str, str], _dict_merge]    # {symbol: LLM分析文本}
    final_report: str                                   # 最终日报
    approval_status: str                                # pending | approved | rejected
    human_feedback: str                                 # 人工反馈


# ════════════════════════════════════════════════════════
#  Layer 1A: 并行数据采集（7个独立API）
# ════════════════════════════════════════════════════════

def _fetch_tencent() -> Dict:
    """腾讯控股 (00700.HK) — 新浪财经"""
    headers = {**REQ_HEADERS, 'Referer': 'https://finance.sina.com.cn'}
    try:
        resp = requests.get('https://hq.sinajs.cn/list=rt_hk00700', timeout=12, headers=headers)
        resp.encoding = 'gb2312'
        content = resp.text.strip().split('="')[1].rstrip('";')
        fields = content.split(',')
        return {
            "success": True,
            "name": f'{fields[1]}({fields[0]})',
            "current_price": float(fields[6]),
            "prev_close": float(fields[3]),
            "open": float(fields[2]),
            "high": float(fields[4]), "low": float(fields[5]),
            "change": float(fields[7]),
            "change_percent": fields[8].strip(),
            "volume": fields[12], "amount": fields[11],
            "source": "新浪财经"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _fetch_gold() -> Dict:
    """黄金 XAU/USD — gold-api.com"""
    try:
        resp = requests.get('https://api.gold-api.com/price/XAU', timeout=12, headers=REQ_HEADERS)
        resp.raise_for_status()
        data = resp.json()
        return {"success": True, "price": float(data['price']), "source": "gold-api.com"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _fetch_usdcny() -> Dict:
    """美元兑人民币 — open.er-api.com"""
    try:
        resp = requests.get('https://open.er-api.com/v6/latest/USD', timeout=12, headers=REQ_HEADERS)
        resp.raise_for_status()
        data = resp.json()
        return {"success": True, "rate": data['rates']['CNY'], "source": "ExchangeRate-API"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _fetch_sp500() -> Dict:
    """标普500指数 — 东方财富 (secid=100.SPX, 需要÷100)"""
    headers = {**REQ_HEADERS, 'Referer': 'https://quote.eastmoney.com/'}
    try:
        resp = requests.get(
            'https://push2.eastmoney.com/api/qt/stock/get'
            '?secid=100.SPX&fields=f43,f44,f45,f46,f47,f48,f60,f170,f171,f168,f169',
            timeout=12, headers=headers
        )
        resp.raise_for_status()
        d = resp.json().get('data')
        if not d or not d.get('f43'):
            raise ValueError(f'东方财富返回空数据: {resp.text[:200]}')

        cur = d['f43'] / 100.0
        prev = d['f60'] / 100.0 if d.get('f60') else None
        chg = (cur - prev) if prev else None
        chg_pct = (chg / prev * 100) if prev and chg else None

        return {
            "success": True,
            "name": "标普500指数 (SPX)",
            "current_price": round(cur, 2),
            "prev_close": round(prev, 2) if prev else None,
            "open": round(d['f46'] / 100.0, 2) if d.get('f46') else None,
            "high": round(d['f44'] / 100.0, 2) if d.get('f44') else None,
            "low": round(d['f45'] / 100.0, 2) if d.get('f45') else None,
            "change": round(chg, 2) if chg else None,
            "change_percent": round(chg_pct, 3) if chg_pct else None,
            "source": "东方财富",
            "_api_raw": f"f43={d['f43']} f60={d.get('f60')}"
        }
    except Exception as e:
        return {"success": False, "error": f"东方财富SPX: {e}"}


def _fetch_csi300() -> Dict:
    """沪深300指数 — 新浪财经"""
    headers = {**REQ_HEADERS, 'Referer': 'https://finance.sina.com.cn'}
    try:
        resp = requests.get('https://hq.sinajs.cn/list=sh000300', timeout=12, headers=headers)
        resp.encoding = 'gb2312'
        content = resp.text.strip().split('="')[1].rstrip('";')
        fields = content.split(',')
        return {
            "success": True,
            "name": fields[0],
            "current_price": float(fields[3]) if fields[3] else None,
            "prev_close": float(fields[2]) if fields[2] else None,
            "high": float(fields[4]) if fields[4] else None,
            "low": float(fields[5]) if fields[5] else None,
            "source": "新浪财经"
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _fetch_bitcoin() -> Dict:
    """比特币 — blockchain.info ticker (free, no key)"""
    try:
        resp = requests.get('https://blockchain.info/ticker', timeout=12, headers=REQ_HEADERS)
        resp.raise_for_status()
        d = resp.json()
        usd = d.get('USD')
        if not usd:
            raise ValueError(f'blockchain.info 无 USD 字段: {list(d.keys())}')
        price = usd.get('15m') or usd.get('last')
        return {
            "success": True,
            "name": "比特币 (BTC/USD)",
            "current_price": price,
            "buy": usd.get('buy'),
            "sell": usd.get('sell'),
            "change_percent_24h": None,
            "source": "blockchain.info"
        }
    except Exception as e:
        return {"success": False, "error": f"blockchain.info: {e}"}


def _fetch_us10y() -> Dict:
    """10年期美债收益率 — 美国财政部 CSV (free, no key)"""
    try:
        now = datetime.now()
        yyyymm = now.strftime('%Y%m')
        url = (
            'https://home.treasury.gov/resource-center/data-chart-center/'
            f'interest-rates/daily-treasury-rates.csv/all/{yyyymm}'
            f'?type=daily_treasury_yield_curve'
            f'&field_tdr_date_value_month={yyyymm}&_format=csv'
        )
        resp = requests.get(url, timeout=15, headers=REQ_HEADERS)
        resp.raise_for_status()
        lines = resp.text.strip().splitlines()
        if len(lines) < 2:
            raise ValueError(f'CSV 行数不足: {len(lines)}')
        headers = [h.strip().strip('"') for h in lines[0].split(',')]
        if '10 Yr' not in headers:
            raise ValueError(f'CSV 缺少 "10 Yr" 列: {headers}')
        idx = headers.index('10 Yr')
        # 第一行数据 = 最新日期（CSV 按日期降序）
        first = [f.strip().strip('"') for f in lines[1].split(',')]
        yield_val = float(first[idx]) if first[idx] else None
        date_str = first[0]
        return {
            "success": True,
            "name": "10年期美债收益率",
            "yield_pct": yield_val,
            "date": date_str,
            "source": "US Treasury.gov",
            "_url": url,
        }
    except Exception as e:
        return {"success": False, "error": f"Treasury CSV: {e}"}


# 采集函数路由表
_FETCHERS = {
    "TENCENT": _fetch_tencent,
    "GOLD": _fetch_gold,
    "USDCNY": _fetch_usdcny,
    "SP500": _fetch_sp500,
    "CSI300": _fetch_csi300,
    "BTC": _fetch_bitcoin,
    "US10Y": _fetch_us10y,
}


# ════════════════════════════════════════════════════════
#  Layer 1B: LLM 分析（DeepSeek）
# ════════════════════════════════════════════════════════

# 初始化 LLM（使用环境变量中的 DEEPSEEK_API_KEY 或 OPENAI_API_KEY）
_LLM_API_KEY = os.environ.get('DEEPSEEK_API_KEY') or os.environ.get('OPENAI_API_KEY')
_LLM = None
if _LLM_API_KEY:
    _LLM = ChatOpenAI(
        model='deepseek-chat',
        api_key=_LLM_API_KEY,
        base_url='https://api.deepseek.com/v1',
        temperature=0.3,
        timeout=30,
    )


_ANALYSIS_PROMPT = """你是金融数据解读员，专门帮普通人看懂数据。请分析以下 {asset_name} 的数据，用**大白话**说出来。

原始数据：
{raw_data_json}

请输出（控制在150字以内，不许用专业术语）：

1. **现在啥情况**：最新价多少，今天涨了还是跌了？
2. **怎么看**：看好/看跌/观望，一句话原因
3. **为什么**：用最容易懂的方式解释为什么会这样

⚠️ 禁止使用：支撑、阻力、震荡、超买超卖、情绪面、基本面、估值、驱动、动能、趋势等技术术语
✅ 只能使用：涨、跌、高了、低了、还行、不太行、看不懂"""


_SYNTHESIS_PROMPT = """你是一位面向普通读者的市场简报编辑。请将以下各资产分析整合成一份人人能读懂的每日简报，**让没有金融背景的人也能看懂**。

各资产分析：
{all_analyses}

请输出以下内容（**务必口语化、大白话，不许用任何专业术语**）：

## 今日市场怎么看

用1-2句话概括今天的市场整体感受，像朋友聊天一样。例如："今天整体还行，美股和A股都在涨，黄金继续创新高。"

## 每个品种一句话

每个品种按以下格式：

- **品种名**：最新价 | 看好/看跌/观望 | 一句话解释（越直白越好）

例如：
- **标普500**：7394点 | ✅ 看好 | 最近一直在涨，趋势不错
- **黄金**：4193美元 | ⚠️ 观望 | 涨太多了，后面可能会跌一跌
- **美元兑人民币**：6.78 | ✅ 看好人民币 | 人民币最近比较强，还在低位

## 有啥值得注意的

1-2条今天最值得一提的事，用大白话说。例如："黄金今天冲到4200附近了，创历史新高，但如果明天跌了也别意外。"

## 明天看什么

1条明天可以关注的事。

---
⚠️ **禁止使用的词汇**（一个都不用）：支撑位、阻力位、震荡中枢、超买、超卖、降息预期、地缘风险、资金流入、权重板块、技术性回调、宏观背景、数据指引、动量、趋势线、头肩顶、双底、布林带、KDJ、MACD、斐波那契、筹码、换手率、量能、情绪面、基本面、估值、溢价、折价

✅ **只能用的词汇**：涨、跌、高了、低了、在涨、在跌、可能要涨、可能要跌、还行、不太好、看不懂、稳住、不太好说

风格：像朋友在群里分享行情消息一样，自然、口语、好懂。"""


# ════════════════════════════════════════════════════════
#  Graph Nodes
# ════════════════════════════════════════════════════════

def node_init(state: FinanceState) -> Dict:
    """初始化节点：填充资产配置"""
    enabled = [a for a in ASSETS if a.get('enabled', True)]
    today = datetime.now(CST).strftime('%Y-%m-%d')
    print(f'🤖 每日金融情报官 Agent 启动 | {today}')
    print(f'📋 待采集资产: {len(enabled)} 个 ({", ".join(a["symbol"] for a in enabled)})')
    print('─' * 50)
    return {
        "assets_config": enabled,
        "raw_data": {},
        "errors": {},
        "analyses": {},
        "final_report": "",
        "approval_status": "pending",
        "human_feedback": "",
        "date": state.get("date") or today,
    }


def route_fetch(state: FinanceState) -> List[Send]:
    """Fan-out: 为每个启用的资产创建一个并行采集任务"""
    print('🚀 Fan-out: 并行采集所有资产...')
    return [Send("fetch_asset", {"cfg": cfg}) for cfg in state["assets_config"]]


def fetch_asset(inputs: Dict) -> Dict:
    """采集节点：根据 symbol 路由到对应的采集函数"""
    cfg = inputs["cfg"]
    fetcher = _FETCHERS.get(cfg["symbol"])
    if not fetcher:
        return {"errors": {cfg["symbol"]: f"未知资产: {cfg['symbol']}"}}
    
    result = fetcher()
    if result.get("success"):
        return {"raw_data": {cfg["symbol"]: result}}
    else:
        return {"errors": {cfg["symbol"]: result.get("error", "采集失败")}}


def node_log_results(state: FinanceState) -> Dict:
    """Fan-in 汇总: 打印采集结果并保存 JSON"""
    success_count = sum(1 for cfg in state["assets_config"] if cfg["symbol"] in state["raw_data"])
    error_count = len(state["errors"])
    total = len(state["assets_config"])
    
    print(f'\n📊 采集完成: {success_count}/{total} 成功, {error_count} 错误')
    for sym in state["raw_data"]:
        print(f'   ✅ {sym}')
    for sym, err in state["errors"].items():
        print(f'   ❌ {sym}: {err}')
    
    # 写入 JSON
    dt = datetime.now(CST)
    date_str = dt.strftime('%Y%m%d')
    output = {
        "fetch_time": dt.isoformat(),
        "date": dt.strftime('%Y-%m-%d'),
        "raw_data": state["raw_data"],
        "errors": state["errors"],
        "summary": {"total": total, "success": success_count, "errors": error_count},
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f'daily-data-agent-{date_str}.json'
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f'📁 数据已保存: {path}')
    print('─' * 50)
    return {}


def route_analyze(state: FinanceState) -> List[Send]:
    """Fan-out: 为每个成功采集的资产创建分析任务"""
    successful = [cfg for cfg in state["assets_config"] if cfg["symbol"] in state["raw_data"]]
    if not successful:
        print('⚠️ 没有成功采集的数据，跳过分析')
        return []
    
    print(f'🚀 Fan-out: 并行 LLM 分析 {len(successful)} 个资产...')
    return [
        Send("analyze_asset", {"cfg": cfg, "data": state["raw_data"][cfg["symbol"]]})
        for cfg in successful
    ]


def analyze_asset(inputs: Dict) -> Dict:
    """LLM 分析节点：对单个资产进行深度分析"""
    cfg = inputs["cfg"]
    data = inputs["data"]
    
    if _LLM is None:
        # Fallback: 无 LLM 时用简要文字
        return {"analyses": {cfg["symbol"]: f'{cfg["name"]}: 数据已采集（LLM 不可用，请配置 DEEPSEEK_API_KEY）'}}
    
    try:
        prompt = _ANALYSIS_PROMPT.format(
            asset_name=cfg["name"],
            asset_type=cfg["type"],
            raw_data_json=json.dumps(data, ensure_ascii=False, indent=2)
        )
        resp = _LLM.invoke([HumanMessage(content=prompt)])
        analysis = resp.content.strip()
        print(f'   ✅ {cfg["symbol"]} 分析完成 ({len(analysis)} 字)')
        return {"analyses": {cfg["symbol"]: analysis}}
    except Exception as e:
        print(f'   ⚠️ {cfg["symbol"]} LLM 分析失败: {e}')
        return {"analyses": {cfg["symbol"]: f'{cfg["name"]}: 分析失败 ({str(e)})'}}


def node_synthesize(state: FinanceState) -> Dict:
    """Fan-in 汇总: 将各资产分析合成完整日报"""
    if not state["analyses"]:
        return {"final_report": "⚠️ 无有效分析，无法生成报告。"}
    
    all_text = ""
    for cfg in state["assets_config"]:
        sym = cfg["symbol"]
        if sym in state["analyses"]:
            all_text += f"--- {cfg['name']} ({sym}) ---\n{state['analyses'][sym]}\n\n"
    
    report = ""
    if _LLM:
        try:
            resp = _LLM.invoke([
                HumanMessage(content=_SYNTHESIS_PROMPT.format(all_analyses=all_text))
            ])
            report = resp.content.strip()
        except Exception as e:
            print(f'⚠️ 合成报告 LLM 失败: {e}')
            report = _fallback_synthesis(state)
    else:
        report = _fallback_synthesis(state)
    
    # 添加头部和尾部标识
    dt = datetime.now(CST)
    weekday_map = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    weekday = weekday_map[dt.weekday()]
    header = f'# 📊 每日金融情报 | {dt.year}年{dt.month}月{dt.day}日 {weekday}\n\n'
    header += '—— 普通人也能看懂的行情简报 ——\n\n---\n\n'
    
    footer = f'\n---\n\n*🤖 自动生成 | {dt.strftime("%Y-%m-%d %H:%M")}*\n'
    footer += '*⚠️ 不构成投资建议，纯属AI胡扯。*'
    
    full_report = header + report + footer
    
    # 保存到文件
    date_str = dt.strftime('%Y-%m-%d')
    path = REPORTS_DIR / f'daily-finance-agent-{date_str}.md'
    with open(path, 'w', encoding='utf-8') as f:
        f.write(full_report)
    print(f'📄 Agent 日报已保存: {path}')
    
    return {"final_report": full_report}


def _fallback_synthesis(state: FinanceState) -> str:
    """无 LLM 时的备用合成"""
    lines = ['## 📋 今日市场速览\n']
    lines.append('| 品种 | 状态 |')
    lines.append('|:---|:---|')
    for cfg in state["assets_config"]:
        sym = cfg["symbol"]
        if sym in state["raw_data"]:
            lines.append(f'| {cfg["name"]} | ✅ 已采集 |')
        elif sym in state["errors"]:
            lines.append(f'| {cfg["name"]} | ❌ {state["errors"][sym][:30]} |')
    lines.append('')
    lines.append('*详细分析请配置 DEEPSEEK_API_KEY 后查看 LLM 版本。*')
    return '\n'.join(lines)


# ════════════════════════════════════════════════════════
#  构建 Graph
# ════════════════════════════════════════════════════════

def build_graph() -> StateGraph:
    """构建完整的 LangGraph 工作流"""
    
    builder = StateGraph(FinanceState)
    
    # Layer 1: 并行采集
    builder.add_node("init", node_init)
    builder.add_node("fetch_asset", fetch_asset)     # 被 Send 并行调用
    builder.add_node("log_results", node_log_results)  # Fan-in
    
    # Layer 1b: 并行分析
    builder.add_node("analyze_asset", analyze_asset)  # 被 Send 并行调用
    builder.add_node("synthesize", node_synthesize)    # Fan-in
    
    # ── 边 ──
    builder.add_edge(START, "init")
    
    # 采集阶段: init → fan-out → fetch_asset → log_results
    builder.add_conditional_edges("init", route_fetch, ["fetch_asset"])
    builder.add_edge("fetch_asset", "log_results")
    
    # 分析阶段: log_results → fan-out → analyze_asset → synthesize
    builder.add_conditional_edges("log_results", route_analyze, ["analyze_asset"])
    builder.add_edge("analyze_asset", "synthesize")
    
    # 合成后结束
    builder.add_edge("synthesize", END)
    
    # 内存持久化（为 Phase 3 审批准备）
    memory = MemorySaver()
    return builder.compile(checkpointer=memory)


# ════════════════════════════════════════════════════════
#  对外入口
# ════════════════════════════════════════════════════════

def run_agent_workflow(date_str: str = None) -> str:
    """
    运行完整的 Agent 工作流

    参数:
        date_str: YYYY-MM-DD (默认当天)

    返回:
        最终日报文本
    """
    graph = build_graph()
    
    config = {"configurable": {"thread_id": f"daily-finance-{datetime.now(CST).strftime('%Y%m%d')}"}}
    
    initial_state = FinanceState(
        date=date_str or datetime.now(CST).strftime('%Y-%m-%d'),
        assets_config=[],
        raw_data={},
        errors={},
        analyses={},
        final_report="",
        approval_status="pending",
        human_feedback="",
    )
    
    print('╔═══════════════════════════════════════╗')
    print('║    每日金融情报官 · LangGraph Agent    ║')
    print('╚═══════════════════════════════════════╝')
    print()
    
    t0 = datetime.now()
    
    # 支持流式输出
    for event in graph.stream(initial_state, config):
        for node_name, output in event.items():
            if output and any(output.values()):
                # 只打印一些关键节点
                pass
    
    # 获取最终状态
    final_state = graph.get_state(config)
    report = final_state.values.get("final_report", "")
    
    elapsed = (datetime.now() - t0).total_seconds()
    print()
    print('─' * 50)
    print(f'✅ Agent 工作流完成 | 耗时 {elapsed:.1f}s')
    
    return report


if __name__ == '__main__':
    report = run_agent_workflow()
    print()
    print(report)
