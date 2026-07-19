#!/usr/bin/env python3
"""
factor_calibrator.py — 自适应权重校准器

核心逻辑：
- 滚动N日：每个因子与后续收益的相关性 = 当前权重
- 权重 = softmax(相关系数 × 衰减因子)
- 低置信度（样本不足）因子自动降权
"""
import os, sys, json, datetime, math
import numpy as np
from collections import defaultdict

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)

FACTOR_DIR = os.path.join(os.path.dirname(TOOLS), "reports", "追踪")
WEIGHT_FILE = os.path.join(FACTOR_DIR, "factor_weights.json")
HISTORY_FILE = os.path.join(FACTOR_DIR, "track_history.csv")


def load_weights():
    """加载既有权重，没有就返回默认"""
    if os.path.exists(WEIGHT_FILE):
        with open(WEIGHT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return get_default_weights()


def get_default_weights():
    """默认权重（主观先验）"""
    return {
        # A组 资金流
        "A1_big_net_ratio": {"weight": 15, "confidence": 0.5, "description": "大单净流入比"},
        "A2_consecutive_days": {"weight": 12, "confidence": 0.5, "description": "资金持续天数"},
        "A3_strength": {"weight": 13, "confidence": 0.5, "description": "主力资金强度"},
        "A4_north_flow": {"weight": 10, "confidence": 0.3, "description": "北向资金变化"},
        # B组 量价
        "B1_divergence": {"weight": 8, "confidence": 0.4, "description": "量价背离信号"},
        "B2_limit_quality": {"weight": 5, "confidence": 0.3, "description": "涨停封板质量"},
        "B3_gap": {"weight": 8, "confidence": 0.4, "description": "跳空缺口"},
        "B4_rel_strength": {"weight": 10, "confidence": 0.5, "description": "相对强弱(超额收益)"},
        "B5_trend": {"weight": 8, "confidence": 0.4, "description": "趋势强度"},
        # C组 情绪
        "C_market_up_ratio": {"weight": 3, "confidence": 0.2, "description": "市场涨跌比"},
        "C_limit_up_count": {"weight": 3, "confidence": 0.2, "description": "涨停家数"},
        # F组 日历
        "F1_is_monday": {"weight": 1, "confidence": 0.1, "description": "周一股市效应"},
        "F1_is_friday": {"weight": 1, "confidence": 0.1, "description": "周五效应"},
        "F1_is_thursday": {"weight": 1, "confidence": 0.1, "description": "周四效应"},
        "F2_is_month_end": {"weight": 1, "confidence": 0.1, "description": "月末效应"},
        "F3_is_earnings_season": {"weight": 2, "confidence": 0.1, "description": "业绩窗口"},
    }


def calibrate(history_df, factor_data_history, window=20):
    """
    用滚动窗口校准权重
    输入：history_df (date, code, pct_chg), factor_data_history [{date: {code: {factors}}}]
    输出：新权重 dict
    """
    weights = load_weights()

    # 对每个因子：计算最近window天内，因子值与次日收益的相关系数
    factor_corrs = defaultdict(list)

    # 遍历历史日期
    dates = sorted(history_df["date"].unique()) if not history_df.empty else []
    if len(dates) < 5:
        print(f"⚠️ 历史数据不足({len(dates)}天)，使用默认权重")
        return weights

    recent_dates = dates[-window:] if len(dates) > window else dates

    for d in recent_dates:
        day_data = history_df[history_df["date"] == d]
        if day_data.empty:
            continue
        # 找次日收益
        d_idx = dates.index(d)
        if d_idx + 1 >= len(dates):
            continue
        next_d = dates[d_idx + 1]
        next_data = history_df[history_df["date"] == next_d]
        if next_data.empty:
            continue

        # 对每只股票
        for _, row in day_data.iterrows():
            code = row["code"]
            if "." not in code:
                code_with_mkt = code + ".SH" if code[0] in "69" else code + ".SZ"
            else:
                code_with_mkt = code

            # 找该日的因子值
            factor_key = f"{d}_{code}"
            f_data = factor_data_history.get(factor_key, {})
            if not f_data:
                continue

            # 找次日收益率
            next_row = next_data[next_data["code"] == code]
            if next_row.empty:
                continue
            next_ret = next_row.iloc[0]["pct_chg"]

            # 计算每个因子与收益的关系
            for factor_name, f_val in f_data.items():
                if isinstance(f_val, (int, float)):
                    factor_corrs[factor_name].append((f_val, next_ret))

    # 计算Spearman秩相关
    for f_name, pairs in factor_corrs.items():
        if len(pairs) < 5:
            continue
        vals, rets = zip(*pairs)
        if np.std(vals) == 0 or np.std(rets) == 0:
            corr = 0
        else:
            corr = np.corrcoef(vals, rets)[0, 1]
        if np.isnan(corr):
            corr = 0

        # 更新权重：权重 = 基础权重 × (1 + corr)
        # corr > 0 说明预测方向正确，提高权重
        # corr < 0 说明该因子反向，降低甚至取反
        base = weights.get(f_name, {"weight": 5, "confidence": 0.3})
        new_weight = base["weight"] * (1 + corr)
        new_confidence = min(0.9, base["confidence"] + abs(corr) * 0.1)
        weights[f_name] = {
            "weight": round(new_weight, 1),
            "confidence": round(new_confidence, 2),
            "description": base["description"],
            "correlation": round(corr, 3),
            "samples": len(pairs),
        }

    # 归一化：确保权重总和 ≈ 100
    total = sum(v["weight"] for v in weights.values())
    if total > 0:
        for k in weights:
            weights[k]["weight"] = round(weights[k]["weight"] / total * 100, 1)

    return weights


def save_weights(weights):
    with open(WEIGHT_FILE, "w", encoding="utf-8") as f:
        json.dump(weights, f, ensure_ascii=False, indent=2)
    print(f"✅ 权重已保存: {WEIGHT_FILE}")


def run():
    import pandas as pd
    print(f"\n{'='*60}")
    print(f"⚖️ 自适应权重校准器")
    print(f"{'='*60}\n")

    # 加载历史数据
    hist_df = pd.read_csv(HISTORY_FILE) if os.path.exists(HISTORY_FILE) else pd.DataFrame()
    print(f"  历史追踪: {len(hist_df)} 条")

    # 加载因子历史
    factor_hist_path = os.path.join(FACTOR_DIR, "factors_raw.json")
    factor_hist = {}
    if os.path.exists(factor_hist_path):
        with open(factor_hist_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        for code, factors in raw.items():
            if "error" not in factors:
                factor_hist[f"_{code}"] = factors

    # 校准
    weights = calibrate(hist_df, factor_hist)
    save_weights(weights)

    # 输出排行榜
    sorted_w = sorted(weights.items(), key=lambda x: x[1]["weight"], reverse=True)
    print("\n📊 当前因子权重排名：")
    print(f"{'因子':<25} | {'权重':>6} | {'置信度':>6} | {'相关性':>7} | {'说明'}")
    print("-"*80)
    for k, v in sorted_w:
        corr = f"{v.get('correlation', 0):+.3f}" if "correlation" in v else "N/A"
        print(f"{k:<25} | {v['weight']:>5.1f}% | {v['confidence']:.2f} | {corr:>7} | {v['description']}")

    print(f"\n✅ 校准完成")


if __name__ == "__main__":
    run()