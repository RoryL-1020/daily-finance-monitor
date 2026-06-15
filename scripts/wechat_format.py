"""微信推送专用排版 — 简洁、清晰、移动端友好"""

def build_wechat_content(data):
    from datetime import datetime, timezone, timedelta
    CST = timezone(timedelta(hours=8))
    now = datetime.now(CST)
    weekday_map = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    weekday = weekday_map[now.weekday()]

    er = data.get('exchange_rate', {})
    tc = data.get('tencent', {})
    gl = data.get('gold', {})

    from push_report import analyze_exchange_rate, analyze_tencent, analyze_gold
    er_a = analyze_exchange_rate(er)
    tc_a = analyze_tencent(tc)
    gl_a = analyze_gold(gl)

    lines = []
    date_str = f'{now.month}月{now.day}日 {weekday}'

    # ═══ 头部 ═══
    lines.append(f'📊 **每日金融情报 | {date_str}**')
    lines.append('')
    lines.append('━━━ 📋 市场速览 ━━━')
    lines.append('')

    if tc.get('success'):
        lines.append(f'📈 腾讯控股  {tc["current_price"]} 港元  {tc_a["change_pct"]}  {tc_a["direction"]}')

    if gl.get('success'):
        lines.append(f'🥇 XAU/USD  ${gl_a["price"]:,.0f}  {gl_a["zone"]}')

    if er.get('success'):
        lines.append(f'💱 USD/CNY  {er["rate"]}  {er_a["judgment"]}')

    lines.append('')

    # ═══ 腾讯深度 ═══
    lines.append('━━━ 📈 腾讯深度 ━━━')
    lines.append('')
    lines.append(f'{tc_a["volatility"]} · 振幅 {tc_a["amplitude"]}')
    lines.append('')
    lines.append(f'📍 关键价位：')
    lines.append(f'  52周高点 {tc_a["year_high"]}（距现价 {tc_a["distance_from_high"]}）')
    lines.append(f'  52周低点 {tc_a["year_low"]}（距现价 {tc_a["distance_from_low"]}）')
    lines.append(f'  高盛目标 700（+{(700/tc["current_price"]-1)*100:.0f}%）')
    lines.append('')
    lines.append(f'🔥 近期催化：')
    for ev in tc_a['recent_events']:
        lines.append(f'  ▸ {ev}')
    lines.append('')
    lines.append(f'💡 核心研判：{tc_a["detail"]}')
    lines.append('')

    # ═══ 黄金深度 ═══
    lines.append('━━━ 🥇 黄金深度 ━━━')
    lines.append('')
    lines.append(f'${gl_a["price"]:,.2f}  {gl_a["zone"]}')
    lines.append('')
    lines.append(f'🆙 看多：{gl_a["bull_case"][0]}')
    lines.append(f'🔻 看空：{gl_a["bear_case"][0]}')
    lines.append('')
    lines.append(f'💡 核心研判：金价从$5,600+回调至$4,000企稳，属大涨后健康调整。中长期看多逻辑未破坏。')
    lines.append('')

    # ═══ 汇率 ═══
    lines.append('━━━ 💱 汇率 ━━━')
    lines.append('')
    lines.append(f'USD/CNY {er["rate"]}  {er_a["judgment"]}')
    lines.append(f'{er_a["yoy_change"]}')
    lines.append(f'{er_a["forecast"]}')
    lines.append('')

    # ═══ 明日关注 ═══
    lines.append('━━━ 🔮 明日关注 ━━━')
    lines.append('')
    lines.append('📊 美国经济数据 → 降息预期/黄金')
    lines.append('🏢 腾讯回购公告 → 是否延续5亿/日')
    lines.append('🌍 美伊谈判 → 地缘风险溢价')
    lines.append('🏛️ 央行中间价 → 汇率政策信号')
    lines.append('')

    # ═══ 底部 ═══
    lines.append('━━━━━━━━━━━━━━━━━')
    lines.append(f'📱 {now.strftime("%H:%M")}更新 | ⚡不构成投资建议')

    return '\n'.join(lines)
