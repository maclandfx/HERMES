#!/usr/bin/env python3
"""
factor_reporter.py — 因子日报
综合: 因子引擎得分 + 自适应权重 → 综合评分 + 行动建议
"""
import os, sys, json, datetime

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)

FACTOR_DIR = os.path.join(os.path.dirname(TOOLS), "reports", "追踪")
FACTOR_DATA = os.path.join(FACTOR_DIR, "factors_raw.json")
WEIGHT_FILE = os.path.join(FACTOR_DIR, "factor_weights.json")
REPORT_FILE = os.path.join(FACTOR_DIR, "factor_report_daily.md")

WATCH_NAMES = {
    "600118": "中国卫星", "300418": "昆仑万维", "600288": "大恒科技",
    "688135": "利扬芯片", "688175": "高凌信息", "603296": "华勤技术",
    "603893": "瑞芯微", "688802": "沐曦股份", "000518": "四环生物",
    "301516": "中远通", "300454": "深信服", "688722": "同益中",
    "688039": "当虹科技", "001395": "亚联机械", "600992": "贵绳股份",
    "300649": "杭州园林", "002414": "高德红外", "002490": "山东墨龙",
    "000779": "甘咨询", "603339": "四方科技",
}


def load_data():
    with open(FACTOR_DATA, "r", encoding="utf-8") as f:
        factors = json.load(f)
    if os.path.exists(WEIGHT_FILE):
        with open(WEIGHT_FILE, "r", encoding="utf-8") as f:
            weights = json.load(f)
    else:
        weights = {}
    return factors, weights


def compute_composite(factors, weights):
    """加权综合评分"""
    scores = {}
    for code, f_dict in factors.items():
        if "error" in f_dict:
            scores[code] = {"error": f_dict["error"], "total": 0}
            continue
        total = 0
        weight_sum = 0
        details = {}
        for f_name, f_val in f_dict.items():
            w = weights.get(f_name, {}).get("weight", 0)
            total += f_val * w
            weight_sum += w
            details[f_name] = {"value": f_val, "weight": w}
        total = total / weight_sum if weight_sum > 0 else 0
        scores[code] = {"total": round(total, 1), "details": details}
    return scores


def run():
    print(f"\n{'='*60}")
    print(f"📊 因子日报 — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    factors, weights = load_data()
    scores = compute_composite(factors, weights)

    # 排序
    sorted_scores = sorted(scores.items(), key=lambda x: x[1]["total"], reverse=True)

    # 生成报告
    md = f"# 📊 因子引擎日报\n\n"
    md += f"**{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}**  |  因子数: {len(weights)}  |  标的: {len(scores)}只\n\n"

    # 综合排名
    md += "## 🏆 综合因子排名\n\n"
    md += "| 排名 | 代码 | 名称 | 综合分 | 核心因子 |\n"
    md += "|------|------|------|--------|----------|\n"
    for i, (code, s) in enumerate(sorted_scores):
        if "error" in s:
            continue
        name = WATCH_NAMES.get(code, code)
        # 找前3大贡献因子
        top3 = sorted(s["details"].items(), key=lambda x: x[1]["value"] * x[1]["weight"], reverse=True)[:3]
        top3_str = ", ".join([f"{k}({v['value']})" for k, v in top3])
        md += f"| {i+1} | {code} | {name} | **{s['total']:.0f}** | {top3_str} |\n"

    # 权重排名
    md += "\n## ⚖️ 当前因子权重\n\n"
    md += "| 排名 | 因子 | 权重 | 置信度 | 近20日相关性 | 说明 |\n"
    md += "|------|------|------|--------|-------------|------|\n"
    sorted_w = sorted(weights.items(), key=lambda x: x[1]["weight"], reverse=True)
    for i, (k, v) in enumerate(sorted_w):
        corr = f"{v.get('correlation', 0):+.3f}" if "correlation" in v else "N/A"
        md += f"| {i+1} | {k} | {v['weight']:.1f}% | {v['confidence']:.2f} | {corr} | {v['description']} |\n"

    # 各因子详细得分
    md += "\n## 🔍 各因子详细得分\n\n"
    md += "| 股票 | 综合 |"
    f_names = sorted(weights.keys(), key=lambda k: weights[k]["weight"], reverse=True)
    for f in f_names:
        md += f" {f} |"
    md += "\n|------|------|"
    for f in f_names:
        md += "------|"
    md += "\n"

    for code, s in sorted_scores:
        if "error" in s:
            continue
        name = WATCH_NAMES.get(code, code)
        md += f"| {code} {name} | {s['total']:.0f} |"
        for f in f_names:
            val = s["details"].get(f, {}).get("value", "—")
            md += f" {val} |"
        md += "\n"

    md += f"\n\n*生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}*\n"
    md += "*因子引擎 v1 — 自适应权重滚动校准*\n"

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"📄 因子日报: {REPORT_FILE}")

    # 打印摘要
    print("\n📊 TOP 5:")
    for i, (code, s) in enumerate(sorted_scores[:5]):
        if "error" not in s:
            name = WATCH_NAMES.get(code, code)
            print(f"  {i+1}. {name} {s['total']:.0f}分")
    print("✅ 完成")


if __name__ == "__main__":
    run()