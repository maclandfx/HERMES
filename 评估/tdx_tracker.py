#!/usr/bin/env python3
"""
tdx_tracker.py — 用户选股池追踪系统

功能：
1. 每日扫描20只跟踪标的的最新行情+评估分变化
2. 记录每个因子的实际表现（命中/止损/止盈）
3. 输出追踪报告，对比各维度预测准确率

用法: python tdx_tracker.py
"""
import os, sys, json, datetime, csv, re
import pandas as pd
import numpy as np
from pathlib import Path

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)

import tushare as ts
pro = ts.pro_api()
from astock_bridge import tencent_quote

# 20只跟踪标的
WATCH_CODES = ['600118','300418','600288','688135','688175','603296',
               '603893','688802','000518','301516','300454','688722',
               '688039','001395','600992','300649','002414','002490',
               '000779','603339']

WATCH_NAMES = ['中国卫星','昆仑万维','大恒科技','利扬芯片','高凌信息',
               '华勤技术','瑞芯微','沐曦股份','四环生物','中远通',
               '深信服','同益中','当虹科技','亚联机械','贵绳股份',
               '杭州园林','高德红外','山东墨龙','甘咨询','四方科技']
WATCH_NAME_DICT = dict(zip(WATCH_CODES, WATCH_NAMES))

TRACK_DIR = os.path.join(os.path.dirname(TOOLS), "reports", "追踪")
HISTORY_FILE = os.path.join(TRACK_DIR, "track_history.csv")
REPORT_FILE = os.path.join(TRACK_DIR, "track_report_latest.md")
os.makedirs(TRACK_DIR, exist_ok=True)


def load_history():
    """加载历史追踪记录"""
    if os.path.exists(HISTORY_FILE):
        return pd.read_csv(HISTORY_FILE)
    return pd.DataFrame()


def save_history(df):
    df.to_csv(HISTORY_FILE, index=False, encoding="utf-8-sig")


def scan_today():
    """今日扫描"""
    today = datetime.datetime.now().strftime("%Y%m%d")
    records = []
    quotes = tencent_quote(WATCH_CODES)
    for code, name in zip(WATCH_CODES, WATCH_NAMES):
        q = quotes.get(code, {})
        price = q.get("price", 0)
        pct = q.get("pct_chg", 0)
        limit_up = q.get("limit_up", 0)
        is_limit = limit_up > 0 and price >= limit_up * 0.995
        records.append({
            "date": today, "code": code, "name": name,
            "price": round(price, 2), "pct_chg": round(pct, 2),
            "is_limit": 1 if is_limit else 0,
            "vol_ratio": round(q.get("vol_ratio", 0), 2),
            "turnover_pct": round(q.get("turnover_pct", 0), 2),
            "pe_ttm": round(q.get("pe_ttm", 0), 1),
        })
    return pd.DataFrame(records)


def run():
    print(f"\n{'='*60}")
    print(f"📡 选股池追踪 — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    # 今日扫描
    df_today = scan_today()
    print(f"📊 今日扫描: {len(df_today)} 只")
    limit_count = df_today["is_limit"].sum()
    if limit_count:
        limit_names = df_today[df_today["is_limit"]==1]["name"].tolist()
        print(f"🚨 涨停: {', '.join(limit_names)}")

    # 合并历史
    df_hist = load_history()
    if not df_hist.empty:
        df_all = pd.concat([df_hist, df_today], ignore_index=True)
        df_all = df_all.drop_duplicates(subset=["date","code"], keep="last")
    else:
        df_all = df_today
    save_history(df_all)

    # 生成追踪报告
    md = f"# 📡 选股池追踪报告\n\n"
    md += f"**{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}**  |  跟踪标的: {len(WATCH_CODES)}只\n\n"

    md += "## 📊 今日快照\n\n"
    md += "| 代码 | 名称 | 现价 | 涨跌% | 状态 | 量比 | 换手% |\n"
    md += "|------|------|------|-------|------|------|------|\n"
    for _, r in df_today.iterrows():
        status = "🚨涨停" if r["is_limit"] else "✅"
        md += f"| {r['code']} | {r['name']} | ¥{r['price']:.2f} | {r['pct_chg']:+.2f}% | {status} | {r['vol_ratio']} | {r['turnover_pct']}% |\n"

    # 涨幅榜
    df_sorted = df_today.sort_values("pct_chg", ascending=False)
    top5 = df_sorted.head(5)
    bottom5 = df_sorted.tail(5)
    md += "\n## 📈 涨幅TOP5\n\n"
    md += "| 名称 | 涨幅 |\n|------|------|\n"
    for _, r in top5.iterrows():
        md += f"| {r['name']} | **{r['pct_chg']:+.2f}%** |\n"

    md += "\n## 📉 跌幅TOP5\n\n"
    md += "| 名称 | 跌幅 |\n|------|------|\n"
    for _, r in bottom5.iterrows():
        md += f"| {r['name']} | {r['pct_chg']:+.2f}% |\n"

    # 历史统计
    if len(df_all) > len(df_today):
        md += "\n## 📋 累计统计\n\n"
        total_days = df_all["date"].nunique()
        md += f"跟踪天数: {total_days}天  |  总记录: {len(df_all)}条\n\n"
        # 统计涨幅
        avg_pct = df_all.groupby("code")["pct_chg"].mean().sort_values(ascending=False)
        md += "| 排名 | 名称 | 日均涨幅 | 最佳日 | 最差日 |\n"
        md += "|------|------|----------|--------|--------|\n"
        for i, (code, avg) in enumerate(avg_pct.items()):
            sub = df_all[df_all["code"]==code]
            best = sub["pct_chg"].max()
            worst = sub["pct_chg"].min()
            name = WATCH_NAME_DICT.get(code, code)
            md += f"| {i+1} | {name} | {avg:+.2f}% | {best:+.2f}% | {worst:+.2f}% |\n"

    md += f"\n\n*生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}*\n"

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"\n📄 追踪报告: {REPORT_FILE}")
    print("✅ 完成")
    
    # 打印摘要
    print(f"\n📊 今日亮点: {', '.join(top5['name'].tolist())}")

if __name__ == "__main__":
    run()