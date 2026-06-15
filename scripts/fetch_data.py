#!/usr/bin/env python3
"""
每日金融情报官 — 数据采集脚本
采集美元兑人民币汇率、腾讯控股(00700.HK)股价、现货黄金价格
输出结构化 JSON 到 reports/ 目录

用法:
    python scripts/fetch_data.py                     # 默认采集并保存
    python scripts/fetch_data.py -v                  # 详细输出
    python scripts/fetch_data.py --output-dir ./自定义路径
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
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)      # daily-finance-monitor/
DEFAULT_OUTPUT_DIR = os.path.join(PROJECT_DIR, 'reports')

# 数据源端点
ER_API_USD = 'https://open.er-api.com/v6/latest/USD'   # 美元汇率
SINA_HK_URL = 'https://hq.sinajs.cn/list=rt_hk00700'   # 腾讯港股

REQ_HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                             'AppleWebKit/537.36 (KHTML, like Gecko)'}


# ── 采集函数 ────────────────────────────────────────

def fetch_exchange_rate():
    """采集美元兑人民币汇率 (开放 API, 无需 Key)"""
    try:
        resp = requests.get(ER_API_USD, timeout=10, headers=REQ_HEADERS)
        resp.raise_for_status()
        data = resp.json()
        if data.get('result') == 'success':
            cny_rate = data['rates'].get('CNY')
            update_time = data.get('time_last_update_utc', '')
            return {
                'success': True,
                'rate': cny_rate,
                'update_time': update_time,
                'source': 'ExchangeRate-API (open.er-api.com)',
                'fetched_at': datetime.now(CST).isoformat()
            }
        return {'success': False, 'error': f'API 返回异常: {data.get("result")}'}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def fetch_tencent_stock():
    """采集腾讯控股 (00700.HK) 股价 (新浪财经免费接口)"""
    sina_headers = {
        'Referer': 'https://finance.sina.com.cn',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                      'AppleWebKit/537.36',
    }
    try:
        resp = requests.get(SINA_HK_URL, timeout=10, headers=sina_headers)
        resp.encoding = 'gb2312'
        text = resp.text.strip()

        if not text or '=' not in text:
            return {'success': False, 'error': '新浪接口返回空数据'}

        # 解析: var hq_str_rt_hk00700="字段1,字段2,..."
        content = text.split('="')[1].rstrip('";')
        fields = content.split(',')

        # 港股字段索引 (已验证):
        #   0=英文名, 1=中文名, 2=开盘价, 3=昨收价, 4=最高价,
        #   5=最低价, 6=现价, 7=涨跌额, 8=涨跌幅%,
        #   9=买入价, 10=卖出价, 11=成交额, 12=成交量,
        #   13=市盈率, 17=日期, 18=时间
        name_en = fields[0].strip() if len(fields) > 0 else ''
        name_cn = fields[1].strip() if len(fields) > 1 else ''
        return {
            'success': True,
            'name': f'{name_cn}({name_en})',
            'current_price': _to_float(fields[6]),
            'prev_close': _to_float(fields[3]),
            'open_price': _to_float(fields[2]),
            'high': _to_float(fields[4]),
            'low': _to_float(fields[5]),
            'change': _to_float(fields[7]),
            'change_percent': fields[8].strip() + '%' if len(fields) > 8 else '',
            'volume': fields[12].strip() if len(fields) > 12 else '',
            'amount': fields[11].strip() if len(fields) > 11 else '',
            'date': fields[17].strip() if len(fields) > 17 else '',
            'time': fields[18].strip() if len(fields) > 18 else '',
            'source': '新浪财经',
            'fetched_at': datetime.now(CST).isoformat()
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


def _to_float(val):
    """安全转换为 float"""
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


GOLD_API_URL = 'https://api.gold-api.com/price/XAU'

def fetch_gold_price():
    """采集现货黄金价格 XAU/USD (开放 API, 无需 Key)"""
    try:
        resp = requests.get(GOLD_API_URL, timeout=10,
                            headers={'User-Agent': 'Mozilla/5.0'})
        resp.raise_for_status()
        data = resp.json()
        price = data.get('price')
        if price is not None:
            return {
                'success': True,
                'price_usd': float(price),
                'update_time': data.get('updatedAt', ''),
                'source': 'gold-api.com',
                'fetched_at': datetime.now(CST).isoformat()
            }
        return {'success': False, 'error': '响应中缺少 price 字段'}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ── 主入口 ────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='每日金融情报官 — 数据采集')
    parser.add_argument('--output-dir', default=DEFAULT_OUTPUT_DIR,
                        help='输出目录 (默认: reports/)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='显示详细信息')
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    if args.verbose:
        print('🔍 正在采集三件套数据...\n')

    # 并行采集三类数据
    exchange_rate = fetch_exchange_rate()
    tencent = fetch_tencent_stock()
    gold = fetch_gold_price()

    # 汇总
    result = {
        'fetch_time': datetime.now(CST).isoformat(),
        'date': datetime.now(CST).strftime('%Y-%m-%d'),
        'exchange_rate': exchange_rate,
        'tencent': tencent,
        'gold': gold,
        'summary': {
            'total': 3,
            'success': sum(1 for x in [exchange_rate, tencent, gold]
                           if x.get('success'))
        }
    }

    # 写入 JSON
    filename = f'daily-data-{datetime.now(CST).strftime("%Y%m%d")}.json'
    output_path = os.path.join(args.output_dir, filename)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    if args.verbose:
        print(f'✅ 采集完成: {result["summary"]["success"]}/3 成功')
        print(f'📁 保存至: {output_path}')
        if exchange_rate.get('success'):
            print(f'   💱 USD/CNY: {exchange_rate["rate"]}')
        else:
            print(f'   ❌ 汇率: {exchange_rate.get("error")}')
        if tencent.get('success'):
            print(f'   📈 腾讯: {tencent["current_price"]} 港元 '
                  f'({tencent.get("change_percent", "")})')
        else:
            print(f'   ❌ 腾讯: {tencent.get("error")}')
        if gold.get('success'):
            print(f'   🥇 黄金: ${gold["price_usd"]:,.2f}/盎司')
        else:
            print(f'   ❌ 黄金: {gold.get("error")}')

    # 全部失败 → 非零退出码
    if result['summary']['success'] == 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
