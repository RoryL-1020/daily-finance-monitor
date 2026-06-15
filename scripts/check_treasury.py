#!/usr/bin/env python3
"""Check Treasury data availability more thoroughly."""
import requests as r

h = {'User-Agent': 'Mozilla/5.0'}

# Check full Treasury dataset dates
resp = r.get(
    'https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/all/202606'
    '?type=daily_treasury_yield_curve&field_tdr_date_value_month=202606&_format=csv',
    timeout=15
)
if resp.status_code == 200:
    lines = resp.text.strip().split('\n')[1:]  # skip header
    print(f'Total data rows: {len(lines)}')
    if lines:
        print(f'First date: {lines[0].split(",")[0]}')
        print(f'Last date: {lines[-1].split(",")[0]}')
        print(f'All dates: {[l.split(",")[0] for l in lines]}')

# Check previous months
for m in [5, 4, 3]:
    url = f'https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/all/2026{m:02d}?type=daily_treasury_yield_curve&field_tdr_date_value_month=2026{m:02d}&_format=csv'
    resp = r.get(url, timeout=15)
    if resp.status_code == 200:
        data_lines = resp.text.strip().split('\n')[1:]
        if data_lines:
            dates = [l.split(",")[0].strip('"') for l in data_lines]
            print(f'Month {m:02d}: {len(data_lines)} days, last: {dates[-1]}, first: {dates[0]}')
            if '06/12/2026' in dates:
                print('  *** HAS June 12 data! ***')
    else:
        print(f'Month {m:02d}: HTTP {resp.status_code}')

# Try FRED API (St. Louis Fed) - maybe this is updated daily
print('\n=== FRED API (DGS10) ===')
# FRED has a public API that often works without key for simple queries
try:
    resp = r.get('https://fred.stlouisfed.org/graph/fredgraph.csv?bgcolor=%23e1e9f0&chart_type=line&drp=0&fo=open%20sans&graph_bgcolor=%23ffffff&height=450&mode=fred&recession_bars=on&txtcolor=%23444444&ts=12&tts=12&width=1168&nt=0&thu=0&trc=0&show_legend=yes&show_axis_titles=yes&show_tooltip=yes&id=DGS10&scale=left&cosd=2026-06-01&coed=2026-06-12&line_color=%234572a7&link_values=false&line_style=solid&mark_type=none&mw=3&lw=2&ost=-99999&oet=99999&mma=0&fml=a&fq=Daily&fam=avg&fgst=lin&fgsnd=2020-02-01&line_index=1&transformation=lin&vintage_date=2026-06-12&revision_date=2026-06-12&nd=1962-01-02', timeout=15)
    if resp.status_code == 200:
        print(f'FRED CSV: {resp.text[:200]}')
except Exception as e:
    print(f'FRED error: {e}')
