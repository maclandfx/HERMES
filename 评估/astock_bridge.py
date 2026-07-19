"""a-stock-data 数据桥接器 — 让评估中心能用上 a-stock-data skill 的端点

【实测可用端点】(本机2026-07-05 测试通过)
  ✓ 腾讯财经 qt.gtimg.cn             实时行情/PE/PB/振幅/涨跌停价/量比
  ✓ 东方财富 datacenter-web          RPT_MUTUAL_HOLD_DET 北向持股明细（近期数据滞后）

【本机不可用端点】
  ✗ 东财push2.eastmoney.com         RemoteDisconnected (网络层屏蔽)
  ✗ 百度finance.pae.baidu.com        本机返回空数据(可能需登录态)
  ✗ 同花顺stock/api/v1/...          大量端点 len=0 / 404
"""

import os
import re
import json
import time
import urllib.request
import urllib.parse
import random


# ═══════════════════════════════════════════════════
#  Layer 1.2: 腾讯实时行情（不封 IP，永远稳定）
# ═══════════════════════════════════════════════════

def tencent_quote(codes, request_timeout=10):
    """腾讯财经批量实时行情 — 不封 IP，单次请求 ~670ms

    输入: ["000938", "603638"] 或 ["000938.SZ"] 或数字混合中文名（中文会被跳过）
    返回: {纯数字代码: {name, price, pe_ttm, pb, ...}}
    """
    if isinstance(codes, str):
        codes = [codes]

    prefixed = []
    for c in codes:
        c = c.strip()
        # 跳过非数字/含中文条目
        if not c or not all(ch.isdigit() or ch == '.' for ch in c):
            continue
        if "." in c:
            pure = c.split(".")[0]
        else:
            pure = c
        if not pure.isdigit():
            continue

        if pure.startswith(("60", "68", "90", "11", "13")):
            prefix = "sh"
        elif pure.startswith(("00", "30", "20")):
            prefix = "sz"
        elif pure.startswith(("8", "43", "83", "87")):
            prefix = "bj"
        else:
            prefix = "sz"

        prefixed.append(f"{prefix}{pure}")

    if not prefixed:
        return {}

    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    # 编码安全：纯 ASCII
    url = url.encode("ascii", errors="replace").decode("ascii")
    last_exc = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "Mozilla/5.0")
            resp = urllib.request.urlopen(req, timeout=request_timeout)
            # 真实响应是 GBK
            data = resp.read().decode("gbk", errors="replace")
            break
        except Exception as e:
            last_exc = e
            if attempt < 2:
                print(f"  ⚠ 腾讯接口失败(第{attempt+1}次): {e}，1s 后重试...")
                time.sleep(1)
            else:
                print(f"  ⚠ 腾讯接口连续3次失败: {e}，返回空数据")
    else:
        return {}

    result = {}
    for line in data.strip().split(";"):
        if "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        pure = key[2:]
        result[pure] = {
            "name":         vals[1],
            "price":        _to_float(vals[3]),
            "last_close":   _to_float(vals[4]),
            "open":         _to_float(vals[5]),
            "change_amt":   _to_float(vals[31]),
            "change_pct":   _to_float(vals[32]),
            "high":         _to_float(vals[33]),
            "low":          _to_float(vals[34]),
            "amount_wan":   _to_float(vals[37]),
            "turnover_pct": _to_float(vals[38]),
            "pe_ttm":       _to_float(vals[39]),
            "amplitude_pct":_to_float(vals[43]),  # ⚠ 是振幅！
            "mcap_yi":      _to_float(vals[44]),
            "float_mcap_yi":_to_float(vals[45]),
            "pb":           _to_float(vals[46]),
            "limit_up":     _to_float(vals[47]),
            "limit_down":   _to_float(vals[48]),
            "vol_ratio":    _to_float(vals[49]),
            "pe_static":    _to_float(vals[52]),
        }
    return result


def _to_float(s, default=0.0):
    try:
        return float(s) if s else default
    except (ValueError, TypeError):
        return default


# ═══════════════════════════════════════════════════
#  Layer 1.3: 百度股市通 K线（带 MA5/10/20）
# ═══════════════════════════════════════════════════

def baidu_kline(code, market="sh", ktype="1"):
    """百度股市通 K线 — 实测本机返回空，仅作为 fallback 保留"""
    secid = f"{market}.{code}"
    url = "https://finance.pae.baidu.com/selfselect/getstockquotation"
    params = {
        "all": "1", "isIndex": "false", "isBk": "false", "isBlock": "false",
        "isFutures": "false", "isStock": "true", "newFormat": "1",
        "group": "quotation_kline_ab", "finClientType": "pc",
        "code": secid, "start_time": "", "ktype": ktype,
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/vnd.finance-web.v1+json",
        "Origin": "https://gushitong.baidu.com",
        "Referer": "https://gushitong.baidu.com/",
    }
    try:
        req = urllib.request.Request(
            url + "?" + urllib.parse.urlencode(params),
            headers=headers,
        )
        resp = urllib.request.urlopen(req, timeout=10)
        d = json.loads(resp.read().decode('utf-8', errors='replace'))
    except Exception as e:
        return {"error": str(e), "rows": [], "keys": [], "is_empty": True}

    result = d.get("Result")
    if not isinstance(result, dict):
        return {
            "error": f"Unexpected Result type: {type(result).__name__} = {str(result)[:80]}",
            "rows": [], "keys": [], "is_empty": True,
            "result_code": d.get("ResultCode"),
            "raw": d,
        }
    md = result.get("newMarketData", {})
    keys = md.get("keys", []) or []
    rows_raw = md.get("marketData", "")
    rows = rows_raw.split(";") if isinstance(rows_raw, str) else (rows_raw or [])
    return {
        "keys": keys, "rows": rows,
        "is_empty": (rows_raw == "" or not keys),
        "result_code": d.get("ResultCode"), "raw": d,
    }


# ═══════════════════════════════════════════════════
#  Layer 3.6 (东财北向): RPT_MUTUAL_HOLD_DET
# ═══════════════════════════════════════════════════

def eastmoney_north_holdings(stock_code, max_rows=10):
    """东财 datacenter 北向持股明细

    ⚠ 北向数据自 2024-08 起接近实时断供（参见 SKILL.md V3+ 提示）
    """
    url = (f"https://datacenter-web.eastmoney.com/api/data/v1/get?"
           f"reportName=RPT_MUTUAL_HOLD_DET&columns=ALL&pageSize={max_rows}"
           f"&filter=(SECURITY_CODE%3D%22{stock_code}%22)"
           f"&sortColumns=HOLD_DATE&sortTypes=-1")
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://data.eastmoney.com/",
        })
        resp = urllib.request.urlopen(req, timeout=10)
        text = resp.read().decode('utf-8')
        data = json.loads(text).get("result", {}).get("data", [])
        return data
    except Exception as e:
        return [{"error": str(e)}]


# ═══════════════════════════════════════════════════
#  高层桥接
# ═══════════════════════════════════════════════════

def enrich_with_tencent(stock_data_by_code):
    """用腾讯API增强评估中心数据 — 注:输入必须是代码键，不是中文名"""
    codes = list(stock_data_by_code.keys())
    code_map = {c: (c.split(".")[0] if "." in c else c) for c in codes}
    quotes = tencent_quote([code_map[c] for c in codes])

    for code_orig in codes:
        pure = code_map[code_orig]
        if pure in quotes:
            q = quotes[pure]
            sd = stock_data_by_code[code_orig]
            sd["tencent"] = q
            if q.get("pe_ttm", 0) > 0:
                sd["pe_ttm"] = q["pe_ttm"]
            if q.get("pb", 0) > 0:
                sd["pb"] = q["pb"]
            sd["amplitude_pct"] = q.get("amplitude_pct", 0)
            sd["vol_ratio"] = q.get("vol_ratio", 0)
            sd["limit_up_price"] = q.get("limit_up", 0)
            sd["limit_down_price"] = q.get("limit_down", 0)
            sd["float_mcap_yi"] = q.get("float_mcap_yi", 0)
            sd["turnover_pct"] = q.get("turnover_pct", 0)
    return stock_data_by_code


# ═══════════════════════════════════════════════════
#  状态
# ═══════════════════════════════════════════════════

BRIDGE_STATUS = """
╔══════════════════════════════════════════════════════════╗
║         a-stock-data 桥接器 — 端点可用性 (2026-07-05)   ║
╠══════════════════════════════════════════════════════════╣
║  ✓ 腾讯财经 qt.gtimg.cn        100% 可用              ║
║  ✓ 东财 datacenter-web         部分                   ║
║      北向持股 RPT_MUTUAL_HOLD_DET                       ║
║      行业板块 报表名更新 ✗                              ║
║  ✗ 东财 push2.eastmoney.com    本机被屏蔽              ║
║  ✗ 同花顺热点接口            大量 404 / 空             ║
║  ✗ 百度股市通 K线              本机返回空               ║
╚══════════════════════════════════════════════════════════╝
"""


if __name__ == "__main__":
    print(BRIDGE_STATUS)
    print("=" * 60)
    print("桥接器测试 - 紫光股份、艾迪精密")
    print("=" * 60)

    print("\n[1/3] 腾讯 qt.gtimg.cn")
    q = tencent_quote(["000938", "603638"])
    for c, info in q.items():
        print(f"  {info['name']}({c}): ¥{info['price']:.2f} "
              f"PE={info['pe_ttm']:.1f}x PB={info['pb']:.2f}x "
              f"振幅={info['amplitude_pct']:.2f}% 量比={info['vol_ratio']:.2f} "
              f"涨停¥{info['limit_up']:.2f}")

    print("\n[2/3] 百度 finance.pae.baidu.com")
    kl = baidu_kline("000938", market="sz")
    if kl.get("is_empty"):
        print(f"  ⚠ 端点空数据 (ResultCode={kl.get('result_code')})")
    elif "error" in kl:
        print(f"  ⚠ 失败: {kl['error']}")
    else:
        print(f"  ✓ keys={len(kl['keys'])}, rows={len(kl['rows'])}")

    print("\n[3/3] 东财 datacenter-web 北向明细")
    nh = eastmoney_north_holdings("000938", max_rows=3)
    if nh and "error" not in nh[0]:
        print(f"  紫光股份 北向持仓记录: {len(nh)} 条")
        for r in nh[:3]:
            print(f"    {r.get('HOLD_DATE', '')[:10]}: 持股{r.get('HOLD_NUM', 0):>10,} "
                  f"机构{r.get('ORG_NAME', '')[:25]}")
    elif nh and "error" in nh[0]:
        print(f"  ⚠ 失败: {nh[0]['error']}")
    else:
        print("  (空数据 — 北向明细滞后)")
