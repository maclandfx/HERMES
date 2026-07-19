#!/usr/bin/env python3
"""生成测试推送报告"""
import os, sys, json, datetime, re

TOOLS = r"D:\Hermes\评估中心\tools"
sys.path.insert(0, TOOLS)

OUT = r"C:\Users\Admin\AppData\Local\hermes\scripts\_td_payload.txt"
PUSH = r"C:\Users\Admin\AppData\Local\hermes\scripts\push_mcp_report.py"

# 读取因子报告数据
with open(r"D:\Hermes\评估中心\reports\追踪\factors_raw.json", "r", encoding="utf-8") as f:
    factors = json.load(f)

watch_names = {
    "600118":"中国卫星","300418":"昆仑万维","600288":"大恒科技",
    "688135":"利扬芯片","688175":"高凌信息","603296":"华勤技术",
    "603893":"瑞芯微","688802":"沐曦股份","000518":"四环生物",
    "301516":"中远通","300454":"深信服","688722":"同益中",
    "688039":"当虹科技","001395":"亚联机械","600992":"贵绳股份",
    "300649":"杭州园林","002414":"高德红外","002490":"山东墨龙",
    "000779":"甘咨询","603339":"四方科技",
}

# 计算综合分（用默认权重）
weights = {"A1_big_net_ratio":15,"A3_strength":13,"A2_consecutive_days":12,
           "A4_north_flow":10,"B4_rel_strength":10,"B1_divergence":8,
           "B3_gap":8,"B5_trend":8,"B2_limit_quality":5}

scores = []
for code, f in factors.items():
    if "error" in f: continue
    total = sum(f.get(k,50)*w for k,w in weights.items()) / sum(weights.values())
    scores.append((code, round(total,1), f))

scores.sort(key=lambda x: x[1], reverse=True)
now = datetime.datetime.now().strftime("%m月%d日 %H:%M")

# 构建推送文本（≤3900字符）
lines = [
    f"# 📊 因子引擎日报 — 测试推送",
    f"**{now}** | 标的20只 | 因子16个",
    "",
    f"## 🏆 TOP 10",
    "",
    "| # | 名称 | 综合分 | 主力因子 |",
    "|---|------|:------:|----------|",
]

for i, (code, total, f_dict) in enumerate(scores[:10]):
    name = watch_names.get(code, code)
    # 找到分最高的因子
    top = sorted(f_dict.items(), key=lambda x: x[1] if isinstance(x[1],(int,float)) else 0, reverse=True)[:2]
    top_str = ", ".join([f"{k}({v:.0f})" for k,v in top if isinstance(v,(int,float))])
    # 涨停标记
    is_limit = any(v > 95 for k,v in top if isinstance(v,(int,float)) and k in ["A3_strength","B4_rel_strength"])
    flag = "🚨" if total > 55 else ""
    lines.append(f"| {i+1} | {flag}{name} | {total} | {top_str} |")

lines += [
    "",
    f"## ⚖️ 权重排名",
    "",
    "| 因子 | 权重 | 说明 |",
    "|------|:----:|------|",
    "| A1大单净流入比 | 15% | 🥇最核心 |",
    "| A3主力资金强度 | 13% | 质量过滤 |",
    "| A2资金持续性 | 12% | 非一日游 |",
    "| A4北向变化 | 10% | 聪明钱 |",
    "| B4相对强弱 | 10% | α收益 |",
    "| B1量价背离 | 8% | 真假突破 |",
    "| B3跳空缺口 | 8% | 缺口质量 |",
    "| B5趋势强度 | 8% | 动量 |",
    "| B2涨停质量 | 5% | 封板力度 |",
    "",
    "## 🎯 行动指南",
    "",
    "**买入条件**: 评估≥95分 + 资金面≥70 + 非涨停封死",
    "**止损**: 常态-8%硬止损 | 首日T+0关注次日",
    "**仓位**: 20%(≥100分) / 15%(≥95分) / 不操作(其他)",
    "**追击涨停**: 开板+资金面>70→开盘追；3日不创新高→剔除",
    "",
    f"— 测试推送 | 自适应权重满5天自动调权 —",
]

text = "\n".join(lines)
# 截断
if len(text) > 3900:
    text = text[:3850] + "\n\n... (截断)"

with open(OUT, "w", encoding="utf-8") as f:
    f.write(text)

print(f"Payload: {len(text)} chars")

# 调用推送
import subprocess
r = subprocess.run(
    f'"{sys.executable}" {PUSH}',
    shell=True, capture_output=True, text=True, encoding="utf-8", timeout=30
)
print(f"Exit: {r.returncode}")
print(r.stdout[-500:] if r.stdout else "")
if r.stderr:
    print(f"STDERR: {r.stderr[:200]}")