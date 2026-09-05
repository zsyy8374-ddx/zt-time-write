"""
涨停时间写入通达信外部数据 ID=114
数据源: 同花顺问财 → extern_user.txt
运行: python3 zt_time_write.py [YYYYMMDD]
      不传日期默认最新交易日
"""

import sys
import os
import struct
from datetime import datetime, timezone, timedelta

# 确保能找到 ths_config
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.normpath(os.path.join(SCRIPT_DIR, '..'))
WENCAI_DIR = os.path.join(WORKSPACE, '.openclaw', 'workspace')
if os.path.isdir(WENCAI_DIR):
    sys.path.insert(0, WENCAI_DIR)
sys.path.insert(0, WORKSPACE)
sys.path.insert(0, os.path.join(WORKSPACE, '.openclaw', 'workspace'))

from ths_config import get_ths_ops
from thsdk import THS

# === Config ===
EXTERN_FILE = os.path.expanduser("~/tdx/T0002/signals/extern_user.txt")
CFG_FILE = os.path.expanduser("~/tdx/T0002/signals/datacfg.dat")
TZ_CN = timezone(timedelta(hours=8))
DATA_ID = 114
DATA_NAME = "涨停时间"

def code_to_market_prefix(code):
    code_6 = code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
    if code_6.startswith('6') or code_6.startswith('688'):
        return '1', code_6
    elif code_6.startswith('8') or code_6.startswith('4') or code_6.startswith('920'):
        return '2', code_6
    else:
        return '0', code_6

def get_trade_date():
    """获取最新交易日"""
    today = datetime.now(TZ_CN)
    wd = today.weekday()
    # 周末取上周五
    if wd >= 5:
        offset = wd - 4  # Sat→-1, Sun→-2
        today = today + timedelta(days=-offset)
    return today.strftime('%Y%m%d')

def ensure_datacfg():
    """确保 datacfg.dat 中有 ID=114 注册"""
    if not os.path.exists(CFG_FILE):
        print(f"[WARN] {CFG_FILE} not found, skip datacfg check")
        return
    with open(CFG_FILE, 'rb') as f:
        data = bytearray(f.read())
    for i in range(len(data) // 120):
        offset = i * 120
        id_val = struct.unpack('<I', data[offset:offset+4])[0]
        if id_val == DATA_ID:
            print(f"  datacfg: ID={DATA_ID} already registered")
            return
    # 没找到，插入
    insert_offset = None
    for i in range(len(data) // 120):
        offset = i * 120
        id_val = struct.unpack('<I', data[offset:offset+4])[0]
        if id_val == 113:
            insert_offset = (i + 1) * 120
            break
    if insert_offset is None:
        print(f"[ERROR] Cannot find insertion point in datacfg.dat")
        return
    rec = bytearray(120)
    struct.pack_into('<I', rec, 0, DATA_ID)
    struct.pack_into('<I', rec, 4, 0)  # type=0
    name_gbk = DATA_NAME.encode('gbk')
    rec[8:8+len(name_gbk)] = name_gbk
    struct.pack_into('<I', rec, 60, DATA_ID + 1)  # dir_ref
    new_data = bytearray(data[:insert_offset]) + rec + bytearray(data[insert_offset:])
    with open(CFG_FILE, 'wb') as f:
        f.write(new_data)
    print(f"  datacfg: registered ID={DATA_ID} '{DATA_NAME}'")

def main():
    # 日期
    if len(sys.argv) > 1:
        query_date = sys.argv[1]
    else:
        query_date = get_trade_date()
    print(f"Query date: {query_date}")

    # 1. 查询问财
    ops = get_ths_ops()
    if not ops:
        print("[ERROR] thsdk login config not found")
        sys.exit(1)
    with THS(ops) as ths:
        resp = ths.wencai_nlp(
            f"最终涨停时间[{query_date}], 涨停, 非ST, 非停牌, 代码[{query_date}], 股票简称"
        )
    if not resp.success:
        print(f"[ERROR] wencai query failed: {resp.error}")
        sys.exit(1)
    data = resp.data
    print(f"  Limit-up stocks: {len(data)}")

    # 2. 自动识别返回数据中的实际日期
    actual_date = None
    for k in data[0].keys():
        if k.startswith('最终涨停时间['):
            actual_date = k[len('最终涨停时间['):-1]
            break
    if not actual_date:
        print(f"[ERROR] 未找到最终涨停时间字段，可用列: {list(data[0].keys())}")
        sys.exit(1)
    print(f"  Actual data date: {actual_date}")

    # 3. 生成外部数据
    new_bytes = b''
    for row in data:
        code_full = row['股票代码']
        ts_ms = int(row[f'最终涨停时间[{actual_date}]'])
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=TZ_CN)
        time_6d = f"{dt.hour:02d}{dt.minute:02d}{dt.second:02d}"
        mkt, c6 = code_to_market_prefix(code_full)
        line = f"{mkt}|{c6}|{DATA_ID}|{time_6d}|0.000\r\n"
        new_bytes += line.encode('utf-8')

    # 4. 写入 extern_user.txt
    if not os.path.exists(EXTERN_FILE):
        print(f"[ERROR] {EXTERN_FILE} not found")
        sys.exit(1)
    with open(EXTERN_FILE, 'rb') as f:
        raw = f.read()
    old_lines = raw.split(b'\r\n')
    old_lines = [l for l in old_lines if l and f'|{DATA_ID}|'.encode() not in l]
    clean_old = b'\r\n'.join(old_lines) + b'\r\n' if old_lines else b''
    result = clean_old + new_bytes
    with open(EXTERN_FILE, 'wb') as f:
        f.write(result)
    print(f"  Written to {EXTERN_FILE}")
    print(f"  Entries: {result.count(f'|{DATA_ID}|'.encode())}")

    # 5. 确保 datacfg 注册
    ensure_datacfg()
    print("Done. Restart 通达信 to refresh.")

if __name__ == '__main__':
    main()
