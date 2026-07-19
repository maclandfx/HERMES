#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tdx_batch_scanner.py —— 通达信5条件选股全市场批量扫描
用法: python tdx_batch_scanner.py --scan-only       只跑选股
      python tdx_batch_scanner.py --scan-and-eval    选股 + 对候选跑智能评估
      python tdx_batch_scanner.py --top 10           输出前N只候选
      python tdx_batch_scanner.py --report           输出markdown报告到 reports/粗评/

数据源: tushare.pro.daily(ts_code, start_date, end_date)  （复用评估体系已通链路）
"""

import argparse
import datetime
import json
import os
import sys

# ── 路径 ──────────────────────────────────────────────
WORK_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = WORK_DIR  # 本脚本就在 tools/ 下
REPORT_DIR = os.path.join(os.path.dirname(WORK_DIR), "reports", "粗评")
os.makedirs(REPORT_DIR, exist_ok=True)
sys.path.insert(0, TOOLS_DIR)


def main():
    import tushare as ts
    import tdx_stockpickers as sp

    parser = argparse.ArgumentParser(description="通达信5条件选股全市场批量扫描")
    parser.add_argument("--scan-only", action="store_true", help="只跑选股，不评估")
    parser.add_argument("--scan-and-eval", action="store_true", help="选股 + 对候选跑智能评估")
    parser.add_argument("--top", type=int, default=20, help="输出候选股数量(默认20)")
    parser.add_argument("--report", action="store_true", help="生成markdown报告写入reports/粗评/")
    parser.add_argument("--json-out", type=str, default="", help="输出json到指定路径")
    args = parser.parse_args()

    pro = ts.pro_api()

    # ── 获取全市场股票列表 ─────────────────────────
    print("\n" + "=" * 60)
    print("🔍 通达信5条件选股 — 全市场批量扫描")
    print("=" * 60 + "\n")

    print("📂 获取全市场股票列表...")
    basic = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
    print(f"  全市场上市股票: {len(basic)} 只")

    # 过滤掉 ST、退市风险、科创板次新（太新无足够K线）
    codes_all = [r["ts_code"].split(".")[0] for _, r in basic.iterrows()
                 if "ST" not in r["name"].upper() and "退" not in r["name"]]
    print(f"  过滤后候选池: {len(codes_all)} 只")

    ts_map = {r["ts_code"].split(".")[0]: {"ts": r["ts_code"], "name": r["name"]}
              for _, r in basic.iterrows() if "ST" not in r["name"].upper() and "退" not in r["name"]}

    # ── 批量扫描 ─────────────────────────────────────
    print(f"\n🔎 开始全市场扫描 {len(codes_all)} 只...")
    out = sp.run_scanner(codes_all, ts_codes=ts_map, tushare_pro=pro, verbose=False)

    s = out["summary"]
    print(f"\n{'─' * 40}")
    print(f"📊 扫描结果汇总")
    print(f"{'─' * 40}")
    print(f"  扫描总数: {s['总扫描']}")
    print(f"  命中≥2条件: {s['命中>=2条件']}")
    print(f"  命中全部5条件: {s['命中全部5条件']}")
    print(f"  候选股数: {s['候选股数']}")
    print(f"\n  各条件命中数:")
    for cn, cnt in s["各条件命中数"].items():
        bar = "█" * min(cnt, 30)
        print(f"    {cn}: {cnt} {bar}")

    # ── 输出候选列表 ─────────────────────────────────
    candidates = out["candidates"][:args.top]
    print(f"\n{'═' * 70}")
    print(f"🎯 TOP {args.top} 候选股（按命中条件数排序）")
    print(f"{'═' * 70}")

    for i, c in enumerate(candidates, 1):
        code = c.get("code", "?")
        name = c.get("name", "")
        print(f"\n  [{i}] {code} {name}")
        print(f"      命中 {c['passed_count']}/5 条件 | 最高分 {c['max_score']}")
        print(f"      命中条件: {', '.join(c['passed_conditions'])}")
        for cn, cr in c["results"].items():
            flag = "✅" if cr["passed"] else ("🔶" if cr["score"] >= 50 else "❌")
            print(f"      {flag} {cn}({cr['score']}分): {cr['reason'][:60]}")

    # ── 报告输出 ─────────────────────────────────────
    report_path = None
    if args.report:
        report_path = os.path.join(
            REPORT_DIR,
            f"通达信选股_{len(candidates)}只候选_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.md"
        )
        md = generate_md_report(out, candidates, args.top)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"\n📄 报告已写入: {report_path}")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n📄 JSON已写入: {args.json_out}")

    # ── 可选：对候选跑智能评估 ─────────────────────
    if args.scan_and_eval:
        print(f"\n📈 对 {len(candidates)} 只候选股运行智能评估...")
        eval_codes = [c.get("code", "") for c in candidates if c.get("code")]
        if eval_codes:
            try:
                import eval_smart
                eval_smart.run_smart_eval(eval_codes, verbose=True)
                print("✅ 智能评估完成，详见 reports/粗评/ 最新文件")
            except Exception as e:
                print(f"⚠ 智能评估调用失败: {e}")

    print("\n✅ 扫描完成")
    return out


def generate_md_report(out, candidates, top_n):
    """生成markdown报告"""
    s = out["summary"]
    ts_now = datetime.datetime.now().strftime("%Y年%m月%d日 %H:%M")

    md = f"""# 🔍 通达信5条件选股报告

**扫描时间**: {ts_now}  
**数据截止**: {out.get('end_date', '—')}  
**扫描范围**: A股全市场（排除ST/退市）  
**评估体系**: 通达信条件选股 v1.0

---

## 📊 扫描汇总

| 指标 | 数值 |
|------|------|
| 扫描总数 | {s['总扫描']} |
| 命中≥2条件 | {s['命中>=2条件']} |
| 命中全部5条件 | {s['命中全部5条件']} |
| 候选股数 | {s['候选股数']} |

### 各条件命中数

| 条件 | 命中数 |
|------|--------|
"""
    for cn, cnt in s["各条件命中数"].items():
        md += f"| {cn} | {cnt} |\n"

    md += f"""
---

## 🎯 TOP {top_n} 候选股

| # | 代码 | 名称 | 命中数 | 最高分 | 命中条件 |
|---|------|------|--------|--------|----------|
"""
    for i, c in enumerate(candidates, 1):
        code = c.get("code", "?")
        name = c.get("name", "")
        conds = ", ".join(c["passed_conditions"])
        md += f"| {i} | {code} | {name} | {c['passed_count']}/5 | {c['max_score']} | {conds} |\n"

    md += """

---

## 🔧 5条件选股公式说明

| 条件 | 选股逻辑 |
|------|----------|
| **20日DCZ双回踩** | 近20日股价≥2次回调到DCZ(中位成本)±3%并放量获支撑，现价位于DCZ之上 |
| **四维共振主起** | 天时(大盘多头)+地利(板块ZSCORE>1.5)+人和(北向净流入)+技术(突破)四力汇聚 |
| **金牌狙击紧** | 主力进场信号+主进A/B级+筹码集中(<30%)+量价齐升(量比>1.5,涨>3%) |
| **黄金右侧** | 突破趋势通道上轨+MACD金叉+主力资金净流入，右侧追涨信号 |
| **黄金右侧紧** | 黄金右侧基础上+5日累计涨<10%+日涨<10%（排除已加速高位） |

---

## ⚠️ 免责声明

本报告基于通达信主力全景公式 v3.9/V6.05 的 Python 移植实现，
为技术分析参考，**不构成投资建议**。

- 公式中 `COST` 函数用成交加权近似，与通达信实际计算存在差异
- 选股条件需结合个股基本面、市场情绪综合判断
- 所有候选股进入评估体系后仍需十维度评分确认

---

*报告生成时间: {ts_now}*  
*选股模块: tdx_stockpickers.py v1.0*
"""
    return md


if __name__ == "__main__":
    main()
