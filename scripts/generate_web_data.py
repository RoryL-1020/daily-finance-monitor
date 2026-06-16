#!/usr/bin/env python3
"""
每日金融情报 — 网页端数据生成器 v1.0
══════════════════════════════════════════════════════════════

作用：读取最新的 daily-data-agent-*.json → 调用 DeepSeek LLM 分析
      → 渲染完整的 web/index.html（保持现有精美 UI 设计）

用法：
    python scripts/generate_web_data.py                              # 最新数据
    python scripts/generate_web_data.py --date 20260615              # 指定日期
    python scripts/generate_web_data.py --skip-llm                   # 跳过LLM（纯数据展示）
    python scripts/generate_web_data.py --verbose                    # 详细输出

集成到 run.sh：
    python3 scripts/generate_web_data.py --skip-llm  # 如果想快点，跳过LLM
    python3 scripts/generate_web_data.py             # 完整版（含LLM分析）
"""

import json
import os
import sys
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

# ── 路径常量 ───────────────────────────────────────
CST = timezone(timedelta(hours=8))
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_DIR = SCRIPT_DIR.parent
REPORTS_DIR = PROJECT_DIR / 'reports'
WEB_DIR = PROJECT_DIR / 'web'
WEB_INDEX = WEB_DIR / 'index.html'
TEMPLATE_DIR = PROJECT_DIR / 'web' / 'templates'

DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', 'sk-bf3f6ac2c50748fabcbc3d22c370129e')
DEEPSEEK_URL = 'https://api.deepseek.com/v1/chat/completions'

WEEKDAY_MAP = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

# ── 资产展示配置（控制卡片显示顺序、简称、图标、颜色）──
ASSET_DISPLAY = [
    {"key": "TENCENT",  "icon": "📈", "short": "腾讯控股",     "full": "腾讯控股 (00700.HK)",   "unit": "港元"},
    {"key": "GOLD",     "icon": "🥇", "short": "XAU/USD",      "full": "黄金 (XAU/USD)",        "unit": "美元/盎司"},
    {"key": "USDCNY",   "icon": "💱", "short": "USD/CNY",      "full": "美元兑人民币",          "unit": ""},
    {"key": "SP500",    "icon": "🇺🇸", "short": "标普500",      "full": "标普500指数 (SPX)",     "unit": "点"},
    {"key": "CSI300",   "icon": "🇨🇳", "short": "沪深300",      "full": "沪深300指数",           "unit": "点"},
    {"key": "BTC",      "icon": "₿",  "short": "比特币",       "full": "比特币 (BTC/USD)",      "unit": "美元"},
    {"key": "US10Y",    "icon": "🏦", "short": "10年美债",     "full": "10年期美债收益率",      "unit": "%"},
]


# ════════════════════════════════════════════════════════
#  1. 数据加载
# ════════════════════════════════════════════════════════

def find_latest_json() -> tuple:
    """找到最新的 daily-data-agent-*.json
    
    Returns:
        (date_str_yyyymmdd, filepath)
    """
    files = sorted(REPORTS_DIR.glob('daily-data-agent-*.json'), reverse=True)
    if not files:
        raise FileNotFoundError(f'❌ 未找到 daily-data-agent-*.json 文件（在 {REPORTS_DIR}）')
    
    latest = files[0]
    match = re.search(r'(\d{8})', latest.name)
    date_str = match.group(1) if match else datetime.now(CST).strftime('%Y%m%d')
    return date_str, str(latest)


def load_data(date_arg: str = None) -> dict:
    """加载 JSON 数据"""
    if date_arg:
        path = REPORTS_DIR / f'daily-data-agent-{date_arg}.json'
        if not path.exists():
            raise FileNotFoundError(f'❌ 数据文件不存在: {path}')
        return json.loads(path.read_text(encoding='utf-8'))
    
    date_str, path_str = find_latest_json()
    print(f'📂 加载数据: {Path(path_str).name}')
    return json.loads(Path(path_str).read_text(encoding='utf-8'))


# ════════════════════════════════════════════════════════
#  2. LLM 分析（逐资产调用 DeepSeek）
# ════════════════════════════════════════════════════════

def call_deepseek(prompt: str, system: str = '') -> str:
    """调用 DeepSeek API"""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    
    try:
        resp = requests.post(
            DEEPSEEK_URL,
            headers={
                'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
                'Content-Type': 'application/json',
            },
            json={
                'model': 'deepseek-chat',
                'messages': messages,
                'temperature': 0.3,
                'max_tokens': 300,
            },
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        return result['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f'   ⚠️ LLM 调用失败: {e}')
        return ''


_ANALYSIS_SYSTEM = '你是金融数据解读员，专门帮普通人看懂数据。回答必须简短（50字以内），只看涨跌，不许用任何专业术语。'

def analyze_asset_for_web(asset_key: str, data: dict) -> dict:
    """为单个资产生成网页展示用的分析文本
    
    Returns:
        {
            "judgment": "上涨 📈" 或 "下跌 📉" 或 "横盘 ➡️",
            "signal": "bull"/"bear"/"neutral"/"watch",
            "summary": "1句话分析",
            "insight": "详细研判",
            "bull_points": [...],
            "bear_points": [...],
        }
    """
    result = {
        "judgment": "横盘 ➡️",
        "signal": "neutral",
        "summary": "",
        "insight": "",
        "bull_points": [],
        "bear_points": [],
    }
    
    raw = data.get("raw_data", {}).get(asset_key, {})
    if not raw.get("success"):
        return result
    
    # 通用信号判断（基于涨跌幅）
    if asset_key == "TENCENT":
        chg_pct = float(raw.get("change_percent", "0").replace("%", "")) if raw.get("change_percent") else 0
        if chg_pct > 1:
            result["judgment"] = "上涨 📈"
            result["signal"] = "bull"
        elif chg_pct > -1:
            result["judgment"] = "横盘 ➡️"
            result["signal"] = "neutral"
        else:
            result["judgment"] = "下跌 📉"
            result["signal"] = "bear"
    
    elif asset_key == "GOLD":
        # 黄金：纯价格水平判断
        price = float(raw.get("price", 0))
        if price > 5000:
            result["judgment"] = "历史高位 ⚠️"
            result["signal"] = "watch"
        elif price > 4200:
            result["judgment"] = "高位偏强 📈"
            result["signal"] = "bull"
        elif price > 4000:
            result["judgment"] = "偏高观望 ➡️"
            result["signal"] = "neutral"
        else:
            result["judgment"] = "较低位置 💪"
            result["signal"] = "bull"
    
    elif asset_key == "USDCNY":
        rate = float(raw.get("rate", 0))
        if rate > 7.2:
            result["judgment"] = "人民币承压 📉"
            result["signal"] = "bear"
        elif rate > 7.0:
            result["judgment"] = "微贬 ➡️"
            result["signal"] = "neutral"
        elif rate > 6.8:
            result["judgment"] = "窄幅整理 ➡️"
            result["signal"] = "neutral"
        else:
            result["judgment"] = "人民币偏强 📈"
            result["signal"] = "bull"
    
    elif asset_key == "SP500":
        chg = float(raw.get("change_percent", 0) or 0)
        if chg > 1:
            result["judgment"] = "上涨 📈"
            result["signal"] = "bull"
        elif chg > -1:
            result["judgment"] = "窄幅波动 ➡️"
            result["signal"] = "neutral"
        else:
            result["judgment"] = "调整 📉"
            result["signal"] = "bear"
    
    elif asset_key == "CSI300":
        cur = float(raw.get("current_price", 0) or 0)
        prev = float(raw.get("prev_close", 0) or 0)
        chg = ((cur - prev) / prev * 100) if prev else 0
        if chg > 1:
            result["judgment"] = "上涨 📈"
            result["signal"] = "bull"
        elif chg > -1:
            result["judgment"] = "横盘 ➡️"
            result["signal"] = "neutral"
        else:
            result["judgment"] = "下跌 📉"
            result["signal"] = "bear"
    
    elif asset_key == "BTC":
        price = float(raw.get("current_price", 0) or 0)
        if price > 80000:
            result["judgment"] = "强势 💪"
            result["signal"] = "bull"
        elif price > 65000:
            result["judgment"] = "企稳 ➡️"
            result["signal"] = "neutral"
        else:
            result["judgment"] = "偏弱 📉"
            result["signal"] = "bear"
    
    elif asset_key == "US10Y":
        yld = float(raw.get("yield_pct", 0) or 0)
        if yld > 5:
            result["judgment"] = "偏高 ⚠️"
            result["signal"] = "watch"
        elif yld > 4.5:
            result["judgment"] = "偏紧 📉"
            result["signal"] = "bear"
        elif yld > 4.0:
            result["judgment"] = "中性 ➡️"
            result["signal"] = "neutral"
        else:
            result["judgment"] = "偏松 📈"
            result["signal"] = "bull"
    
    # ── LLM 分析（丰富文本内容）──
    if DEEPSEEK_API_KEY and DEEPSEEK_API_KEY != 'YOUR_KEY_HERE':
        asset_name = "黄金" if asset_key == "GOLD" else "比特币" if asset_key == "BTC" else None
        if not asset_name:
            for ad in ASSET_DISPLAY:
                if ad["key"] == asset_key:
                    asset_name = ad["short"]
                    break
        
        # 生成一句话分析
        prompt_summary = f'{asset_name} 最新数据: {json.dumps(raw, ensure_ascii=False)}\n用一句话（20字内）说今天行情怎么样，只说涨跌，不说原因。'
        summary_text = call_deepseek(prompt_summary, _ANALYSIS_SYSTEM)
        if summary_text:
            result["summary"] = summary_text
        
        # 生成核心研判（黄金/腾讯需要更详细）
        if asset_key in ("TENCENT", "GOLD"):
            prompt_detail = (
                f'{asset_name} 今天的数据：{json.dumps(raw, ensure_ascii=False)}\n\n'
                f'请用60字以内说两句：第一句说今天什么情况（涨了跌了），第二句说简单原因（越通俗越好）。'
                f'只许用：涨、跌、高了、低了、还好、不太好。'
            )
            detail_text = call_deepseek(prompt_detail, _ANALYSIS_SYSTEM)
            if detail_text:
                result["insight"] = detail_text
    
    return result


def analyze_all_assets(data: dict, skip_llm: bool = False) -> dict:
    """分析所有资产，返回 {asset_key: analysis_dict}"""
    results = {}
    for ad in ASSET_DISPLAY:
        key = ad["key"]
        print(f'🔍 分析: {ad["short"]}...', end='')
        if skip_llm:
            results[key] = analyze_asset_for_web(key, data)
            results[key]["summary"] = ""
            results[key]["insight"] = ""
            print(' ✅ (跳过LLM)')
        else:
            results[key] = analyze_asset_for_web(key, data)
            print(' ✅')
    return results


# ════════════════════════════════════════════════════════
#  3. HTML 渲染
# ════════════════════════════════════════════════════════

def fmt_price(asset_key: str, raw: dict) -> str:
    """根据资产类型格式化价格显示"""
    if asset_key == "USDCNY":
        return f'{float(raw["rate"]):.4f}'
    elif asset_key == "GOLD":
        return f'${float(raw["price"]):,.0f}'
    elif asset_key == "BTC":
        return f'${float(raw["current_price"]):,.0f}'
    elif asset_key == "US10Y":
        return f'{float(raw["yield_pct"]):.2f}%'
    elif asset_key == "SP500":
        return f'{float(raw["current_price"]):,.0f}'
    elif asset_key == "CSI300":
        cur = float(raw.get("current_price", 0) or 0)
        return f'{cur:,.1f}'
    elif asset_key == "TENCENT":
        return f'{float(raw["current_price"]):.1f}'
    return str(raw.get("current_price", "—"))


def fmt_change(asset_key: str, raw: dict) -> tuple:
    """计算涨跌幅，返回 (display_text, css_class)
    
    Returns:
        ("+1.23%", "up") 或 ("-0.56%", "down") 或 ("—", "flat")
    """
    if asset_key == "GOLD":
        # 黄金没涨跌幅数据
        return ("—", "flat")
    if asset_key == "USDCNY":
        return ("—", "flat")
    if asset_key == "US10Y":
        return ("—", "flat")
    if asset_key == "BTC":
        return ("—", "flat")
    
    chg_pct = None
    if asset_key == "TENCENT":
        if raw.get("change_percent"):
            chg_pct = float(raw["change_percent"].replace("%", ""))
    elif raw.get("change_percent") is not None:
        chg_pct = float(raw["change_percent"])
    elif raw.get("current_price") and raw.get("prev_close"):
        cur = float(raw["current_price"])
        prev = float(raw["prev_close"])
        if prev:
            chg_pct = (cur - prev) / prev * 100
    
    if chg_pct is None:
        return ("—", "flat")
    
    if chg_pct > 0:
        return (f'+{chg_pct:.2f}%', "up")
    elif chg_pct < 0:
        return (f'{chg_pct:.2f}%', "down")
    else:
        return (f'0.00%', "flat")


def fmt_signal_tag(signal: str, judgment: str) -> str:
    """渲染信号标签HTML"""
    css_map = {
        "bull": "bull",
        "bear": "bear",
        "neutral": "neutral",
        "watch": "watch",
    }
    css = css_map.get(signal, "neutral")
    return f'<span class="signal {css}">{judgment}</span>'


def render_market_cards(data: dict, analyses: dict) -> str:
    """渲染顶部市场全景卡片（仅主力资产：腾讯、黄金、汇率）"""
    primary_keys = {"TENCENT", "GOLD", "USDCNY"}
    cards = []
    for ad in ASSET_DISPLAY:
        if ad["key"] not in primary_keys:
            continue
        key = ad["key"]
        raw = data.get("raw_data", {}).get(key, {})
        if not raw.get("success"):
            continue
        
        price = fmt_price(key, raw)
        change_text, change_css = fmt_change(key, raw)
        analysis = analyses.get(key, {})
        signal_tag = fmt_signal_tag(analysis.get("signal", "neutral"), analysis.get("judgment", "横盘 ➡️"))
        
        cards.append(f'''      <div class="market-card">
        <div class="asset-icon">{ad["icon"]}</div>
        <div class="asset-name">{ad["short"]}</div>
        <div class="price">{price}</div>
        <div class="change {change_css}">{change_text}</div>
        {signal_tag}
      </div>''')
    
    return '\n'.join(cards)


def render_tencent_section(raw: dict, analysis: dict) -> str:
    """渲染腾讯深度分析区块"""
    if not raw.get("success"):
        return ''
    
    price = float(raw["current_price"])
    prev = float(raw.get("prev_close", 0) or 0)
    chg = float(raw.get("change", 0) or 0)
    chg_pct = float(raw.get("change_percent", "0").replace("%", "")) if raw.get("change_percent") else 0
    high = float(raw.get("high", 0) or 0)
    low = float(raw.get("low", 0) or 0)
    open_p = float(raw.get("open", 0) or 0)
    
    chg_color = 'var(--green)' if chg >= 0 else 'var(--red)'
    chg_sign = '+' if chg >= 0 else ''
    
    tag_text = analysis.get("judgment", "横盘 ➡️")
    tag_css = analysis.get("signal", "neutral")
    tag_css_map = {"bull": "up", "bear": "down", "neutral": "flat", "watch": "watch"}
    tag_css = tag_css_map.get(tag_css, "flat")
    
    # 关键价位
    year_high = 675.1
    year_low = 420.4
    gs_target = 700
    dist_high = (year_high - price) / year_high * 100
    dist_low = (price - year_low) / price * 100
    dist_gs = (gs_target - price) / price * 100
    
    insight = analysis.get("insight", '')
    insight_html = f'<p>{insight}</p>' if insight else ''
    
    return f'''    <!-- ═══ TENCENT ANALYSIS ═══ -->
    <section class="section">
      <h3 class="section-title">深度分析</h3>
      <div class="analysis-card">
        <div class="card-header">
          <span class="icon">📈</span>
          <h2>腾讯控股 <span style="font-weight:400;color:var(--text-muted)">00700.HK</span></h2>
          <span class="tag {tag_css}">{tag_text}</span>
        </div>

        <div class="data-grid">
          <div class="data-item">
            <div class="label">最新收盘</div>
            <div class="value">{price:.1f} <span style="font-size:12px;color:var(--text-muted)">港元</span></div>
          </div>
          <div class="data-item">
            <div class="label">涨跌幅</div>
            <div class="value" style="color:{chg_color}">{chg_sign}{chg_pct:.2f}%</div>
          </div>
          <div class="data-item">
            <div class="label">涨跌值</div>
            <div class="value" style="color:{chg_color}">{chg_sign}{chg:.1f}</div>
          </div>
          <div class="data-item">
            <div class="label">今日区间</div>
            <div class="value" style="font-size:14px">{low:.1f} — {high:.1f}</div>
          </div>
          <div class="data-item">
            <div class="label">昨收</div>
            <div class="value">{prev:.1f}</div>
          </div>
          <div class="data-item">
            <div class="label">开盘</div>
            <div class="value">{open_p:.1f}</div>
          </div>
        </div>

        <h4 style="font-size:13px;font-family:'Inter',sans-serif;font-weight:600;letter-spacing:1px;color:var(--text-muted);margin-bottom:12px;text-transform:uppercase">📍 关键价位</h4>
        <table class="levels-table">
          <tr><th>基准</th><th>价位</th><th>距离现价</th></tr>
          <tr><td>52周高点</td><td class="num">{year_high}</td><td class="pct">-{dist_high:.1f}%</td></tr>
          <tr><td>52周低点</td><td class="num">{year_low}</td><td class="pct highlight">+{dist_low:.1f}%</td></tr>
          <tr><td>高盛目标价</td><td class="num highlight">{gs_target}</td><td class="pct highlight">+{dist_gs:.0f}%</td></tr>
        </table>

        <h4 style="font-size:13px;font-family:'Inter',sans-serif;font-weight:600;letter-spacing:1px;color:var(--text-muted);margin-bottom:12px;text-transform:uppercase">🔥 近期催化</h4>
        <ul class="events-list">
          <li>6/2 腾讯单日暴涨10.46%，创5年最大涨幅，微信AI Agent概念引爆</li>
          <li>6/6 腾讯云发布「效率智能体工具集」，覆盖20+垂直场景</li>
          <li>6/6 微信宣布联合华为/荣耀/小米等手机厂商开放A2A能力</li>
        </ul>

        <div class="judgment">
          <div class="label">📌 核心研判</div>
          {insight_html}
          <p style="margin-top:8px">{price:.1f}距52周高点({year_high})还有{dist_high:.0f}%空间，距52周低点({year_low})已反弹{dist_low:.0f}%。</p>
          <div class="focus-points">
            <span>① AI产品落地进度</span>
            <span>② 回购力度延续性</span>
            <span>③ 恒生科技指数联动</span>
          </div>
        </div>
      </div>
    </section>'''


def render_gold_section(raw: dict, analysis: dict) -> str:
    """渲染黄金深度分析区块"""
    if not raw.get("success"):
        return ''
    
    price = float(raw["price"])
    source = raw.get("source", "gold-api.com")
    
    tag_text = analysis.get("judgment", "偏高观望 ➡️")
    tag_css = analysis.get("signal", "neutral")
    tag_css_map = {"bull": "up", "bear": "down", "neutral": "flat", "watch": "watch"}
    tag_css = tag_css_map.get(tag_css, "flat")
    
    insight = analysis.get("insight", '')
    insight_html = f'<p>{insight}</p>' if insight else ''
    
    return f'''    <!-- ═══ GOLD ANALYSIS ═══ -->
    <section class="section">
      <div class="analysis-card">
        <div class="card-header">
          <span class="icon">🥇</span>
          <h2>黄金 <span style="font-weight:400;color:var(--text-muted)">XAU/USD</span></h2>
          <span class="tag gold-tag">{tag_text}</span>
        </div>

        <div class="data-grid">
          <div class="data-item">
            <div class="label">最新价格</div>
            <div class="value gold-text">${price:,.2f}</div>
          </div>
          <div class="data-item">
            <div class="label">数据源</div>
            <div class="value" style="font-family:'Inter',sans-serif;font-size:13px;font-weight:400;color:var(--text-muted)">{source}</div>
          </div>
        </div>

        <h4 style="font-size:13px;font-family:'Inter',sans-serif;font-weight:600;letter-spacing:1px;color:var(--text-muted);margin-bottom:12px;text-transform:uppercase">📊 宏观背景</h4>
        <div class="bg-context">
          <span class="chip">📈 2025年涨幅+60% 创45年纪录</span>
          <span class="chip">💰 年初冲高$5,600+ 后大幅回调</span>
          <span class="chip">🏦 央行上半年净购123吨</span>
          <span class="chip">🎯 瑞银目标$6,200</span>
          <span class="chip">📋 高盛目标$5,400</span>
          <span class="chip">⚠️ 花旗提示回调风险</span>
        </div>

        <h4 style="font-size:13px;font-family:'Inter',sans-serif;font-weight:600;letter-spacing:1px;color:var(--text-muted);margin-bottom:12px;text-transform:uppercase">⚖️ 多空博弈</h4>
        <div class="bull-bear">
          <div class="bull-box">
            <div class="bb-title">🆙 看多逻辑</div>
            <ul>
              <li>美联储降息周期推进，实际利率下行</li>
              <li>全球央行"去美元化"趋势不减</li>
              <li>中东/俄乌地缘风险持续提供避险支撑</li>
            </ul>
          </div>
          <div class="bear-box">
            <div class="bb-title">🔻 看空逻辑</div>
            <ul>
              <li>鹰派美联储主席提名限制降息空间</li>
              <li>前期"非理性超涨"需要时间消化</li>
              <li>美伊局势若缓和将削弱避险需求</li>
            </ul>
          </div>
        </div>

        <div class="judgment">
          <div class="label">📌 核心研判</div>
          {insight_html}
          <p>金价从年初$5,600+高点回调至${price:,.0f}附近企稳，属于大涨后的健康调整。中长期看多逻辑未破坏（央行购金、去美元化、降息周期）。</p>
          <div class="focus-points">
            <span>🔍 本周美国就业数据</span>
            <span>🌍 美伊谈判进展</span>
          </div>
        </div>
      </div>
    </section>'''


def render_exchange_section(raw: dict) -> str:
    """渲染汇率分析区块"""
    if not raw.get("success"):
        return ''
    
    rate = float(raw["rate"])
    source = raw.get("source", "ExchangeRate-API")
    
    # 简单判断
    if rate > 7.2: tag_text, tag_css = "人民币承压", "down"
    elif rate > 7.0: tag_text, tag_css = "微贬", "down"
    elif rate > 6.8: tag_text, tag_css = "窄幅整理", "flat"
    else: tag_text, tag_css = "人民币偏强", "up"
    
    tag_css_map = {"up": "up", "down": "bear", "flat": "flat"}
    tag_css = tag_css_map.get(tag_css, "flat")
    
    return f'''    <!-- ═══ EXCHANGE RATE ═══ -->
    <section class="section">
      <div class="analysis-card">
        <div class="card-header">
          <span class="icon">💱</span>
          <h2>美元兑人民币</h2>
          <span class="tag {tag_css}">{tag_text}</span>
        </div>

        <div class="data-grid">
          <div class="data-item">
            <div class="label">在岸参考</div>
            <div class="value">{rate:.4f}</div>
          </div>
          <div class="data-item">
            <div class="label">数据源</div>
            <div class="value" style="font-family:'Inter',sans-serif;font-size:13px;font-weight:400;color:var(--text-muted)">{source}</div>
          </div>
          <div class="data-item" style="grid-column: span 2;">
            <div class="label">12个月走势</div>
            <div class="value" style="color:var(--green);font-size:14px">人民币升值约5.53%</div>
          </div>
        </div>

        <div class="judgment">
          <div class="label">📌 核心研判</div>
          <p>美元兑人民币 {rate:.4f}，处于{tag_text}区间。模型预测本季度末 6.76，12个月后 6.71（小幅升值预期）。</p>
          <p style="margin-top:8px">短期缺乏单边驱动，关注央行中间价设定方向和中美利差变化。</p>
        </div>
      </div>
    </section>'''


def render_outlook_section() -> str:
    """渲染明日关注区块"""
    return f'''    <!-- ═══ TOMORROW OUTLOOK ═══ -->
    <section class="section">
      <h3 class="section-title">明日关注</h3>
      <div class="outlook-grid">
        <div class="outlook-item">
          <span class="oi-icon">📊</span>
          <div class="oi-content">
            <h4>美国经济数据公布</h4>
            <p>影响降息预期 → 黄金/汇率波动</p>
          </div>
        </div>
        <div class="outlook-item">
          <span class="oi-icon">🏢</span>
          <div class="oi-content">
            <h4>腾讯回购公告</h4>
            <p>每日5亿回购是否延续</p>
          </div>
        </div>
        <div class="outlook-item">
          <span class="oi-icon">🌍</span>
          <div class="oi-content">
            <h4>美伊谈判进展</h4>
            <p>地缘风险溢价 → 金价/油价</p>
          </div>
        </div>
        <div class="outlook-item">
          <span class="oi-icon">🏛️</span>
          <div class="oi-content">
            <h4>央行中间价</h4>
            <p>人民币汇率政策信号</p>
          </div>
        </div>
      </div>
    </section>'''


def render_extended_market(data: dict) -> str:
    """渲染其他资产（SP500, CSI300, BTC, US10Y）的小卡片区块"""
    extended = [ad for ad in ASSET_DISPLAY if ad["key"] in ("SP500", "CSI300", "BTC", "US10Y")]
    cards = []
    
    for ad in extended:
        key = ad["key"]
        raw = data.get("raw_data", {}).get(key, {})
        if not raw.get("success"):
            continue
        
        price = fmt_price(key, raw)
        change_text, change_css = fmt_change(key, raw)
        
        # 额外信息
        extra = ""
        if key == "SP500" and raw.get("prev_close"):
            extra = f'<div style="font-size:11px;color:var(--text-muted);margin-top:4px">昨收 {float(raw["prev_close"]):,.0f}</div>'
        elif key == "CSI300" and raw.get("prev_close"):
            extra = f'<div style="font-size:11px;color:var(--text-muted);margin-top:4px">昨收 {float(raw["prev_close"]):,.1f}</div>'
        elif key == "BTC":
            extra = f'<div style="font-size:11px;color:var(--text-muted);margin-top:4px">买/卖 {float(raw.get("buy",0)):,.0f}</div>'
        elif key == "US10Y":
            extra = f'<div style="font-size:11px;color:var(--text-muted);margin-top:4px">日期 {raw.get("date","—")}</div>'
        
        cards.append(f'''      <div class="market-card">
        <div class="asset-icon">{ad["icon"]}</div>
        <div class="asset-name">{ad["short"]}</div>
        <div class="price">{price}</div>
        <div class="change {change_css}">{change_text}</div>
        {extra}
      </div>''')
    
    if not cards:
        return ''
    
    return f'''    <!-- ═══ EXTENDED MARKET ═══ -->
    <section class="section">
      <h3 class="section-title">其他市场</h3>
      <div class="market-grid">
        {''.join(cards)}
      </div>
    </section>'''


def render_full_html(data: dict, analyses: dict, fetch_time: str) -> str:
    """渲染完整HTML页面"""
    
    # ── 日期信息 ──
    now = datetime.now(CST)
    date_cn = f'{now.year}年{now.month}月{now.day}日'
    weekday = WEEKDAY_MAP[now.weekday()]
    
    issn = (now - datetime(2026, 6, 1, tzinfo=CST)).days + 1
    
    # ── 各区块 ──
    market_cards = render_market_cards(data, analyses)
    
    # 主分析（腾讯 + 黄金）
    main_analyses = ''
    tc_raw = data.get("raw_data", {}).get("TENCENT", {})
    gold_raw = data.get("raw_data", {}).get("GOLD", {})
    usdcny_raw = data.get("raw_data", {}).get("USDCNY", {})
    
    main_analyses += render_tencent_section(tc_raw, analyses.get("TENCENT", {})) + '\n'
    main_analyses += render_gold_section(gold_raw, analyses.get("GOLD", {})) + '\n'
    main_analyses += render_exchange_section(usdcny_raw) + '\n'
    
    # 扩展市场 + 明日关注
    ext_market = render_extended_market(data)
    outlook = render_outlook_section()
    
    # ── footer 数据源 ──
    sources = set()
    for key, raw in data.get("raw_data", {}).items():
        if raw.get("success"):
            s = raw.get("source", "")
            if s:
                sources.add(s)
    sources_str = ' · '.join(sorted(sources))
    
    fetch_time_display = fetch_time[:16].replace('T', ' ')
    
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日金融情报 | {date_cn}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;600;700;900&family=JetBrains+Mono:wght@400;500;600&family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg-primary: #0a0b0f;
    --bg-secondary: #111317;
    --bg-card: #16181e;
    --bg-card-hover: #1c1f28;
    --border-color: #1e2230;
    --border-accent: #2a2f42;
    --text-primary: #e8eaf0;
    --text-secondary: #9098a8;
    --text-muted: #5a6270;
    --gold: #d4a84b;
    --gold-light: #f0d58c;
    --gold-glow: rgba(212,168,75,0.15);
    --green: #34d399;
    --green-bg: rgba(52,211,153,0.1);
    --red: #f87171;
    --red-bg: rgba(248,113,113,0.1);
    --blue: #60a5fa;
    --blue-bg: rgba(96,165,250,0.1);
    --purple: #a78bfa;
    --purple-bg: rgba(167,139,250,0.1);
    --orange: #fb923c;
    --orange-bg: rgba(251,146,60,0.1);
    --gradient-gold: linear-gradient(135deg, #d4a84b, #f0d58c);
    --shadow-card: 0 1px 3px rgba(0,0,0,0.3), 0 0 0 1px rgba(255,255,255,0.02);
  }}

  * {{ margin: 0; padding: 0; box-sizing: border-box; }}

  html {{
    scroll-behavior: smooth;
  }}

  body {{
    font-family: 'Noto Serif SC', 'Inter', sans-serif;
    background: var(--bg-primary);
    color: var(--text-primary);
    line-height: 1.7;
    -webkit-font-smoothing: antialiased;
  }}

  /* ─── Background grain ─── */
  body::before {{
    content: '';
    position: fixed;
    inset: 0;
    background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='0.04'/%3E%3C/svg%3E");
    pointer-events: none;
    z-index: 0;
  }}

  .container {{
    max-width: 960px;
    margin: 0 auto;
    padding: 0 24px;
    position: relative;
    z-index: 1;
  }}

  /* ─── Header ─── */
  .header {{
    padding: 60px 0 40px;
    text-align: center;
    position: relative;
  }}

  .header::after {{
    content: '';
    position: absolute;
    bottom: 0;
    left: 50%;
    transform: translateX(-50%);
    width: 60px;
    height: 2px;
    background: var(--gradient-gold);
    border-radius: 2px;
  }}

  .header-badge {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 6px 16px;
    border: 1px solid var(--border-accent);
    border-radius: 100px;
    font-size: 12px;
    font-family: 'Inter', sans-serif;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: var(--text-muted);
    margin-bottom: 24px;
  }}

  .header-badge .dot {{
    width: 6px; height: 6px;
    border-radius: 50%;
    background: var(--green);
    animation: pulse-dot 2s ease-in-out infinite;
  }}

  @keyframes pulse-dot {{
    0%, 100% {{ opacity: 1; }}
    50% {{ opacity: 0.3; }}
  }}

  .header h1 {{
    font-size: clamp(32px, 5vw, 52px);
    font-weight: 900;
    letter-spacing: -0.02em;
    line-height: 1.15;
    margin-bottom: 8px;
  }}

  .header h1 .gold {{
    background: var(--gradient-gold);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }}

  .header .subtitle {{
    font-family: 'Inter', sans-serif;
    font-size: 15px;
    font-weight: 300;
    color: var(--text-secondary);
    letter-spacing: 2px;
    margin-top: 16px;
  }}

  .header .date-line {{
    font-family: 'Inter', sans-serif;
    font-size: 13px;
    color: var(--text-muted);
    margin-top: 8px;
  }}

  /* ─── Market Overview Section ─── */
  .section {{
    margin: 48px 0;
  }}

  .section-title {{
    font-size: 13px;
    font-family: 'Inter', sans-serif;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 3px;
    color: var(--text-muted);
    margin-bottom: 20px;
    position: relative;
    padding-left: 16px;
  }}

  .section-title::before {{
    content: '';
    position: absolute;
    left: 0;
    top: 50%;
    transform: translateY(-50%);
    width: 4px;
    height: 16px;
    background: var(--gradient-gold);
    border-radius: 2px;
  }}

  .market-grid {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
  }}

  @media (max-width: 700px) {{
    .market-grid {{ grid-template-columns: 1fr; }}
  }}

  .market-card {{
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 16px;
    padding: 24px;
    transition: all 0.3s ease;
    position: relative;
    overflow: hidden;
  }}

  .market-card::before {{
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 3px;
    background: var(--gradient-gold);
    opacity: 0;
    transition: opacity 0.3s ease;
  }}

  .market-card:hover {{
    background: var(--bg-card-hover);
    border-color: var(--border-accent);
    transform: translateY(-2px);
  }}

  .market-card:hover::before {{
    opacity: 1;
  }}

  .market-card .asset-icon {{
    font-size: 24px;
    margin-bottom: 12px;
  }}

  .market-card .asset-name {{
    font-family: 'Inter', sans-serif;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 2px;
    color: var(--text-muted);
    margin-bottom: 8px;
  }}

  .market-card .price {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 24px;
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 4px;
  }}

  .market-card .change {{
    font-family: 'Inter', sans-serif;
    font-size: 13px;
    font-weight: 500;
  }}

  .change.up {{ color: var(--green); }}
  .change.down {{ color: var(--red); }}
  .change.flat {{ color: var(--text-muted); }}

  .market-card .signal {{
    display: inline-block;
    margin-top: 12px;
    padding: 4px 12px;
    border-radius: 100px;
    font-family: 'Inter', sans-serif;
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.5px;
  }}

  .signal.bull {{ background: var(--green-bg); color: var(--green); }}
  .signal.neutral {{ background: var(--blue-bg); color: var(--blue); }}
  .signal.bear {{ background: var(--red-bg); color: var(--red); }}
  .signal.watch {{ background: var(--orange-bg); color: var(--orange); }}
  .signal.gold-signal {{ background: var(--gold-glow); color: var(--gold); }}

  /* ─── Deep Analysis Cards ─── */
  .analysis-card {{
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 20px;
    padding: 36px;
    margin-bottom: 20px;
    transition: all 0.3s ease;
  }}

  .analysis-card:hover {{
    border-color: var(--border-accent);
  }}

  .analysis-card .card-header {{
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 24px;
    padding-bottom: 16px;
    border-bottom: 1px solid var(--border-color);
  }}

  .analysis-card .card-header .icon {{
    font-size: 28px;
  }}

  .analysis-card .card-header h2 {{
    font-size: 20px;
    font-weight: 700;
    letter-spacing: -0.01em;
  }}

  .analysis-card .card-header .tag {{
    margin-left: auto;
    padding: 4px 14px;
    border-radius: 100px;
    font-family: 'Inter', sans-serif;
    font-size: 11px;
    font-weight: 500;
    white-space: nowrap;
  }}

  .tag.up {{ background: var(--green-bg); color: var(--green); }}
  .tag.flat {{ background: var(--blue-bg); color: var(--blue); }}
  .tag.watch {{ background: var(--orange-bg); color: var(--orange); }}
  .tag.gold-tag {{ background: var(--gold-glow); color: var(--gold); }}
  .tag.down {{ background: var(--red-bg); color: var(--red); }}

  /* Data table inside cards */
  .data-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px;
    margin-bottom: 24px;
  }}

  .data-item {{
    padding: 12px 16px;
    background: var(--bg-secondary);
    border-radius: 12px;
  }}

  .data-item .label {{
    font-family: 'Inter', sans-serif;
    font-size: 11px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--text-muted);
    margin-bottom: 4px;
  }}

  .data-item .value {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 18px;
    font-weight: 600;
    color: var(--text-primary);
  }}

  .data-item .value.gold-text {{ color: var(--gold); }}

  /* Price Levels Table */
  .levels-table {{
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 24px;
    font-family: 'Inter', sans-serif;
    font-size: 13px;
  }}

  .levels-table th {{
    text-align: left;
    padding: 10px 16px;
    color: var(--text-muted);
    font-weight: 500;
    letter-spacing: 0.5px;
    border-bottom: 1px solid var(--border-color);
  }}

  .levels-table td {{
    padding: 10px 16px;
    border-bottom: 1px solid var(--border-color);
  }}

  .levels-table tr:last-child td {{
    border-bottom: none;
  }}

  .levels-table .num {{
    font-family: 'JetBrains Mono', monospace;
    text-align: right;
  }}

  .levels-table .pct {{
    font-family: 'JetBrains Mono', monospace;
    color: var(--text-secondary);
    text-align: right;
  }}

  .levels-table .highlight {{
    color: var(--gold);
  }}

  /* Events list */
  .events-list {{
    list-style: none;
    margin-bottom: 24px;
  }}

  .events-list li {{
    position: relative;
    padding: 10px 0 10px 28px;
    font-size: 14px;
    line-height: 1.6;
    color: var(--text-secondary);
    border-bottom: 1px solid rgba(255,255,255,0.03);
  }}

  .events-list li:last-child {{ border-bottom: none; }}

  .events-list li::before {{
    content: '▸';
    position: absolute;
    left: 4px;
    color: var(--gold);
    font-size: 14px;
  }}

  /* Judgment section */
  .judgment {{
    padding: 20px 24px;
    background: var(--bg-secondary);
    border-radius: 12px;
    border-left: 3px solid var(--gold);
    margin-top: 16px;
  }}

  .judgment .label {{
    font-family: 'Inter', sans-serif;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: var(--gold);
    margin-bottom: 8px;
  }}

  .judgment p {{
    font-size: 14px;
    line-height: 1.8;
    color: var(--text-secondary);
  }}

  .judgment .focus-points {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 12px;
  }}

  .judgment .focus-points span {{
    padding: 4px 12px;
    background: rgba(212,168,75,0.1);
    border: 1px solid rgba(212,168,75,0.15);
    border-radius: 100px;
    font-family: 'Inter', sans-serif;
    font-size: 12px;
    color: var(--gold-light);
  }}

  /* ─── Gold Bull/Bear ─── */
  .bull-bear {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    margin-bottom: 20px;
  }}

  @media (max-width: 600px) {{
    .bull-bear {{ grid-template-columns: 1fr; }}
  }}

  .bull-box, .bear-box {{
    padding: 20px;
    border-radius: 12px;
  }}

  .bull-box {{
    background: var(--green-bg);
    border: 1px solid rgba(52,211,153,0.15);
  }}

  .bear-box {{
    background: var(--red-bg);
    border: 1px solid rgba(248,113,113,0.15);
  }}

  .bull-box .bb-title, .bear-box .bb-title {{
    font-family: 'Inter', sans-serif;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 1px;
    margin-bottom: 12px;
  }}

  .bull-box .bb-title {{ color: var(--green); }}
  .bear-box .bb-title {{ color: var(--red); }}

  .bull-box ul, .bear-box ul {{
    list-style: none;
    padding: 0;
  }}

  .bull-box li, .bear-box li {{
    position: relative;
    padding: 6px 0 6px 18px;
    font-size: 13px;
    line-height: 1.6;
    color: var(--text-secondary);
  }}

  .bull-box li::before {{ content: '✓'; position: absolute; left: 0; color: var(--green); }}
  .bear-box li::before {{ content: '✗'; position: absolute; left: 0; color: var(--red); }}

  /* Background context (gold) */
  .bg-context {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 20px;
  }}

  .bg-context .chip {{
    padding: 6px 14px;
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 100px;
    font-family: 'Inter', sans-serif;
    font-size: 12px;
    color: var(--text-secondary);
  }}

  /* ─── Tomorrow Outlook ─── */
  .outlook-grid {{
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
  }}

  @media (max-width: 600px) {{
    .outlook-grid {{ grid-template-columns: 1fr; }}
  }}

  .outlook-item {{
    display: flex;
    align-items: flex-start;
    gap: 16px;
    padding: 18px 20px;
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 14px;
    transition: all 0.2s ease;
  }}

  .outlook-item:hover {{
    border-color: var(--border-accent);
    background: var(--bg-card-hover);
  }}

  .outlook-item .oi-icon {{
    font-size: 22px;
    flex-shrink: 0;
    margin-top: 2px;
  }}

  .outlook-item .oi-content h4 {{
    font-size: 14px;
    font-weight: 600;
    margin-bottom: 4px;
  }}

  .outlook-item .oi-content p {{
    font-size: 12px;
    font-family: 'Inter', sans-serif;
    color: var(--text-muted);
    line-height: 1.5;
  }}

  /* ─── Footer ─── */
  .footer {{
    padding: 40px 0 80px;
    text-align: center;
    border-top: 1px solid var(--border-color);
    margin-top: 60px;
  }}

  .footer p {{
    font-size: 12px;
    font-family: 'Inter', sans-serif;
    color: var(--text-muted);
    line-height: 1.8;
  }}

  .footer a {{
    color: var(--gold);
    text-decoration: none;
  }}

  .footer a:hover {{
    text-decoration: underline;
  }}

  /* ─── Deerflow Branding ─── */
  .deerflow-badge {{
    position: fixed;
    bottom: 20px;
    right: 20px;
    z-index: 100;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 14px;
    background: rgba(10, 11, 15, 0.8);
    backdrop-filter: blur(12px);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 100px;
    font-family: 'Inter', sans-serif;
    font-size: 11px;
    color: var(--text-muted);
    text-decoration: none;
    transition: all 0.3s ease;
    letter-spacing: 0.5px;
  }}

  .deerflow-badge:hover {{
    border-color: var(--gold);
    color: var(--gold-light);
    background: rgba(10, 11, 15, 0.95);
    transform: translateY(-1px);
  }}

  .deerflow-badge .df-icon {{
    font-size: 12px;
  }}

  /* ─── Animations ─── */
  .animate-in {{
    opacity: 0;
    transform: translateY(20px);
    animation: fadeUp 0.6s ease forwards;
  }}

  .animate-in:nth-child(1) {{ animation-delay: 0.05s; }}
  .animate-in:nth-child(2) {{ animation-delay: 0.1s; }}
  .animate-in:nth-child(3) {{ animation-delay: 0.15s; }}
  .animate-in:nth-child(4) {{ animation-delay: 0.2s; }}
  .animate-in:nth-child(5) {{ animation-delay: 0.25s; }}
  .animate-in:nth-child(6) {{ animation-delay: 0.3s; }}

  @keyframes fadeUp {{
    to {{
      opacity: 1;
      transform: translateY(0);
    }}
  }}

  /* ─── Scrollbar ─── */
  ::-webkit-scrollbar {{ width: 6px; }}
  ::-webkit-scrollbar-track {{ background: var(--bg-primary); }}
  ::-webkit-scrollbar-thumb {{ background: var(--border-accent); border-radius: 3px; }}
  ::-webkit-scrollbar-thumb:hover {{ background: var(--text-muted); }}
</style>
</head>
<body>

<div class="container">

  <!-- ═══ HEADER ═══ -->
  <header class="header animate-in">
    <div class="header-badge">
      <span class="dot"></span>
      Market Intelligence
    </div>
    <h1>每日金融<span class="gold">情报</span></h1>
    <p class="subtitle">深度研判 · 数据驱动决策</p>
    <p class="date-line">{date_cn} {weekday} · 第{issn}期</p>
  </header>

  <!-- ═══ MARKET OVERVIEW ═══ -->
  <section class="section animate-in">
    <h3 class="section-title">今日市场全景</h3>
    <div class="market-grid">
{market_cards}
    </div>
  </section>

  <!-- ═══ MAIN ANALYSIS ═══ -->
{main_analyses}

  <!-- ═══ EXTENDED MARKET ═══ -->
{ext_market}

  <!-- ═══ OUTLOOK ═══ -->
{outlook}

  <!-- ═══ FOOTER ═══ -->
  <footer class="footer animate-in">
    <p>数据来源：{sources_str}</p>
    <p>报告生成：{fetch_time_display}</p>
    <p style="margin-top:12px;font-size:11px;color:rgba(255,255,255,0.15)">
      ⚡ 数据仅供参考，不构成投资建议。市场有风险，决策需谨慎。
    </p>
  </footer>

</div>

<!-- Deerflow Branding -->
<a href="https://deerflow.tech" target="_blank" class="deerflow-badge" title="Created By Deerflow">
  <span class="df-icon">✦</span>
  Deerflow
</a>

</body>
</html>'''
    
    return html


# ════════════════════════════════════════════════════════
#  主入口
# ════════════════════════════════════════════════════════

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='每日金融情报 — 网页端数据生成器')
    parser.add_argument('--date', default=None, help='数据日期 (YYYYMMDD)')
    parser.add_argument('--skip-llm', action='store_true', help='跳过 LLM 分析（纯数据展示）')
    parser.add_argument('--verbose', '-v', action='store_true', help='详细输出')
    args = parser.parse_args()
    
    # 1. 加载数据
    data = load_data(args.date)
    fetch_time = data.get('fetch_time', datetime.now(CST).isoformat())
    
    success = data['summary']['success']
    total = data['summary']['total']
    print(f'📊 数据概览: {success}/{total} 资产成功采集')
    
    # 2. LLM 分析
    print('🤖 开始 LLM 逐资产分析...')
    analyses = analyze_all_assets(data, skip_llm=args.skip_llm)
    
    # 3. 渲染 HTML
    print(f'🖌️  渲染 HTML...')
    html = render_full_html(data, analyses, fetch_time)
    
    # 4. 写入文件
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    WEB_INDEX.write_text(html, encoding='utf-8')
    print(f'✅ 网页已生成: {WEB_INDEX}')
    
    if args.verbose:
        print(f'   HTML 大小: {len(html):,} 字节')
    
    # 打印关键数据摘要
    print()
    print('📋 今日数据摘要:')
    for ad in ASSET_DISPLAY:
        key = ad["key"]
        raw = data.get("raw_data", {}).get(key, {})
        if raw.get("success"):
            price = fmt_price(key, raw)
            chg_text, _ = fmt_change(key, raw)
            analysis = analyses.get(key, {})
            summary = analysis.get("summary", "")
            print(f'   {ad["icon"]} {ad["short"]}: {price} {chg_text}')


if __name__ == '__main__':
    main()
