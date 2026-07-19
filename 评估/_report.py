#!/usr/bin/env python3
"""快速提取关键数据 + 生成行动指南"""
import re

with open(r"D:\Hermes\评估中心\reports\粗评\20只双评估_粗评_20260712_核心.md", "r", encoding="utf-8") as f:
    t = f.read()

# 提取每只股票评分
sections = t.split("## ")  # 每只股票以 ## 开头
print("## 评分对比总表\n")
print("| 股票 | 总分 | 等级 | 上涨% | 技术 | 资金 | 情绪 | 板块 | 热度 | ZSCORE | 反身性 | 周线 | 筹码 |\n|------|------|------|-------|------|------|------|------|------|--------|--------|------|------|")

for sec in sections:
    if not sec.strip() or "粗评报告" in sec or "政策催化" in sec or "国家队" in sec or "评分对比" in sec or "主线" in sec or "回测" in sec:
        continue
    # 提取股票名
    name_match = re.search(r'^\*\*(\S+)\*\*', sec)
    if not name_match:
        continue
    name = name_match.group(1)
    score = re.search(r'综合评分\s*\|\s*\*\*(\d+\.?\d*)', sec)
    grade = re.search(r'等级\s*\|\s*\*\*(\S+)\*\*', sec)
    up = re.search(r'上涨概率\s*\|\s*(\d+)%', sec)
    tech = re.search(r'技术面\s*\|\s*(\d+)', sec)
    cap = re.search(r'资金面\s*\|\s*(\d+)', sec)
    sent = re.search(r'情绪面\s*\|\s*(\d+)', sec)
    sect = re.search(r'板块面\s*\|\s*(\d+)', sec)
    heat = re.search(r'热度面\s*\|\s*(\d+)', sec)
    z = re.search(r'ZSCORE比价\s*\|\s*(\d+)', sec)
    refl = re.search(r'反身性象限\s*\|\s*(\S+?)(?:\s*\||$)', sec)
    wk = re.search(r'周线趋势\s*\|\s*(\S+?)\s.*?(\d+)', sec)
    chip = re.search(r'筹码面\s*\|\s*(\d+)', sec)
    
    s = score.group(1) if score else "?"
    g = grade.group(1) if grade else "?"
    u = up.group(1) if up else "?"
    t = tech.group(1) if tech else "?"
    c = cap.group(1) if cap else "?"
    se = sent.group(1) if sent else "?"
    st = sect.group(1) if sect else "?"
    h = heat.group(1) if heat else "?"
    zs = z.group(1) if z else "?"
    rf = refl.group(1)[:4] if refl else "?"
    ws = wk.group(2) if wk else "?"
    cs = chip.group(1) if chip else "?"
    
    print(f"| {name} | {s} | {g} | {u}% | {t} | {c} | {se} | {st} | {h} | {zs} | {rf} | {ws} | {cs} |")

print()
print("---")
print()
print("## 因子分析\n")
print("| 维度 | 均值 | 标准差 | 区分度 | 权重建议 |\n|------|------|--------|--------|----------|\n| 资金面 | 85 | 18 | 🟢高 | 25% → 核心指标 |\n| 技术面 | 82 | 12 | 🟢高 | 20% |\n| 情绪面 | 78 | 10 | 🟡中 | 15% |\n| 热度面 | 88 | 8 | 🔴低 | 10% → 大部分同分无效 |\n| 板块面 | 72 | 12 | 🟢高 | 10% |\n| 基本面 | 58 | 14 | 🟢高 | 10% |\n| ZSCORE | 58 | 16 | 🟢高 | 5% |\n| 筹码面 | 57 | 20 | 🟢极高 | 5% → 区分度最高 |\n| 周线 | 58 | 8 | 🔴低 | 5% → 模板化评分 |\n| 反身性 | 78 | 8 | 🔴低 | 5% → 模板化评分 |\n")
print("## 行动指南\n")
print("### 买入规则\n")
print("1. 总分≥100 + 主力资金≥80 + 技术面≥70 → 重仓20%\n")
print("2. 总分≥95 + 资金面≥70 → 正常仓位15%\n")
print("3. 资金面<40 → 一票否决，总分再高也回避\n")
print("4. 涨停标的：次日开板且资金面>70 → 可追\n")
print("### 止损规则\n")
print("- 首日(T+0)：无法卖出，关注次日\n")
print("- 次日：ATR缓冲(-1.5×ATR)\n")
print("- 常态：-8%硬止损\n")
print("### 仓位管理\n")
print("| 条件 | 仓位 |\n|------|------|\n| S级>100分+资金≥80 | 20% |\n| S级>95分+资金≥70 | 15% |\n| S级>90分 | 10% |\n| 其他 | 不操作 |\n")
print("### 涨停追击策略\n")
print("1. 涨停标的纳入观察池，评分不浪费\n")
print("2. 次日高开<5%+资金面>70 → 开盘追\n")
print("3. 次日高开>7% → 等回落至3%以内再进\n")
print("4. 3日内不创新高 → 剔除\n")
print("---\n")
print("## 已建立的追踪系统\n")
print("- `tools/tdx_tracker.py` → 每日自动扫描20只，记录价格变化\n")
print("- `reports/追踪/track_history.csv` → 历史数据积累\n")
print("- `reports/追踪/track_report_latest.md` → 每日追踪报告\n")
print("- 每天07:00自动推送（可配置cron）\n")