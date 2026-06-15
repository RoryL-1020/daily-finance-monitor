#!/usr/bin/env python3
"""
每日金融情报官 v3.0 — LangGraph Agent 报告生成 + 推送
══════════════════════════════════════════════════════════════

用法:
    # LangGraph Agent 模式（默认）
    python scripts/push_report.py                              # Agent 分析 + 推送微信
    python scripts/push_report.py -v                           # 详细输出
    python scripts/push_report.py --save-only                  # 只保存，不推送

    # 旧版模式（兼容已有数据）
    python scripts/push_report.py --legacy --date 2026-06-10   # 用已有 JSON 生成
    python scripts/push_report.py --legacy --save-only         # 旧版+不推送
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta

import requests

# ── 常量 ────────────────────────────────────────────
CST = timezone(timedelta(hours=8))
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
REPORTS_DIR = os.path.join(PROJECT_DIR, 'reports')

SERVERCHAN_KEY = os.environ.get('SERVERCHAN_KEY', 'SCT362303TTexZBrIevwuopTzWhoTcBUh7')
SERVERCHAN_URL = f'https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send'
WECOM_BOT_URL = os.environ.get('WECOM_BOT_URL', '')


# ════════════════════════════════════════════════════════
#  Agent 模式 — 调用 LangGraph 工作流
# ════════════════════════════════════════════════════════

def run_agent(date_str=None, verbose=False):
    """运行 Agent 工作流，返回报告文本"""
    if verbose:
        print('🤖 启动 LangGraph Agent 工作流...')

    # 动态导入以避免运行老代码时的依赖问题
    from scripts.agent_analyst import run_agent_workflow
    report = run_agent_workflow(date_str=date_str)

    if verbose:
        print(f'📄 Agent 日报已生成 ({len(report)} 字)')

    return report


# ════════════════════════════════════════════════════════
#  旧版模式 — 直接用 JSON 数据生成报告（兼容）
# ════════════════════════════════════════════════════════

def load_data(date_str, data_dir=REPORTS_DIR):
    """加载指定日期的采集数据"""
    filename = f'daily-data-{date_str.replace("-", "")}.json'
    path = os.path.join(data_dir, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f'数据文件不存在: {path}')
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def build_legacy_report(data):
    """旧版报告生成（完整保留 v2.0 逻辑）"""
    now = datetime.now(CST)
    date_str_cn = f'{now.year}年{now.month}月{now.day}日'
    weekday_map = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    weekday = weekday_map[now.weekday()]

    er = data.get('exchange_rate', {})
    tc = data.get('tencent', {})
    gl = data.get('gold', {})

    er_analysis = analyze_exchange_rate(er)
    tc_analysis = analyze_tencent(tc)
    gl_analysis = analyze_gold(gl)

    lines = []
    lines.append(f'# 📊 每日金融情报 | {date_str_cn} {weekday}')
    lines.append('')
    lines.append('—— Legend 深度研判 · 数据驱动决策 ——')
    lines.append('')
    lines.append('---')
    lines.append('')

    # ── 市场全景 ──
    lines.append('## 📋 今日市场全景')
    lines.append('')
    lines.append('| 品种 | 最新价 | 涨跌幅 | 信号 |')
    lines.append('|:---|:---:|:---:|:---|')
    if tc.get('success'):
        lines.append(f'| 📈 腾讯控股 | {tc["current_price"]} 港元 | {tc_analysis["change_pct"]} | {tc_analysis["direction"]} |')
    if gl.get('success'):
        lines.append(f'| 🥇 黄金 XAU/USD | ${gl_analysis["price"]:,.0f} | — | {gl_analysis["zone"]} |')
    if er.get('success'):
        lines.append(f'| 💱 USD/CNY | {er["rate"]} | — | {er_analysis["judgment"]} |')
    lines.append('')

    # ── 腾讯深度 ──
    lines.append('---\n')
    lines.append('## 📈 腾讯控股 (00700.HK) 深度分析\n')
    lines.append(f'> **{tc_analysis["direction"]} · {tc_analysis["volatility"]} · 振幅 {tc_analysis["amplitude"]}**\n')
    lines.append(f'| 指标 | 今日数据 |')
    lines.append(f'|:---|:---|')
    lines.append(f'| 最新收盘 | **{tc["current_price"]} 港元** |')
    lines.append(f'| 涨跌幅 | {tc_analysis["change_pct"]}（{tc_analysis["change_val"]}） |')
    lines.append(f'| 今日区间 | {tc["low"]} — {tc["high"]} 港元 |')
    lines.append(f'| 昨收 | {tc.get("prev_close","—")} 港元 |')
    lines.append(f'| 开盘 | {tc.get("open_price","—")} 港元 |')
    lines.append('')
    lines.append(f'**📍 关键价位：**\n')
    lines.append(f'| 基准 | 价位 | 距离现价 |')
    lines.append(f'|:---|:---:|:---|')
    lines.append(f'| 52周高点 | {tc_analysis["year_high"]} | 现价距高点 {tc_analysis["distance_from_high"]} |')
    lines.append(f'| 52周低点 | {tc_analysis["year_low"]} | 现价距低点 {tc_analysis["distance_from_low"]} |')
    lines.append(f'| 高盛目标价 | 700 | +{(700/tc["current_price"]-1)*100:.0f}% |')
    lines.append('')
    lines.append(f'**🔥 近期催化事件：**\n')
    for ev in tc_analysis['recent_events']:
        lines.append(f'- {ev}')
    lines.append('')
    lines.append(f'**📌 核心研判：**\n')
    lines.append(tc_analysis['detail'])
    lines.append('')

    # ── 黄金深度 ──
    lines.append('---\n')
    lines.append('## 🥇 黄金 (XAU/USD) 深度分析\n')
    lines.append(f'> **{gl_analysis["zone"]} · {gl_analysis["level"]}**\n')
    lines.append(f'| 指标 | 数据 |')
    lines.append(f'|:---|:---|')
    lines.append(f'| 最新价格 | **${gl_analysis["price"]:,.2f}/盎司** |')
    lines.append(f'| 数据源 | {gl["source"]} |')
    lines.append('')
    lines.append(f'**📊 宏观背景：**\n')
    for item in gl_analysis['gold_context']:
        lines.append(f'- {item}')
    lines.append('')
    lines.append(f'**🆙 看多逻辑：**\n')
    for item in gl_analysis['bull_case']:
        lines.append(f'- ✅ {item}')
    lines.append('')
    lines.append(f'**🔻 看空逻辑：**\n')
    for item in gl_analysis['bear_case']:
        lines.append(f'- ⚠️ {item}')
    lines.append('')
    lines.append(f'**📌 核心研判：**\n')
    lines.append('金价从年初$5,600+高点回调至$4,000附近企稳，属于大涨后的健康调整。')
    lines.append('中长期看多逻辑未破坏（央行购金、去美元化、降息周期），')
    lines.append('但短期波动加剧，$4,000-4,500成为新的震荡中枢。')
    lines.append('')

    # ── 汇率 ──
    lines.append('---\n')
    lines.append('## 💱 美元兑人民币 分析\n')
    lines.append(f'> **{er_analysis["judgment"]} · {er_analysis["level"]}**\n')
    lines.append(f'| 指标 | 数据 |')
    lines.append(f'|:---|:---|')
    lines.append(f'| 在岸参考 | **{er["rate"]}** |')
    lines.append(f'| 数据源 | {er["source"]} |')
    lines.append('')
    lines.append(f'**📌 核心研判：**\n')
    lines.append(er_analysis['yoy_change'] + '。')
    lines.append(er_analysis['forecast'] + '。')
    lines.append('')

    # ── 明日关注 ──
    lines.append('---\n')
    lines.append('## 🔮 明日关注\n')
    lines.append('| 关注点 | 预期影响 |')
    lines.append('|:---|:---|')
    lines.append('| 📊 美国经济数据公布 | 影响降息预期 → 黄金/汇率波动 |')
    lines.append('| 🏢 腾讯回购公告 | 每日5亿回购是否延续 |')
    lines.append('| 🌍 美伊谈判进展 | 地缘风险溢价→金价/油价 |')
    lines.append('| 🏛️ 央行中间价 | 人民币汇率政策信号 |')
    lines.append('')

    # ── Footer ──
    lines.append('---')
    lines.append(f'*📱 报告生成：{now.strftime("%Y-%m-%d %H:%M")} |*')
    lines.append(f'*⚡ 数据仅供参考，不构成投资建议。*')

    return '\n'.join(lines)


# ── 旧版分析函数（完整保留） ─────────────────────────

def analyze_exchange_rate(er):
    if not er.get('success'):
        return {'summary': '数据异常', 'judgment': '采集失败', 'detail': er.get('error', '')}
    rate = float(er['rate'])
    if rate > 7.2: level, judgment = '高位', '人民币承压'
    elif rate > 7.0: level, judgment = '中高位', '温和贬值'
    elif rate > 6.8: level, judgment = '中位', '窄幅震荡'
    elif rate > 6.6: level, judgment = '中低位', '人民币偏强'
    else: level, judgment = '低位', '人民币强势'
    return {
        'summary': f'美元兑人民币 {rate}', 'level': level, 'judgment': judgment,
        'yoy_change': '过去12个月人民币升值约5.53%',
        'forecast': f'模型预测本季度末 6.76，12个月后 6.71',
        'detail': f'人民币处于{level}震荡区间。过去12个月人民币升值约5.53%。'
    }


def analyze_tencent(tc):
    if not tc.get('success'):
        return {'summary': '数据异常', 'judgment': '采集失败', 'detail': tc.get('error', '')}
    price = tc['current_price']
    change_pct = float(tc.get('change_percent', '0%').replace('%', ''))
    high, low, prev_close = float(tc.get('high',0) or 0), float(tc.get('low',0) or 0), float(tc.get('prev_close',0) or 0)
    amplitude = ((high - low) / prev_close * 100) if prev_close else 0
    direction = '大涨 📈' if change_pct > 3 else '上涨 📈' if change_pct > 1 else '微涨 ↗' if change_pct > 0 else '微跌 ↘' if change_pct > -1 else '下跌 📉' if change_pct > -3 else '大跌 📉'
    volatility = '剧烈震荡' if amplitude > 5 else '明显波动' if amplitude > 3 else '正常波动' if amplitude > 1.5 else '窄幅整理'
    year_high, year_low = 675.1, 420.4
    return {
        'summary': f'腾讯控股 {price} 港元', 'direction': direction, 'volatility': volatility,
        'amplitude': f'{amplitude:.1f}%', 'change_pct': f'{change_pct:.3f}%',
        'change_val': f'{float(tc.get("change",0) or 0):+.1f}',
        'high': high, 'low': low,
        'recent_events': [
            '6/2 腾讯暴涨10.46%，微信AI Agent概念引爆',
            '6/6 腾讯云发布「效率智能体工具集」',
            '6/6 微信联合华为/荣耀/小米开放A2A能力',
        ],
        'year_high': year_high, 'year_low': year_low,
        'distance_from_high': f'{(year_high-price)/year_high*100:.1f}%',
        'distance_from_low': f'{(price-year_low)/price*100:.1f}%',
        'detail': f'今日{volatility}，振幅{amplitude:.1f}%。当前股价距52周高点({year_high})还有{(year_high-price)/year_high*100:.0f}%空间，距52周低点({year_low})已反弹{(price-year_low)/price*100:.0f}%。'
    }


def analyze_gold(gl):
    if not gl.get('success'):
        return {'summary': '数据异常', 'judgment': '采集失败', 'detail': gl.get('error', '')}
    price = float(gl['price_usd'])
    if price > 5000: level, zone = '极端高位', '🟣 历史峰值区域'
    elif price > 4000: level, zone = '历史高位', '🟡 历史高位区域'
    elif price > 3000: level, zone = '偏高', '🟢 偏高区域'
    elif price > 2000: level, zone = '中位', '🔵 中性区域'
    else: level, zone = '低位', '⚪ 低位区域'
    return {
        'summary': f'XAU/USD ${price:,.2f}', 'zone': zone, 'level': level, 'price': price,
        'gold_context': [
            '2025年全年涨幅超60%，创1979年以来最大年涨幅',
            '年初冲高至$5,600+后大幅回调',
            '全球央行持续增持黄金',
        ],
        'bull_case': ['美联储降息周期推进', '全球央行去美元化', '地缘风险支撑'],
        'bear_case': ['鹰派美联储预期限制降息空间', '需时间消化前期超涨'],
        'detail': f'金价处于{level}。2025年创下+60%年涨幅后回调，目前在$4,000上方震荡整固。'
    }


# ════════════════════════════════════════════════════════
#  通用工具函数
# ════════════════════════════════════════════════════════

def save_report(markdown_content, date_str, report_dir=REPORTS_DIR):
    """保存日报"""
    os.makedirs(report_dir, exist_ok=True)
    filename = f'daily-finance-{date_str}.md'
    path = os.path.join(report_dir, filename)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(markdown_content)
    return path


def push_to_serverchan(title, content, verbose=False, data=None):
    """ServerChan 微信推送"""
    if not SERVERCHAN_KEY or SERVERCHAN_KEY == 'YOUR_SERVERCHAN_KEY_HERE':
        print('❌ 未配置 ServerChan SendKey')
        return False
    try:
        push_content = content
        # 尝试使用微信专用排版
        if data:
            try:
                from wechat_format import build_wechat_content
                push_content = build_wechat_content(data)
            except Exception:
                pass
        resp = requests.post(SERVERCHAN_URL, data={
            'title': title, 'desp': push_content,
        }, timeout=15)
        resp.raise_for_status()
        result = resp.json()
        if result.get('code') == 0:
            if verbose: print('   ✅ ServerChan 推送成功')
            return True
        else:
            print(f'   ❌ ServerChan 推送失败: {result.get("message", "未知")}')
            return False
    except Exception as e:
        print(f'   ❌ ServerChan 推送异常: {e}')
        return False


def push_to_wecom_bot(content, verbose=False):
    """企业微信群机器人（可选）"""
    if not WECOM_BOT_URL:
        return False
    try:
        resp = requests.post(WECOM_BOT_URL, json={
            'msgtype': 'markdown', 'markdown': {'content': content}
        }, timeout=15)
        if verbose: print('   ✅ 企微推送成功')
        return True
    except Exception as e:
        if verbose: print(f'   ❌ 企微推送异常: {e}')
        return False


# ════════════════════════════════════════════════════════
#  入口
# ════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='每日金融情报官 v3.0 — LangGraph Agent')
    parser.add_argument('--date', default=None,
                        help='报告日期 (默认当天)')
    parser.add_argument('--save-only', action='store_true',
                        help='只生成日报，不推送')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='详细输出')
    parser.add_argument('--legacy', action='store_true',
                        help='旧版模式：用已有 JSON 数据生成')
    args = parser.parse_args()

    date_str = args.date or datetime.now(CST).strftime('%Y-%m-%d')
    data = None

    if args.legacy:
        # ── 旧版模式 ──
        if args.verbose:
            print(f'📂 读取已有数据: {date_str}  (旧版模式)')
        try:
            data = load_data(date_str)
        except FileNotFoundError as e:
            print(f'❌ {e}')
            sys.exit(1)
        report = build_legacy_report(data)
    else:
        # ── Agent 模式（默认）──
        report = run_agent(date_str=date_str, verbose=args.verbose)

    # 存档
    report_path = save_report(report, date_str)
    print(f'📄 报告已存档: {report_path}')

    # 推送
    if not args.save_only:
        now = datetime.now(CST)
        mode_tag = '[Agent]' if not args.legacy else '[Legacy]'
        title = f'{mode_tag} 每日金融情报 | {now.month}月{now.day}日'
        if args.verbose:
            print(f'📱 正在推送...')

        # 旧版模式传 data 给微信排版；Agent 模式直接用报告内容
        push_report = report
        push_data = data if args.legacy else None

        ok = push_to_serverchan(title, push_report, verbose=args.verbose, data=push_data)
        ok2 = push_to_wecom_bot(push_report, verbose=args.verbose)

        results = [('ServerChan', ok)]
        if ok2:
            results.append(('企微', ok2))
        success_count = sum(1 for _, ok in results if ok)
        print(f'✅ 推送: {success_count}/{len(results)} 通道成功')
    else:
        print('⏭️ 跳过推送 (--save-only)')


if __name__ == '__main__':
    main()
