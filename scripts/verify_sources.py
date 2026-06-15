#!/usr/bin/env python3
"""Verify the three broken data sources are now working."""
import requests as r

h = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com/'}

# 1. SP500
print('=== SP500 (东方财富) ===')
resp = r.get('https://push2.eastmoney.com/api/qt/stock/get?secid=100.SPX&fields=f43,f44,f45,f46,f47,f48,f50,f57,f58,f60,f170,f171,f168,f169', timeout=10, headers=h)
d = resp.json().get('data', {})
if d and d.get('f43'):
    cur = d['f43'] / 100
    prev = d['f60'] / 100
    high = (d['f44'] / 100) if d.get('f44') else None
    low = (d['f45'] / 100) if d.get('f45') else None
    chg_pct = (cur - prev) / prev * 100
    print(f'  Current: {cur:.2f}, PrevClose: {prev:.2f}')
    print(f'  Change: {cur-prev:.2f} ({chg_pct:.2f}%)')
else:
    print('  FAILED:', resp.text[:200])

# 2. BTC
print('\n=== BTC (blockchain.info) ===')
resp = r.get('https://blockchain.info/ticker', timeout=10)
if resp.status_code == 200:
    btc = resp.json().get('USD', {})
    print(f'  Price: ${btc.get("15m", 0):.2f}')
    print(f'  Buy: ${btc.get("buy", 0):.2f}, Sell: ${btc.get("sell", 0):.2f}')
else:
    print('  FAILED')

# 3. US10Y
print('\n=== US10Y (Treasury.gov) ===')
resp = r.get(
    'https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/all/202606'
    '?type=daily_treasury_yield_curve&field_tdr_date_value_month=202606&_format=csv',
    timeout=15
)
if resp.status_code == 200:
    lines = resp.text.strip().split('\n')
    headers = [h.strip().strip('"') for h in lines[0].split(',')]
    idx_10yr = headers.index('10 Yr')
    last_fields = [f.strip().strip('"') for f in lines[-1].split(',')]
    print(f'  Date: {last_fields[0]}, 10 Yr Yield: {last_fields[idx_10yr]}%')
else:
    print(f'  Status: {resp.status_code}')
    # Fallback: try to scrape
    print('  Trying Investing.com...')
    resp2 = r.get('https://cn.investing.com/rates-bonds/u.s.-10-year-bond-yield', timeout=10,
                  headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
    print(f'  Status: {resp2.status_code}')
