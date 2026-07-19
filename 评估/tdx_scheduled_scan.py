#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tdx_scheduled_scan.py —— 通达信5条件选股 + 候选智能评估 调度器

用途：
  1. 每个交易日 14:40 执行全市场5条件选股
  2. 对命中≥2条件的候选股跑智能评估(eval_smart)
  3. 生成报告并推送 Telegram

用法:
  python tdx_scheduled_scan.py                          # 完整流程(扫描+评估)
  python tdx_scheduled_scan.py --scan-only              # 只扫描不评估
  python tdx_scheduled_scan.py --top 10 --scan-and-eval # 评估前10候选
  python tdx_scheduled_scan.py --candidates-only        # 只输出候选代码列表

Cron 集成(每工作日 14:40):
  在 cron job 中执行: python tools/tdx_scheduled_scan.py --no-interact

注意:
  - 本脚本只做扫描+评估，不处理 Telegram 推送（由 push_mcp_report.py 处理）
  - 扫描耗时约 5-10 分钟(5000+ 只股票)
  - 评估耗时约 2-5 分钟/10只候选
"""

import argparse
import datetime
import json
import os
import sys

# ── 路径配置 ──────────────────────────────────────────
WORK_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = WORK_DIR  # 本脚本在 tools/ 下
REPORT_DIR = os.path.join(os.path.dirname(WORK_DIR), "reports", "粗评")
os.makedirs(REPORT_DIR, exist_ok=True)
sys.path.insert(0, TOOLS_DIR)


def is_trading_day() -> bool:
    """检查今天是否为交易日"""
    import tushare as ts
    pro = ts.pro_api()
    today = datetime.datetime.now().strftime("%Y%m%d")
    try:
        r = pro.trade_cal(exchange="SSE", start_date=today, end_date=today)
        if r is None or r.empty:
            return False
        return bool(r["is_open"].iloc[0] == 1)
    except Exception:
        return True  # 无法确认时默认继续


def get_last_trading_day():
    """获取最近交易日"""
    import tushare as ts
    pro = ts.pro_api()
    end_date = datetime.datetime.now().strftime("%Y%m%d")
    try:
        cal_df = pro.trade_cal(exchange="SSE",
                               start_date=(datetime.datetime.now() - datetime.timedelta(days=10)).strftime("%Y%m%d"),
                               end_date=end_date, is_open="1")
        if cal_df is not None and not cal_df.empty:
            return sorted(cal_df["cal_date"].tolist())[-1]
    except Exception:
        pass
    return end_date


def run_tdx_scan(top_n: int = 20, eval_top: int = 10, verbose: bool = True):
    """
    执行完整扫描流程：
    1. 全市场5条件选股扫描
    2. 对命中>=2条件的候选股取前N只
    3. 对前eval_top只跑智能评估

    返回: (扫描结果dict, 候选代码列表, 报告路径)
    """
    import tushare as ts
    import tdx_stockpickers as sp

    end_date = get_last_trading_day()

    if verbose:
        print(f"\n{'='*60}")
        print(f"🔍 通达信5条件选股 — 全市场批量扫描")
        print(f"📅 交易日: {end_date}")
        print(f"{'='*60}\n")

    # ── 1. 获取全市场股票列表 ─────────────────────
    pro = ts.pro_api()
    if verbose:
        print("📂 获取全市场股票列表...")
    basic = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
    total_stocks = len(basic)
    if verbose:
        print(f"  全市场上市股票: {total_stocks} 只")

    # 过滤 ST、退市
    codes_all = [r["ts_code"].split(".")[0] for _, r in basic.iterrows()
                 if "ST" not in r["name"].upper() and "退" not in r["name"]]
    ts_map = {r["ts_code"].split(".")[0]: {"ts": r["ts_code"], "name": r["name"]}
              for _, r in basic.iterrows() if "ST" not in r["name"].upper() and "退" not in r["name"]}
    if verbose:
        print(f"  过滤后候选池: {len(codes_all)} 只")

    # ── 2. 批量扫描 ──────────────────────────────
    if verbose:
        print(f"\n🔎 开始全市场扫描 {len(codes_all)} 只...")
    scan_result = sp.run_scanner(codes_all, ts_codes=ts_map, tushare_pro=pro, verbose=verbose)

    s = scan_result["summary"]
    if verbose:
        print(f"\n{'─'*40}")
        print(f"📊 扫描汇总")
        print(f"{'─'*40}")
        print(f"  扫描总数: {s['总扫描']}")
        print(f"  命中≥2条件: {s['命中>=2条件']}")
        print(f"  命中全部5条件: {s['命中全部5条件']}")
        print(f"  候选股数: {s['候选股数']}")
        for cn, cnt in s["各条件命中数"].items():
            print(f"  {cn}: {cnt}只命中")

    # ── 3. 取候选股 ──────────────────────────────
    candidates = scan_result["candidates"][:top_n]
    multi_hit = [c for c in candidates if c.get("passed_count", 0) >= 2]
    eval_codes = [c.get("code") for c in multi_hit[:eval_top]]

    if verbose:
        print(f"\n🎯 命中≥2条件候选: {len(multi_hit)} 只")
        print(f"📈 将评估前 {len(eval_codes)} 只:")
        for c in multi_hit[:eval_top]:
            print(f"  {c.get('code')} {c.get('name')} ({c.get('passed_count')}/5条件)")

    # ── 4. 生成报告 ──────────────────────────────
    now = datetime.datetime.now()
    report_name = f"通达信选股_{len(candidates)}只候选_{now.strftime('%Y%m%d_%H%M')}.md"
    report_path = os.path.join(REPORT_DIR, report_name)
    md = generate_scan_report(scan_result, candidates, top_n, now)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(md)
    if verbose:
        print(f"\n📄 选股报告已写入: {report_path}")

    # ── 5. 对候选跑智能评估 ──────────────────────
    eval_report_path = None
    if eval_codes:
        try:
            import eval_smart
            title = f"通达信选股评估_{len(eval_codes)}只_{now.strftime('%Y%m%d_%H%M')}"
            eval_smart.run_smart_eval(eval_codes, title=title, verbose=verbose)
            # 找到最新评估报告
            eval_reports = [f for f in os.listdir(REPORT_DIR)
                            if f.startswith("智能合并评估") and now.strftime("%Y%m%d") in f]
            if eval_reports:
                eval_report_path = os.path.join(REPORT_DIR, max(eval_reports))
                if verbose:
                    print(f"📈 评估报告: {eval_report_path}")
        except Exception as e:
            if verbose:
                print(f"⚠ 智能评估失败: {e}")

    if verbose:
        print(f"\n✅ 扫描+评估完成")
        print(f"   报告: {report_path}")
        if eval_report_path:
            print(f"   评估: {eval_report_path}")

    return scan_result, eval_codes, report_path, eval_report_path


def generate_scan_report(scan_result, candidates, top_n, now):
    """生成选股扫描报告"""
    s = scan_result["summary"]

    md = f"""# 🔍 通达信5条件选股报告

**扫描时间**: {now.strftime('%Y年%m月%d日 %H:%M')}  
**数据截止**: {scan_result.get('end_date', '—')}  
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

    # 候选表
    md += f"""
---

## 🎯 TOP {top_n} 候选股（按命中条件数排序）

| # | 代码 | 名称 | 命中数 | 最高分 | 命中条件 |
|---|------|------|--------|--------|----------|
"""
    for i, c in enumerate(candidates, 1):
        code = c.get("code", "?")
        name = c.get("name", "")
        conds = ", ".join(c["passed_conditions"])
        md += f"| {i} | {code} | {name} | {c['passed_count']}/5 | {c['max_score']} | {conds} |\n"

    # 多条件命中股详细
    multi = [c for c in candidates if c.get("passed_count", 0) >= 2]
    if multi:
        md += f"""
---

## 💎 重点候选：命中≥2条件的 {len(multi)} 只

| # | 代码 | 名称 | 命中条件 | 最高分 |
|---|------|------|----------|--------|
"""
        for i, c in enumerate(multi, 1):
            code = c.get("code", "?")
            name = c.get("name", "")
            conds = ", ".join(c["passed_conditions"])
            md += f"| {i} | {code} | {name} | {conds} | {c['max_score']} |\n"

        md += "\n### 条件详情\n\n"
        for c in multi[:5]:  # 前5只详情
            code = c.get("code", "?")
            name = c.get("name", "")
            md += f"\n**{code} {name}** (命中{c['passed_count']}/5)\n\n"
            md += "| 条件 | 通过 | 分数 | 说明 |\n|------|------|------|------|\n"
            for cn, cr in c["results"].items():
                flag = "✅" if cr["passed"] else "❌"
                md += f"| {cn} | {flag} | {cr['score']} | {cr['reason'][:60]} |\n"

    md += """
---

## 🔧 5条件选股公式说明

| 条件 | 选股逻辑 | 信号含义 |
|------|----------|----------|
| **20日DCZ双回踩** | 近20日≥2次回调到DCZ(中位成本)±3%并放量获支撑，现价>DCZ | 成本支撑位确认，主力护盘 |
| **四维共振主起** | 天时(大盘多头)+地利(板块ZSCORE>1.5)+人和(北向净流入)+技术(突破) | 多维共振，主升启动 |
| **金牌狙击紧** | 主力进场+A/B级+筹码集中(<30%)+量价齐升(量比>1.5) | 主力精准进场，高确定性 |
| **黄金右侧** | 突破通道上轨+MACD金叉+资金净流入 | 右侧追涨，趋势确认 |
| **黄金右侧紧** | 黄金右侧+5日涨<10%+日涨<10%（未加速） | 主升初期，右侧安全点 |

---

## ⚠️ 免责声明

本报告基于通达信主力全景公式 v3.9/V6.05 的 Python 移植实现，
为技术分析参考，**不构成投资建议**。

- 公式中 `COST` 函数用成交加权近似，与通达信实际计算存在差异
- 选股条件需结合个股基本面、市场情绪综合判断
- 所有候选股进入评估体系后仍需十维度评分确认

---

*报告生成时间: {now.strftime('%Y-%m-%d %H:%M')}*  
*选股模块: tdx_stockpickers.py v1.0*  
*数据源: tushare.pro.daily*
"""
    return md


def main():
    parser = argparse.ArgumentParser(description="通达信5条件选股调度器")
    parser.add_argument("--scan-only", action="store_true", help="只扫描不评估")
    parser.add_argument("--scan-and-eval", action="store_true", help="扫描+评估")
    parser.add_argument("--candidates-only", action="store_true", help="只输出候选代码")
    parser.add_argument("--top", type=int, default=20, help="候选股数量(默认20)")
    parser.add_argument("--eval-top", type=int, default=10, help="评估股数量(默认10)")
    parser.add_argument("--no-interact", action="store_true", help="非交互模式")
    parser.add_argument("--check-trading-day", action="store_true", help="只检查是否交易日")
    args = parser.parse_args()

    if args.check_trading_day:
        if is_trading_day():
            print("YES")
        else:
            print("NO")
        return

    # 检查交易日
    if not is_trading_day():
        print("⚠ 今天非交易日，跳过")
        sys.exit(0)

    # 执行扫描
    scan_result, eval_codes, report_path, eval_report_path = run_tdx_scan(
        top_n=args.top,
        eval_top=args.eval_top,
        verbose=not args.no_interact,
    )

    # 只输出候选代码（供外部调用）
    if args.candidates_only:
        print(json.dumps(eval_codes, ensure_ascii=False))


if __name__ == "__main__":
    main()
