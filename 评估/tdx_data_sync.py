#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tdx_data_sync.py —— 自动同步通达信本地 .day 文件最新K线

机制:
  1. 检查本地 .day 文件最新日期
  2. 对比今日，若缺失/非今天，从通达信服务器自动拉取
  3. 将缺失日K线追加到本地 .day 文件
  4. 支持全市场批量同步

用法:
  python tdx_data_sync.py                # 全市场同步
  python tdx_data_sync.py --check        # 仅检查数据新鲜度
  python tdx_data_sync.py --code 001206  # 单只同步
  python tdx_data_sync.py --dry-run      # 不写入，仅报告
"""

import argparse
import datetime
import os
import sys
import time
import urllib.error
from pathlib import Path

import numpy as np
import pandas as pd
import struct
from tdxpy.reader import TdxDailyBarReader
from tdxpy.hq import TdxHq_API

# ── 路径 ───────────────────────────────────────────
DEFAULT_VIPDOC = "D:/TDX/vipdoc"
# 通达信公开服务器（按连通速度排序）
SERVERS = [
    ("218.75.126.9", 7709),       # 上海-1（最快）
    ("61.152.107.137", 7709),     # 深圳-1
    ("119.147.212.81", 7709),     # 深圳-2
    ("14.215.128.18", 7709),      # 上海-2
]

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
WORK_DIR = os.path.dirname(TOOLS_DIR)
sys.path.insert(0, TOOLS_DIR)


def _tushare_call(fn, *args, **kwargs):
    """对 tushare pro 调用加重试（指数退避，最多3次）。"""
    _RETRYABLE = (ConnectionError, BrokenPipeError, urllib.error.URLError,
                  urllib.error.HTTPError, OSError)
    _RETRY_DELAYS = [1, 2, 4]
    last_exc = None
    for i, delay in enumerate(_RETRY_DELAYS + [None]):
        try:
            return fn(*args, **kwargs)
        except _RETRYABLE as e:
            last_exc = e
            if delay is None:
                break
            print(f"  ⚠ tushare 失败(第{i+1}次): {e}，{delay}s 后重试...")
            time.sleep(delay)
    raise last_exc if last_exc else ValueError("tushare 重试耗尽")


def load_code_whitelist():
    """加载A股白名单"""
    codes_file = os.path.join(WORK_DIR, "tdx_scan_codes.json")
    if os.path.exists(codes_file):
        import json
        d = json.load(open(codes_file, encoding="utf-8"))
        return d.get("codes", []), d.get("names", {})
    import tushare as ts
    pro = ts.pro_api()
    try:
        basic = _tushare_call(pro.stock_basic, exchange="", list_status="L",
                              fields="ts_code,name,market")
    except Exception as e:
        print(f"🚨 tushare pro 不可用，白名单生成失败: {e}")
        raise
    codes, names = [], {}
    for _, r in basic.iterrows():
        c = r["ts_code"].split(".")[0]
        nm = r["name"]
        m = str(r["market"])
        if "ST" in nm.upper() or "退" in nm or m == "北交所":
            continue
        codes.append(c)
        names[c] = nm
    import json
    json.dump({"codes": codes, "names": names}, open(codes_file, "w", encoding="utf-8"))
    return codes, names


def _get_local_latest_date(reader, vipdoc_path: str, code: str) -> datetime.date:
    """获取本地 .day 文件最新日期"""
    ex = "sh" if code[0] in "69" else "sz"
    fname = f"{ex}{code}.day"
    fpath = Path(vipdoc_path) / ex / "lday" / fname
    if not fpath.exists():
        return None
    try:
        df = reader.get_df(str(fpath))
        if df.empty:
            return None
        return pd.to_datetime(df.index).max().date()
    except Exception:
        return None


def _get_market_code(code: str) -> int:
    """code -> market: 0=深圳, 1=上海"""
    c = str(code)
    if c[0] in "69" or c[:3] in ["009", "126", "110", "201", "202", "203", "204"]:
        return 1
    return 0


def _fetch_klines(api, code: str, market: int, start_date: datetime.date,
                  end_date: datetime.date) -> pd.DataFrame:
    """从服务器拉取K线，返回 DataFrame(date, open, high, low, close, vol, amount)"""
    # get_security_bars(category=9 日线, market, code, offset=0, count)
    days = (end_date - start_date).days + 5
    count = min(days + 5, 200)  # 一次最多200条
    raw = api.get_security_bars(9, market, code, 0, count)
    df = api.to_df(raw)
    if df.empty:
        return df
    # 过滤日期范围
    df["date_col"] = pd.to_datetime(df["datetime"]).dt.date
    df = df[(df["date_col"] >= start_date) & (df["date_col"] <= end_date)].copy()
    if df.empty:
        return df
    # 提取需要的列
    df = df.sort_values("datetime")
    return df


def _unpack_records_32bit(data: bytes) -> list:
    """通达信 .day 二进制格式: 32字节/行
    struct: <IIIIIfII (date, open, high, low, close 为int(价格*100), volume浮点, amount浮点)"""
    N = len(data) // 32
    records = []
    for i in range(N):
        rec = data[i * 32:(i + 1) * 32]
        date_int = int.from_bytes(rec[0:4], "little")
        open_p = int.from_bytes(rec[4:8], "little")
        high_p = int.from_bytes(rec[8:12], "little")
        low_p = int.from_bytes(rec[12:16], "little")
        close_p = int.from_bytes(rec[16:20], "little")
        volume = np.float64.frombuffer(rec[20:24])[0]
        amount = np.float64.frombuffer(rec[24:32])[0]
        # 日期解码: YYYYMMDD
        dt = pd.Timestamp(date_int)
        price_coef = 0.01  # 价格存为分，需/100
        records.append({
            "datetime": dt,
            "open": open_p / 100.0,
            "high": high_p / 100.0,
            "low": low_p / 100.0,
            "close": close_p / 100.0,
            "vol": volume,
            "amount": amount,
        })
    return records


def _write_kline_to_day_file(vipdoc_path: str, code: str, df: pd.DataFrame,
                             dry_run: bool = False) -> bool:
    """将K线DataFrame追加写入通达信 .day 文件
    格式: <IIIIIfII (32字节/行)
      字段: date(4I) + open(4I) + high(4I) + low(4I) + close(4I)
            + amount(4f) + volume(4I) + padding(4I=0)
      价格单位: 元×100(整数)
      amount单位: 元(浮点)
      volume单位: 股(整数)
    """
    ex = "sh" if code[0] in "69" else "sz"
    fname = f"{ex}{code}.day"
    fpath = Path(vipdoc_path) / ex / "lday" / fname

    if df.empty:
        return False

    chunks = b""
    for _, r in df.sort_values("datetime").iterrows():
        dt = r["datetime"]
        if isinstance(dt, str):
            dt = pd.Timestamp(dt)
        date_int = int(dt.strftime("%Y%m%d"))
        open_p = int(round(float(r["open"]) * 100))
        high_p = int(round(float(r["high"]) * 100))
        low_p = int(round(float(r["low"]) * 100))
        close_p = int(round(float(r["close"]) * 100))
        # amount = 元(服务器), volume = 手(服务器)
        amount = float(r.get("amount", 0))
        # 通达信原始文件: vol = 手×100 (整数); amount = 元 (float)
        vol = int(float(r["vol"]) * 100)  # 手 -> 文件单位
        pad = 0
        chunk = struct.pack("<IIIIIfIi",
                            date_int, open_p, high_p, low_p, close_p,
                            amount, vol, pad)
        chunks += chunk

    if dry_run:
        return True

    # 追加写入
    with open(fpath, "ab") as f:
        f.write(chunks)
    return True


def sync_single(vipdoc_path: str, code: str, today: datetime.date,
                reader: TdxDailyBarReader, api: TdxHq_API,
                verbose: bool = True, dry_run: bool = False) -> dict:
    """同步单只股票数据，返回 {code, local_date, synced_date, rows_written, ok}"""
    local_date = _get_local_latest_date(reader, vipdoc_path, code)
    if local_date and local_date >= today:
        return {"code": code, "local_date": str(local_date), "ok": True, "rows_written": 0, "reason": "已是最新"}

    market = _get_market_code(code)
    try:
        # 取近30天K线
        start = today - datetime.timedelta(days=30)
        df = _fetch_klines(api, code, market, start, today)
        if df.empty:
            return {"code": code, "local_date": str(local_date), "ok": False, "reason": "服务器无数据"}
        # 过滤已有数据
        if local_date:
            df = df[pd.to_datetime(df["datetime"]).dt.date > local_date]
        if df.empty:
            return {"code": code, "local_date": str(local_date), "ok": True, "rows_written": 0, "reason": "无新数据"}

        ok = _write_kline_to_day_file(vipdoc_path, code, df, dry_run=dry_run)
        synced = pd.to_datetime(df["datetime"]).max().date()
        return {"code": code, "local_date": str(local_date), "synced_date": str(synced),
                "rows_written": len(df), "ok": ok}
    except Exception as e:
        return {"code": code, "local_date": str(local_date), "ok": False, "reason": str(e)[:60]}


def check_freshness(vipdoc_path: str, codes: list, reader: TdxDailyBarReader) -> dict:
    """检查数据新鲜度"""
    today = datetime.date.today()
    results = []
    for code in codes:
        ld = _get_local_latest_date(reader, vipdoc_path, code)
        stale = ld is None or ld < today
        results.append({"code": code, "local_date": str(ld) if ld else "N/A", "stale": stale})
    return {
        "today": str(today),
        "total": len(results),
        "stale_count": sum(1 for r in results if r["stale"]),
        "latest_count": sum(1 for r in results if not r["stale"]),
        "samples": results[:10],
    }


def main():
    parser = argparse.ArgumentParser(description="通达信本地K线自动同步")
    parser.add_argument("--vipdoc", default=DEFAULT_VIPDOC, help="vipdoc路径")
    parser.add_argument("--code", default="", help="单只股票代码")
    parser.add_argument("--check", action="store_true", help="仅检查数据新鲜度")
    parser.add_argument("--dry-run", action="store_true", help="不写入，仅报告")
    parser.add_argument("--verbose", action="store_true", default=True)
    args = parser.parse_args()

    reader = TdxDailyBarReader()
    today = datetime.date.today()

    print(f"\n{'='*60}")
    print(f"🔄 通达信K线数据同步")
    print(f"📅 {today}  |  📂 {args.vipdoc}  |  {'[DRY RUN]' if args.dry_run else '[WRITE]'}")
    print(f"{'='*60}\n")

    # 检查
    codes, names = load_code_whitelist()
    if args.code:
        codes = [args.code]

    # 检查新鲜度
    freshness = check_freshness(args.vipdoc, codes, reader)
    print(f"📊 数据新鲜度检查")
    print(f"  总: {freshness['total']}  最新: {freshness['latest_count']}  待更新: {freshness['stale_count']}")
    print()
    for r in freshness["samples"][:5]:
        flag = "✅" if not r["stale"] else "⚠️"
        print(f"  {flag} {r['code']}  最新: {r['local_date']}")
    print()

    if args.check:
        print("✅ 检查完成\n")
        return

    if freshness["stale_count"] == 0:
        print("✅ 所有数据已是最新，无需同步\n")
        return

    # 连接服务器
    print(f"🌐 连接通达信服务器...")
    api = TdxHq_API()
    conn_ok = False
    used_server = None
    for ip, port in SERVERS:
        try:
            t0 = time.time()
            api.connect(ip, port, time_out=5)
            used_server = f"{ip}:{port}"
            conn_ok = True
            print(f"  ✅ 连接 {ip}:{port} ({time.time()-t0:.2f}s)")
            break
        except Exception:
            pass
    if not conn_ok:
        print("❌ 无法连接通达信服务器，请检查网络")
        return

    # 同步
    if freshness["stale_count"] > 0:
        print(f"\n📥 开始同步 {freshness['stale_count']} 只股票...\n")
        synced = 0
        failed = 0
        for i, code in enumerate(codes):
            res = sync_single(args.vipdoc, code, today, reader, api,
                              verbose=False, dry_run=args.dry_run)
            if res["ok"]:
                if res.get("rows_written", 0) > 0:
                    synced += 1
                    if args.verbose:
                        print(f"  ✅ {code}: {res.get('local_date','N/A')} → {res.get('synced_date','')}  ({res['rows_written']}条)")
                elif res.get("reason", "") == "无新数据":
                    pass  # 服务器无新数据，可能是非交易时间
                elif res.get("reason", "") == "已是最新":
                    pass
            else:
                failed += 1
                if args.verbose and failed <= 3:
                    print(f"  ❌ {code}: {res.get('reason', '')}")

            if (i + 1) % 100 == 0:
                print(f"  进度: {i+1}/{len(codes)}  已同步{synced}  失败{failed}")

        api.disconnect()
        print(f"\n📊 同步完成")
        print(f"  已更新: {synced} 只")
        print(f"  失败: {failed} 只")
        if args.dry_run:
            print(f"  ⚠️ [DRY RUN] 未实际写入文件")
        print()
    else:
        api.disconnect()

    print(f"✅ 完成\n")


if __name__ == "__main__":
    main()
