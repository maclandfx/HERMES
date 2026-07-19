"""周线技术分析模块 — 为评估报告追加中长期评估层

【评分维度】(总分100)
- 周线均线 (max 45): 多头排列 + 站上5周线
- 周线位置 (max 35): 当前价在12周区间的相对位置
- 周线量能 (max 20): 本周量与前一周比
- 周线MACD (max 55): DIF/DEA方向/红柱/金叉死叉
- 趋势形态 (max 15): 近4周上涨周数

数据源: tushare pro.weekly (周K数据)
当日实时: tushare pro.daily (最近交易日)

日/周对照：每周线结论后追加当日实时价格 vs 周线收盘的偏差提示
"""

import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Any, List

import tushare as ts

_TS_TOKEN = os.environ.get("TUSHARE_TOKEN", "3de9976db504a798ec235a8cfaa5292ba7b5cb7f20957d6929e04287")
ts.set_token(_TS_TOKEN)
pro = ts.pro_api()


def load_weekly(code: str, lookback_weeks: int = 60, end_date: str = None) -> pd.DataFrame:
    """加载周K数据 — 默认60周(~14个月)。

    返回 DataFrame 列: ts_code / trade_date / close / open / high / low /
    pre_close / change / pct_chg / vol / amount
    """
    if end_date is None:
        end_date = datetime.now().strftime('%Y%m%d')

    start_date = (datetime.strptime(end_date, '%Y%m%d') - timedelta(weeks=lookback_weeks + 4)).strftime('%Y%m%d')

    try:
        df = pro.weekly(ts_code=code, start_date=start_date, end_date=end_date)
        if df is None or df.empty:
            return pd.DataFrame()
        # tushare 默认按 trade_date 倒序(从最新到最早)
        return df.sort_values('trade_date', ascending=False).reset_index(drop=True)
    except Exception as e:
        print(f"  ⚠ 周线数据加载失败 ({code}): {e}")
        return pd.DataFrame()


def load_latest_daily(code: str) -> Dict[str, Any]:
    """加载最近交易日实时价格 — 用于日/周对照"""
    try:
        df = pro.daily(ts_code=code, start_date=None, end_date=None)
        if df is None or df.empty:
            return None
        df = df.sort_values('trade_date', ascending=False).reset_index(drop=True)
        row = df.iloc[0]
        return {
            'trade_date': row.get('trade_date'),
            'close': float(row.get('close', 0)),
            'open': float(row.get('open', 0)),
            'pct_chg': float(row.get('pct_chg', 0)),
        }
    except Exception as e:
        print(f"  ⚠ 日线数据加载失败 ({code}): {e}")
        return None


def calc_daily_vs_weekly_alignment(daily: Dict[str, Any], weekly_close: float, weekly_pct: float) -> Dict[str, Any]:
    """日线 vs 周线一致性检查 — 如果当日价格大幅偏离周线收盘，提示风险"""
    if daily is None:
        return {'status': '⚠️ 无日线数据', 'detail': ''}
    
    daily_close = daily['close']
    daily_pct = daily['pct_chg']
    deviation = (daily_close - weekly_close) / weekly_close * 100 if weekly_close > 0 else 0
    
    # 判断方向一致性
    same_direction = (deviation > 0 and weekly_pct > 0) or (deviation < 0 and weekly_pct < 0)
    
    if abs(deviation) > 5:
        if same_direction:
            status = '🟢 日周同向放大'
        else:
            status = '🔴 日周背离（日线反向，需警惕）'
    elif abs(deviation) > 2:
        if same_direction:
            status = '🟢 日周同向'
        else:
            status = '🟡 日周轻微背离（日线反向）'
    else:
        status = '🟢 日周一致'
    
    detail = (
        f"当日收盘{daily_close:.2f}元("
        f"日{daily_pct:+.2f}%"
        f" vs 周{weekly_pct:+.2f}%"
        f",偏离周线收盘{deviation:+.2f}%"
        f")"
    )
    
    return {
        'status': status,
        'detail': detail,
        'daily_close': daily_close,
        'daily_pct': daily_pct,
        'weekly_close': weekly_close,
        'weekly_pct': weekly_pct,
        'deviation': round(deviation, 2),
    }


def _ema(s: pd.Series, n: int) -> pd.Series:
    """EMA — 因为 tushare weekly 不返回 ema 指标，自己算"""
    return s.ewm(span=n, adjust=False).mean()


def calc_weekly_ma(df: pd.DataFrame) -> Dict[str, Any]:
    """周线均线维度 (max 45)
    - 站上5周线: +15
    - 5周>10周: +15
    - 10周>20周: +15

    注: 倒序数据，iloc[0]=最新周，iloc[1]=上周
    """
    if df is None or len(df) < 20:
        return {"score": 0, "detail": "数据不足", "max": 45}

    closes = df['close'].astype(float)
    close_now = closes.iloc[0]
    ma5 = closes.head(5).mean()
    ma10 = closes.head(10).mean()
    ma20 = closes.head(20).mean()

    above_ma5 = close_now > ma5
    ma5_gt_ma10 = ma5 > ma10
    ma10_gt_ma20 = ma10 > ma20

    score = 0
    details = []
    if above_ma5:
        score += 15
        details.append("站上5周线")
    if ma5_gt_ma10:
        score += 15
        details.append("5周>10周")
    if ma10_gt_ma20:
        score += 15
        details.append("10周>20周")

    return {
        "score": min(45, score),
        "detail": ", ".join(details) if details else "空头排列",
        "raw": {
            "close_now": close_now,
            "ma5": ma5, "ma10": ma10, "ma20": ma20,
            "above_ma5": above_ma5,
            "ma5_gt_ma10": ma5_gt_ma10,
            "ma10_gt_ma20": ma10_gt_ma20,
        }
    }


def calc_weekly_position(df: pd.DataFrame, n_weeks: int = 12) -> Dict[str, Any]:
    """周线位置维度 (max 35)
    12周区间的相对位置 (current-low) / (high-low):
      - > 80%: 接近12周高点 (35分)
      - > 60%: 强势区间 (25分)
      - > 40%: 中位区间 (15分)
      - > 20%: 弱势区间 (10分)
      - ≤ 20%: 接近12周低点 (0分)

    注: 数据已是倒序，iloc[:12] = 最近12周
    """
    if df is None or len(df) < n_weeks:
        return {"score": 0, "detail": f"数据不足(需{n_weeks}周)", "max": 35}

    closes = df['close'].astype(float).head(n_weeks)
    high = closes.max()
    low = closes.min()
    close_now = closes.iloc[0]

    if high == low:
        position = 50.0
    else:
        position = (close_now - low) / (high - low) * 100

    if position > 95:
        score = 35
        zone = "突破前高"
    elif position > 80:
        score = 30
        zone = "接近12周高点"
    elif position > 60:
        score = 25
        zone = "强势区间"
    elif position > 40:
        score = 15
        zone = "中位区间"
    elif position > 20:
        score = 10
        zone = "弱势区间"
    else:
        score = 0
        zone = "接近12周低点"

    return {
        "score": score,
        "position_pct": round(position, 1),
        "zone": zone,
        "high": high, "low": low, "current": close_now,
    }


def calc_weekly_volume(df: pd.DataFrame) -> Dict[str, Any]:
    """周线量能维度 (max 20)
    本周量 vs 上周量:
      - 放量 ≥ 1.5倍 (20分)
      - 温和放量 1.2-1.5倍 (15分)
      - 平稳 0.8-1.2倍 (10分)
      - 缩量 < 0.8倍 (5分)
    """
    if df is None or len(df) < 2:
        return {"score": 0, "detail": "数据不足", "max": 20}

    vol_now = float(df.iloc[0]['vol'])
    vol_prev = float(df.iloc[1]['vol'])

    if vol_prev <= 0:
        return {"score": 10, "detail": "无量比较", "ratio": 1.0}

    ratio = vol_now / vol_prev
    if ratio >= 1.5:
        score, label = 20, "明显放量"
    elif ratio >= 1.2:
        score, label = 15, "温和放量"
    elif ratio >= 0.8:
        score, label = 10, "量能平稳"
    else:
        score, label = 5, "量能萎缩"

    return {
        "score": score,
        "ratio": round(ratio, 2),
        "detail": f"{label}({ratio:.1f}倍)",
        "vol_now": vol_now, "vol_prev": vol_prev,
    }


def calc_weekly_macd(df: pd.DataFrame) -> Dict[str, Any]:
    """周线MACD维度 (max 55)
    EMA12 / EMA26 / DIF = EMA12 - EMA26 / DEA = EMA(DIF, 9)
    - DIF>DEA 多头 (15分)
    - DIF>0 中长期多头 (15分)
    - 红柱区 (10分)
    - 红柱扩大 (10分)
    - 金叉 (5分, 一次性信号)
    """
    if df is None or len(df) < 30:
        return {"score": 0, "detail": "数据不足", "max": 55}

    # 倒序数据，按日期升序计算指标
    closes = df['close'].astype(float).iloc[::-1].reset_index(drop=True)
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    dif = ema12 - ema26
    dea = _ema(dif, 9)
    macd_hist = (dif - dea) * 2

    latest_dif = dif.iloc[-1]
    latest_dea = dea.iloc[-1]
    latest_hist = macd_hist.iloc[-1]
    prev_hist = macd_hist.iloc[-2] if len(macd_hist) > 1 else 0

    score = 0
    details = []

    if latest_dif > latest_dea:
        score += 15
        details.append("DIF>DEA(多头)")
    else:
        details.append("DIF<DEA(空头)")

    if latest_dif > 0:
        score += 15
        details.append("DIF>0")

    if latest_hist > 0:
        score += 10
        details.append("红柱区")
    else:
        details.append("绿柱区")

    if latest_hist > prev_hist and latest_hist > 0:
        score += 10
        details.append("红柱扩大")
    elif latest_hist < prev_hist and latest_hist < 0:
        details.append("绿柱扩大")

    # 金叉：本周 DIF 上穿 DEA
    prev_dif = dif.iloc[-2]
    prev_dea = dea.iloc[-2]
    if prev_dif <= prev_dea and latest_dif > latest_dea:
        score += 5
        details.append("周线MACD金叉!")
    # 死叉
    elif prev_dif >= prev_dea and latest_dif < latest_dea:
        details.append("周线MACD死叉")

    return {
        "score": min(55, score),
        "detail": ", ".join(details),
        "DIF": round(latest_dif, 4),
        "DEA": round(latest_dea, 4),
        "MACD_hist": round(float(latest_hist), 4),
    }


def calc_weekly_trend(df: pd.DataFrame, n_weeks: int = 4) -> Dict[str, Any]:
    """趋势形态维度 (max 15)
    近4周中周线收阳的周数:
      - 4周全阳: +15
      - 3周阳: +10
      - 2周阳: +5
      - 1周阳: +0
      - 0周阳: -5(扣减)
    """
    if df is None or len(df) < n_weeks:
        return {"score": 0, "detail": "数据不足", "max": 15}

    pct_chgs = df['pct_chg'].astype(float).head(n_weeks).tolist()
    up_weeks = [p for p in pct_chgs if p > 0]
    count = len(up_weeks)

    if count >= n_weeks:
        score = 15; label = f"近{n_weeks}周{n_weeks}周上涨"
    elif count >= n_weeks - 1:
        score = 10; label = f"近{n_weeks}周{count}周上涨"
    elif count >= 1:
        score = 5; label = f"近{n_weeks}周{count}周上涨"
    else:
        score = -5; label = f"近{n_weeks}周全周下跌"

    return {
        "score": score,
        "detail": label,
        "up_weeks": count,
        "total_weeks": n_weeks,
        "pct_chgs": [round(p, 2) for p in pct_chgs],
    }


def get_trend_label(score: int) -> str:
    """根据总分给出趋势判断"""
    if score >= 85:
        return "📈 周线强势"
    elif score >= 60:
        return "➡️ 周线偏强"
    elif score >= 40:
        return "➡️ 周线震荡"
    elif score >= 20:
        return "📉 周线偏弱"
    else:
        return "📉 周线弱势"


def analyze_weekly(code: str, end_date: str = None) -> Dict[str, Any]:
    """综合周线分析 - 一键调用，含当日实时价格对照"""
    df = load_weekly(code, end_date=end_date)

    if df is None or len(df) < 4:
        return {
            "code": code,
            "error": "周线数据不足(需至少4周)",
            "total_score": 0, "grade": "N/A",
        }

    ma = calc_weekly_ma(df)
    pos = calc_weekly_position(df)
    vol = calc_weekly_volume(df)
    macd = calc_weekly_macd(df)
    trend = calc_weekly_trend(df)

    total = ma["score"] + pos["score"] + vol["score"] + macd["score"] + trend["score"]

    # 截断到 0-200 范围
    total = max(0, min(200, total))

    if total >= 130:
        grade = "S"
    elif total >= 100:
        grade = "A"
    elif total >= 70:
        grade = "B"
    elif total >= 40:
        grade = "C"
    else:
        grade = "D"

    # 加载当日实时价格
    daily = load_latest_daily(code)
    weekly_close = float(df.iloc[0].get('close', 0))
    weekly_pct = float(df.iloc[0].get('pct_chg', 0))

    # 日/周一致性检查
    alignment = calc_daily_vs_weekly_alignment(daily, weekly_close, weekly_pct)

    return {
        "code": code,
        "trade_date": df.iloc[0].get('trade_date'),  # 最新周
        "total_score": total,
        "grade": grade,
        "trend_label": get_trend_label(total),
        "ma": ma,
        "position": pos,
        "volume": vol,
        "macd": macd,
        "trend": trend,
        "weekly_high_low": {
            "current_week_high": float(df.iloc[0].get('high', 0)),
            "current_week_low": float(df.iloc[0].get('low', 0)),
            "current_week_pct_chg": weekly_pct,
            "current_week_close": weekly_close,
        },
        "daily_price": daily,
        "daily_vs_weekly": alignment,
    }


if __name__ == "__main__":
    import json
    print("=" * 60)
    print("周线分析模块 — 测试（含日/周对照）")
    print("=" * 60)

    for code, name in [("000938.SZ", "紫光股份"),
                       ("603638.SH", "艾迪精密"),
                       ("002472.SZ", "双环传动")]:
        print(f"\n[{name} {code}]")
        r = analyze_weekly(code)
        if "error" in r:
            print(f"  ⚠ {r['error']}")
        else:
            # 周线评分
            print(f"  综合分: {r['total_score']}/200 → {r['grade']}级 {r['trend_label']}")
            print(f"  最近周: {r['trade_date']} (周变动{r['weekly_high_low']['current_week_pct_chg']:+.2f}%，收盘{r['weekly_high_low']['current_week_close']:.2f})")
            print(f"  · 均线: {r['ma']['score']}/45 — {r['ma']['detail']}")
            print(f"  · 位置: {r['position']['score']}/35 — {r['position']['zone']} ({r['position']['position_pct']}%)")
            print(f"  · 量能: {r['volume']['score']}/20 — {r['volume']['detail']}")
            print(f"  · MACD: {r['macd']['score']}/55 — {r['macd']['detail']}")
            print(f"  · 形态: {r['trend']['score']}/15 — {r['trend']['detail']}")

            # 日/周对照
            print(f"  ── 日/周对照 ──")
            print(f"  {r['daily_vs_weekly']['status']}")
            print(f"  {r['daily_vs_weekly']['detail']}")
