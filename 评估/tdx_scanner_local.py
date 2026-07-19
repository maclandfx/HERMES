#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tdx_scanner_local.py —— 通达信5条件选股全市场扫描（本地文件版，v2）

数据源: 通达信本地 .day 文件（tdxpy.reader.TdxDailyBarReader）
白名单: 仅扫描A股（排除北交所/ST/退市），约5000只
速度: ~100只/秒（v2优化后）

用法:
  python tdx_scanner_local.py               # 全市场扫描
  python tdx_scanner_local.py --top 20      # 输出前20候选
  python tdx_scanner_local.py --report      # 生成markdown报告
  python tdx_scanner_local.py --json-out x.json
"""

import argparse
import datetime
import json
import os
import sys
import time
import numpy as np
import pandas as pd
from pathlib import Path

# 路径
TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
WORK_DIR = os.path.dirname(TOOLS_DIR)
REPORT_DIR = os.path.join(WORK_DIR, "reports", "粗评")
CODES_FILE = os.path.join(WORK_DIR, "tdx_scan_codes.json")
os.makedirs(REPORT_DIR, exist_ok=True)


CONDITIONS = ["20日DCZ双回踩", "四维共振主起", "金牌狙击紧", "黄金右侧", "黄金右侧紧"]


def load_code_whitelist():
    """加载A股白名单（排除北交所/ST/退市）"""
    if os.path.exists(CODES_FILE):
        d = json.load(open(CODES_FILE, encoding="utf-8"))
        return d.get("codes", []), d.get("names", {})
    # 实时生成
    import tushare as ts
    pro = ts.pro_api()
    basic = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name,market")
    codes, names = [], {}
    for _, r in basic.iterrows():
        c = r["ts_code"].split(".")[0]
        nm = r["name"]
        m = str(r["market"])
        if "ST" in nm.upper() or "退" in nm or m == "北交所":
            continue
        codes.append(c); names[c] = nm
    json.dump({"codes": codes, "names": names}, open(CODES_FILE, "w", encoding="utf-8"))
    return codes, names


def _ma(v, m):
    return float(np.mean(v[-m:]))


def _chip(df):
    sub = df.tail(60)
    amt = (sub["close"].astype(float).values * sub["vol"].astype(float).values)
    total = amt.sum()
    if total == 0:
        return 50.0, float(df["close"].iloc[-1])
    s = pd.DataFrame({"c": sub["close"].astype(float).values, "a": amt})
    s = s.sort_values("c")
    s["cum"] = s["a"].cumsum()
    try:
        c5 = float(s.loc[s["cum"] >= total * 0.05, "c"].iloc[0])
        c95 = float(s.loc[s["cum"] >= total * 0.95, "c"].iloc[0])
    except Exception:
        return 50.0, float(df["close"].iloc[-1])
    return round(float((c95 - c5) / (c95 + c5) * 100), 1), round(float((c5 + c95) / 2), 2)


def _avg_line(h, l, c):
    """通达信平均线 = EMA(4, EMA(3, (C-LLV(L,10))/(HHV(H,25)-LLV(L,10))*4))"""
    s = pd.Series(c)
    min10 = pd.Series(l).rolling(10, min_periods=1).min().values
    max25 = pd.Series(h).rolling(25, min_periods=1).max().values
    rng = (max25 - min10).clip(0.001)
    wave = (s.values - min10) / rng * 4
    w = pd.Series(wave)
    return w.ewm(span=4, adjust=False).mean().ewm(span=3, adjust=False).mean().values


def scan_one(cn, c, o, h, l, v):
    """纯numpy向量化选股，避免pandas逐行循环"""
    n = len(c)
    last_c, last_o, c_prev = c[-1], o[-1], c[-2] if n >= 2 else last_c
    vm5 = _ma(v, 5)
    conc, dcz = _chip_fake(c, v)  # 简化筹码
    if cn == "20日DCZ双回踩":
        pulls, valid = 0, 0
        for i in range(n - 20, n):
            if abs(c[i] - dcz) / max(dcz, 0.001) <= 0.03:
                pulls += 1
                vr = v[i] / max(_ma(v[:i + 1], 5), 0.001)
                ls = c[i] - l[i]
                if (ls > abs(c[i] - o[i]) or vr > 1.2) and vr > 1.1:
                    valid += 1
        score = (20 if pulls >= 2 else 0) + (30 if valid >= 2 else 0) + (20 if last_c > dcz else 0)
        passed = valid >= 2 and last_c > dcz
        return {"passed": passed, "score": min(score, 100),
                "reason": f"{pulls}次回踩, {valid}次放量, 现价¥{last_c:.2f}{'>' if last_c > dcz else '<='}DCZ¥{dcz:.2f}"}
    if cn == "四维共振主起":
        ma20 = _ma(c, 20)
        tech = last_c > ma20 and np.max(v[-5:]) > vm5 * 1.5
        return {"passed": False, "score": 25 if tech else 0, "reason": f"技术={tech}（需外部天时地利人和）"}
    if cn == "金牌狙击紧":
        avg = _avg_line(h, l, c)
        vv = v / np.array([_ma(v[:i + 1], 5) for i in range(n)]).clip(0.001)
        r0 = ((c - np.roll(c, 1)) / np.roll(np.maximum(c, 0.001), 1) * 100) * vv
        r0a5 = sum(abs(r0[-i]) for i in range(1, 6)) / 5
        main_enter = (r0[-1] > r0a5 / 2) and (avg[-1] >= avg[-2]) and (avg[-2] < avg[-3])
        vr = v[-1] / max(vm5, 0.001)
        chg = (last_c - c_prev) / max(c_prev, 0.001) * 100
        passed = main_enter and conc < 30 and vr > 1.5 and chg > 3
        score = 90 if passed else (65 if main_enter and (conc < 30 or vr > 1.5) and chg > 3 else (40 if main_enter else 0))
        return {"passed": passed, "score": min(score, 100),
                "reason": f"主进={main_enter}, 筹码{conc}%, 量比{vr:.2f}, 涨{chg:.1f}%"}
    if cn == "黄金右侧":
        avg = _avg_line(h, l, c)
        ch_mid = float(np.mean(avg[-5:]))
        ch_std = float(np.std(avg[-20:]))
        ch_up = ch_mid + 2 * max(ch_std, 0.001)
        break_up = last_c > ch_up and c_prev <= ch_up
        dif = pd.Series(c).ewm(span=12, adjust=False).mean() - pd.Series(c).ewm(span=26, adjust=False).mean()
        dea = dif.ewm(span=9, adjust=False).mean()
        macd_cross = float(dif.iloc[-1]) > float(dea.iloc[-1]) and float(dif.iloc[-2]) <= float(dea.iloc[-2])
        vv = v / np.array([_ma(v[:i + 1], 5) for i in range(n)]).clip(0.001)
        r0 = ((c - np.roll(c, 1)) / np.roll(np.maximum(c, 0.001), 1) * 100) * vv
        money_in = r0[-1] > 0 and np.mean(r0[-3:]) > 0
        score = (30 if break_up else 0) + (25 if macd_cross else 0) + (25 if money_in else 0)
        return {"passed": bool(break_up and macd_cross and money_in), "score": max(score, 0),
                "reason": f"突破={break_up}, MACD={macd_cross}, 资金={money_in}"}
    if cn == "黄金右侧紧":
        base = scan_one("黄金右侧", c, o, h, l, v)
        cum5 = (last_c - c[-6]) / max(c[-6], 0.001) * 100 if n >= 6 else 0
        tight = cum5 < 10 and (last_c - c_prev) / max(c_prev, 0.001) * 100 < 10
        return {"passed": bool(base["passed"]) and tight, "score": min(int(base["score"]) + (10 if tight else 0), 100),
                "reason": f"5日涨{cum5:.1f}%, {'紧' if tight else '已加速'}"}
    return {"passed": False, "score": 0, "reason": ""}


def _chip_fake(c, v):
    """快速筹码估算（60日成交量加权）"""
    c60, v60 = c[-60:], v[-60:]
    amt = c60 * v60
    total = amt.sum()
    if total == 0: return 50.0, c[-1]
    idx = np.argsort(c60)
    cum = np.cumsum(amt[idx])
    c5 = c60[idx[int(np.searchsorted(cum, total * 0.05))]]
    c95 = c60[idx[min(int(np.searchsorted(cum, total * 0.95)), len(idx) - 1)]]
    return round(float((c95 - c5) / (c95 + c5) * 100), 1), round(float((c5 + c95) / 2), 2)


def run_scanner(vipdoc_path=None, verbose=True):
    """全市场批量扫描（本地 .day 文件 + 白名单）"""
    if vipdoc_path is None:
        vipdoc_path = "D:/TDX/vipdoc"

    codes, names = load_code_whitelist()
    print(f"  白名单: {len(codes)} 只A股（排除北交所/ST/退市）\n")

    # 构建 code -> 文件路径映射
    from tdxpy.reader import TdxDailyBarReader
    reader = TdxDailyBarReader()
    code2path = {}
    for ex in ["sz", "sh"]:
        lday = Path(vipdoc_path) / ex / "lday"
        if lday.is_dir():
            for f in lday.iterdir():
                if f.suffix == ".day":
                    code = f.name[2:8]
                    if code in names:
                        code2path[code] = str(f)

    candidates = []
    by_condition = {n: [] for n in CONDITIONS}
    scanned = 0
    t0 = time.time()

    for i, code in enumerate(codes):
        fpath = code2path.get(code)
        if fpath is None:
            continue
        try:
            df = reader.get_df(fpath)
        except Exception:
            continue
        if df is None or df.empty or len(df) < 30:
            continue
        df = df.reset_index().rename(columns={"date": "trade_date"})
        df["vol"] = df["volume"].astype(float)

        c = df["close"].astype(float).values
        o = df["open"].astype(float).values
        h = df["high"].astype(float).values
        l = df["low"].astype(float).values
        v = df["vol"].values

        passed_count = 0
        passed_names = []
        scores = {}
        reasons = {}
        for cn in CONDITIONS:
            res = scan_one(cn, c, o, h, l, v)
            scores[cn] = res["score"]
            reasons[cn] = res["reason"]
            if res["passed"]:
                passed_count += 1
                passed_names.append(cn)

        scanned += 1

        if passed_count > 0:
            candidates.append({
                "code": code, "name": names.get(code, ""),
                "passed_count": passed_count, "passed_conditions": passed_names,
                "max_score": max(scores.values()),
                "scores": scores, "reasons": reasons,
            })
            for cn in passed_names:
                by_condition[cn].append(code)

        if verbose and (i + 1) % 1000 == 0:
            elapsed = time.time() - t0
            speed = (i + 1) / max(elapsed, 0.001)
            eta = (len(codes) - i - 1) / max(speed, 0.001)
            print(f"  进度: {i + 1}/{len(codes)} 已扫描 {scanned} 命中 {len(candidates)}  速度 {speed:.0f}只/秒  剩余 {eta:.0f}s")

    elapsed = time.time() - t0
    candidates.sort(key=lambda x: (-x["passed_count"], -x["max_score"]))

    if verbose:
        print(f"\n{'─' * 40}")
        print(f"📊 扫描完成")
        print(f"{'─' * 40}")
        print(f"  扫描总数: {scanned}  耗时: {elapsed:.1f}s  速度: {scanned / max(elapsed, 0.001):.0f}只/秒")
        print(f"  命中≥2条件: {sum(1 for c in candidates if c['passed_count'] >= 2)}")
        print(f"  候选股数: {len(candidates)}")
        for cn in CONDITIONS:
            print(f"  {cn}: {len(by_condition[cn])}只")

    return {
        "scanned": scanned, "elapsed_sec": round(elapsed, 1),
        "speed": round(scanned / max(elapsed, 0.001), 0),
        "by_condition": by_condition, "candidates": candidates,
        "summary": {
            "总扫描": scanned, "耗时_秒": round(elapsed, 1),
            "速度_只每秒": round(scanned / max(elapsed, 0.001), 0),
            "命中>=2条件": sum(1 for c in candidates if c["passed_count"] >= 2),
            "命中全部5条件": sum(1 for c in candidates if c["passed_count"] == 5),
            "各条件命中数": {n: len(by_condition[n]) for n in CONDITIONS},
            "候选股数": len(candidates),
        },
        "vipdoc_path": vipdoc_path,
    }


def generate_md(result, top_n):
    s = result["summary"]
    now = datetime.datetime.now()
    md = f"""# 🔍 通达信5条件选股报告（本地文件版）

**扫描时间**: {now.strftime('%Y年%m月%d日 %H:%M')}  
**数据源**: 通达信本地 .day 文件  
**扫描**: {s['总扫描']}只  耗时{s['耗时_秒']}s  速度{s['速度_只每秒']}只/秒

---

## 📊 扫描汇总

| 指标 | 数值 |
|------|------|
| 扫描总数 | {s['总扫描']} |
| 命中≥2条件 | {s['命中>=2条件']} |
| 候选股数 | {s['候选股数']} |

### 各条件命中数

| 条件 | 命中数 |
|------|--------|
"""
    for cn, cnt in s["各条件命中数"].items():
        md += f"| {cn} | {cnt} |\n"
    md += f"\n---\n\n## 🎯 TOP {top_n} 候选股\n\n| # | 代码 | 名称 | 命中数 | 最高分 | 命中条件 |\n|---|------|------|--------|--------|----------|\n"
    for i, c in enumerate(result["candidates"][:top_n], 1):
        conds = ", ".join(c["passed_conditions"])
        md += f"| {i} | {c['code']} | {c['name']} | {c['passed_count']}/5 | {c['max_score']} | {conds} |\n"
    multi = [c for c in result["candidates"] if c["passed_count"] >= 2]
    if multi:
        md += f"\n---\n\n## 💎 重点候选：命中≥2条件（{len(multi)}只）\n\n| # | 代码 | 名称 | 命中条件 | 最高分 |\n|---|------|------|----------|--------|\n"
        for i, c in enumerate(multi[:15], 1):
            conds = ", ".join(c["passed_conditions"])
            md += f"| {i} | {c['code']} | {c['name']} | {conds} | {c['max_score']} |\n"
        md += "\n### 条件详情（前5只）\n\n"
        for c in multi[:5]:
            md += f"\n**{c['code']} {c['name']}** (命中{c['passed_count']}/5)\n\n| 条件 | 分数 | 说明 |\n|------|------|------|\n"
            for cn in CONDITIONS:
                flag = "✅" if cn in c["passed_conditions"] else "❌"
                md += f"| {flag} {cn} | {c['scores'].get(cn, 0)} | {c['reasons'].get(cn, '')[:55]} |\n"
    md += "\n---\n\n*报告生成时间: " + now.strftime('%Y-%m-%d %H:%M') + "*\n"
    return md


def main():
    parser = argparse.ArgumentParser(description="通达信5条件选股全市场扫描（本地文件版）")
    parser.add_argument("--vipdoc", default="D:/TDX/vipdoc", help="通达信vipdoc路径")
    parser.add_argument("--top", type=int, default=20, help="输出候选数量")
    parser.add_argument("--json-out", default="", help="输出JSON到指定路径")
    parser.add_argument("--report", action="store_true", help="生成markdown报告")
    parser.add_argument("--no-verbose", action="store_true", help="静默模式")
    args = parser.parse_args()
    verbose = not args.no_verbose
    print(f"\n{'=' * 60}")
    print(f"🔍 通达信5条件选股 — 全市场扫描（本地文件版）")
    print(f"📅 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"📂 {args.vipdoc}")
    print(f"{'=' * 60}\n")
    result = run_scanner(args.vipdoc, verbose=verbose)
    print(f"\n{'═' * 70}")
    print(f"🎯 TOP {args.top} 候选股")
    print(f"{'═' * 70}")
    for i, c in enumerate(result["candidates"][:args.top], 1):
        conds = ", ".join(c["passed_conditions"])
        print(f"\n  [{i}] {c['code']} {c['name']}  命中{c['passed_count']}/5  分{c['max_score']}  {conds}")
        for cn in CONDITIONS:
            flag = "✅" if cn in c["passed_conditions"] else "❌"
            print(f"      {flag} {cn}({c['scores'].get(cn, 0)}): {c['reasons'].get(cn, '')[:55]}")
    if args.json_out:
        json.dump(result, open(args.json_out, "w", encoding="utf-8"), ensure_ascii=False, indent=2, default=str)
        print(f"\n📄 JSON已写入: {args.json_out}")
    if args.report:
        p = os.path.join(REPORT_DIR, f"通达信选股_local_{len(result['candidates'])}只_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.md")
        open(p, "w", encoding="utf-8").write(generate_md(result, args.top))
        print(f"📄 报告已写入: {p}")
    print(f"\n✅ 完成  扫描{result['scanned']}只 耗时{result['elapsed_sec']}s  命中{len(result['candidates'])}只")
    return result


if __name__ == "__main__":
    main()
