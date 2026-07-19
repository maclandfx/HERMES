#!/usr/bin/env python3
"""Extract stock data from report"""
import re

with open(r"D:\Hermes\评估中心\reports\粗评\20只双评估_粗评_20260712_核心.md", "r", encoding="utf-8") as f:
    t = f.read()

blocks = t.split("\n## **")
stocks = []
for block in blocks[1:]:
    name = block.split("**")[0].strip()
    score = re.search(r"综合评分\s*\|\s*\*\*([\d.]+)", block)
    grade = re.search(r"等级\s*\|\s*\*\*(S|A|B|C)", block)
    up = re.search(r"上涨概率\s*\|\s*(\d+)%", block)
    tech = re.search(r"技术面\s*\|\s*(\d+)", block)
    cap = re.search(r"资金面\s*\|\s*(\d+)", block)
    sent = re.search(r"情绪面\s*\|\s*(\d+)", block)
    sect = re.search(r"板块面\s*\|\s*(\d+)", block)
    heat = re.search(r"热度面\s*\|\s*(\d+)", block)
    z = re.search(r"ZSCORE比价\s*\|\s*(\d+)", block)
    refl = re.search(r"反身性象限\s*\|\s*(\S+)", block)
    chip = re.search(r"筹码面\s*\|\s*(\d+)", block)
    wk = re.search(r"周线趋势\s*\|\s*(\S+?)\s.*?(\d+)", block)
    stocks.append({
        "n": name, "s": score.group(1) if score else "0",
        "g": grade.group(1) if grade else "?", "u": up.group(1) if up else "0",
        "t": tech.group(1) if tech else "0", "c": cap.group(1) if cap else "0",
        "e": sent.group(1) if sent else "0", "ct": sect.group(1) if sect else "0",
        "h": heat.group(1) if heat else "0", "z": z.group(1) if z else "0",
        "r": refl.group(1)[:4] if refl else "?", "cp": chip.group(1) if chip else "?",
        "w": wk.group(2) if wk else "?",
    })

stocks.sort(key=lambda x: float(x["s"]), reverse=True)

print("| 排名 | 股票 | 总分 | 等级 | 上涨% | 技术 | 资金 | 情绪 | 板块 | 热度 | ZSCORE | 筹码 | 周线 | 反身性 |")
print("|------|------|------|------|-------|------|------|------|------|------|--------|------|------|--------|")
for i, s in enumerate(stocks):
    zf = s["z"] if s["z"] != "0" else ""
    cf = s["cp"] if s["cp"] != "?" else ""
    wf = s["w"] if s["w"] != "?" else ""
    print(f"| {i+1} | {s['n']} | {s['s']} | {s['g']} | {s['u']}% | {s['t']} | {s['c']} | {s['e']} | {s['ct']} | {s['h']} | {zf} | {cf} | {wf} | {s['r']} |")