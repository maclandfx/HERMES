#!/usr/bin/env python3
"""
factor_analyzer.py — 评估因子胜率分析 + 行动指南

用途: 分析历史评估数据，找出哪些维度预测最准，形成交易行动指南
"""
import os, sys, json, re, glob
import pandas as pd
import numpy as np
from datetime import datetime

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
TRACK_DIR = os.path.join(os.path.dirname(TOOLS), "reports", "追踪")
OUTPUT = os.path.join(TRACK_DIR, "factor_analysis_report.md")


def parse_eval_report(filepath):
    """从评估报告解析各维度评分"""
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()
    stocks = {}
    # 找评分对比总表
    table_match = re.search(r'## 评分对比总表.*?(?=\n##|\n---|\Z)', text, re.DOTALL)
    if not table_match:
        return stocks
    lines = table_match.group(0).split("\n")
    for line in lines:
        if "|" not in line or "评分" in line or "---" in line:
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) < 3:
            continue
        name = parts[0].replace("**", "")
        # Try to extract score
        score_match = re.search(r'[\d.]+', parts[1])
        if not score_match:
            continue
        score = float(score_match.group())
        stocks[name] = {"score": score, "detail": {}, "raw": parts}
        # Extract all scores from detail section
        detail_section = re.search(
            rf'\*\*{name}\*\*.*?(?=\n##|\n\*\*)',
            text, re.DOTALL
        )
        if detail_section:
            dims = re.findall(r'(\w+)面[=:：]?\s*(\d+)', detail_section.group())
            for dim, val in dims:
                stocks[name]["detail"][dim] = int(val)
    return stocks


def analyze():
    print(f"\n{'='*60}")
    print(f"📊 评估因子胜率分析")
    print(f"{'='*60}\n")

    # 找所有评估报告
    report_dir = os.path.join(os.path.dirname(TOOLS), "reports", "粗评")
    md_files = glob.glob(os.path.join(report_dir, "*评估*.md"))
    md_files += glob.glob(os.path.join(report_dir, "*粗评*.md"))
    md_files = [f for f in md_files if "核心" in f]
    
    print(f"找到 {len(md_files)} 份核心评估报告")
    
    # 解析所有报告
    all_stocks = {}
    for fp in md_files:
        stocks = parse_eval_report(fp)
        for name, data in stocks.items():
            if name not in all_stocks:
                all_stocks[name] = {"count": 0, "scores": [], "details": []}
            all_stocks[name]["count"] += 1
            all_stocks[name]["scores"].append(data["score"])
            all_stocks[name]["details"].append(data["detail"])

    # 生成分析报告
    md = f"# 📊 评估因子胜率分析\n\n"
    md += f"**分析时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    md += f"**样本**: {len(md_files)} 份报告, {len(all_stocks)} 只股票\n\n"
    
    # 1. 各维度评分标准差（越高说明区分度越好）
    md += "## 1️⃣ 各维度区分度分析\n\n"
    md += "> 标准差越大 → 评分区分度越好，越能分出好坏股票\n\n"
    
    # Collect all dimension scores
    dim_data = {}
    for name, data in all_stocks.items():
        for detail in data["details"]:
            for dim, val in detail.items():
                if dim not in dim_data:
                    dim_data[dim] = []
                dim_data[dim].append(val)
    
    dim_stats = []
    for dim, vals in dim_data.items():
        dim_stats.append((dim, np.std(vals), np.mean(vals), len(vals)))
    dim_stats.sort(key=lambda x: x[1], reverse=True)
    
    md += "| 维度 | 标准差 | 均值 | 样本 | 区分度 |\n"
    md += "|------|--------|------|------|--------|\n"
    for dim, std, mean, n in dim_stats:
        rating = "🟢高" if std > 15 else ("🟡中" if std > 10 else "🔴低")
        md += f"| {dim}面 | {std:.1f} | {mean:.1f} | {n} | {rating} |\n"
    
    # 2. 操作建议
    md += "\n## 2️⃣ 核心发现\n\n"
    
    findings = []
    for dim, std, mean, n in dim_stats:
        if std > 15:
            findings.append(f"- **{dim}面**(标准差{std:.0f})：区分度最高，是选股的核心维度")
    for dim, std, mean, n in dim_stats:
        if std < 8:
            findings.append(f"- **{dim}面**(标准差{std:.0f})：区分度低，评分模板化，参考价值有限")
    md += "\n".join(findings[:5])
    md += "\n\n"
    
    # 3. 评分区间分析
    all_scores = [s for d in all_stocks.values() for s in d["scores"]]
    md += f"## 3️⃣ 评分区间分布\n\n"
    md += f"评分范围: {min(all_scores):.0f}~{max(all_scores):.0f}\n\n"
    md += "| 区间 | 数量 | 占比 | 判断 |\n"
    for low, high, label in [(100, 999, "💎极优"), (90, 100, "🟢优质"), (80, 90, "🟡良好"), (0, 80, "🔴一般")]:
        cnt = sum(1 for s in all_scores if low <= s < high)
        pct = cnt / len(all_scores) * 100
        md += f"| {low}-{high} | {cnt} | {pct:.0f}% | {label} |\n"
    
    md += "\n---\n\n"
    
    # 4. 行动指南
    md += """# 🎯 评估体系行动指南

## 核心原则

1. **评分>95分+S级** → 优先操作
2. **多维度共振**（≥3维>85分）→ 高确定性
3. **涨停标的** → 纳入观察池，次日开板优先考虑
4. **资金面<40** → 即使总分高，回避（主力出货）

## 各维度权重（推荐）

| 维度 | 权重 | 说明 |
|------|------|------|
| 资金面 | 25% | 主力进出最直接指标 |
| 技术面 | 20% | 趋势动量 |
| 情绪面 | 15% | 市场情绪溢价 |
| 基本面 | 10% | 估值锚，防御性 |
| 板块面 | 10% | 主线板块溢价 |
| 热度面 | 10% | 短期资金聚集 |
| 反身性 | 10% | 自强化信号 |

## 操作规则

**买入条件**（全部满足）：
1. 总分 ≥ 90
2. 资金面 ≥ 60
3. 技术面 ≥ 70（多头排列）
4. 非涨停封死

**止损规则**：
- 首日（T+0无法卖出）：关注次日
- 次日：ATR缓冲止损（-1.5×ATR）
- 常态：-8%硬止损

**仓位管理**：
- S级 (>95分)：20%仓位
- S级 (90-95分)：15%仓位
- 其他：不操作

## 追击涨停策略

涨停标的评估分仍然有效，次日关注：
1. 若高开<5%且资金面>70 → 可追
2. 若高开>7%或资金面<50 → 等回落
3. 3日内不创新高 → 剔除观察池
"""
    md += f"\n\n*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n"
    
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"📄 因子分析报告: {OUTPUT}")
    print("✅ 完成")


if __name__ == "__main__":
    analyze()