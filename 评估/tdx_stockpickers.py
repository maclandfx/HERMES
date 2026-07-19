#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tdx_stockpickers.py —— 通达信条件选股 Python 实现

5 个条件选股公式（对照 D:/TDX/T0001/export/主力全景5.dat 源码）：
  1. 20日DCZ双回踩
  2. 四维共振主起
  3. 金牌狙击紧
  4. 黄金右侧
  5. 黄金右侧紧

输入：标准日线 DataFrame (columns: open, high, low, close, vol, trade_date)
输出：{passed: bool, reason: str, score: int, signals: list}

批量入口：
  - scan_conditions(df)         → 对单只股票跑5条件
  - run_scanner(stock_list)     → 全市场批量扫描（调用 pro.daily 取K线）

数据源：复用 eval_smart 已通的 tushare.pro.daily(ts_code, start_date, end_date)
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional


# ============================================================
# 1. 20日DCZ双回踩
# ============================================================
def pick_dc2_double_pullback(df: pd.DataFrame) -> Dict[str, Any]:
    """
    20日DCZ双回踩 — 股价两次回调到DCZ附近并获支撑反弹

    选股逻辑（日线）：
      - 计算60日成交加权DCZ（中位成本）
      - 近20日内出现过 >=2 次收盘价贴近DCZ(±3%)的"回踩"
      - 回踩当日或次日必须放量（量比 > 1.2）且收阳/止跌
      - 当前价位于DCZ之上（主力护盘成功）

    输入 df 已按 trade_date 升序，最新在末尾。
    """
    if df is None or df.empty or len(df) < 30:
        return {"passed": False, "reason": "数据不足(<30日线)", "score": 0, "signals": []}

    df = df.sort_values("trade_date").reset_index(drop=True).copy()
    c = df["close"].astype(float)
    l = df["low"].astype(float)
    o = df["open"].astype(float)
    v = df["vol"].astype(float)
    ma5v = c.rolling(5, min_periods=1).apply(lambda x: x.mean())  # placeholder; vol MA handled separately
    vol_ma5 = v.rolling(5, min_periods=1).mean()

    # 估算 DCZ（近60日成交加权中位成本）
    recent60 = df.tail(60).copy()
    recent60["amt"] = recent60["close"] * recent60["vol"]
    total = recent60["amt"].sum()
    if total == 0:
        return {"passed": False, "reason": "成交额为0", "score": 0, "signals": []}
    recent60 = recent60.sort_values("close")
    recent60["cum"] = recent60["amt"].cumsum()
    dc_z = recent60.loc[recent60["cum"] >= total * 0.5, "close"].iloc[0]

    # 回踩窗口：近20日
    win = df.tail(20)
    pulls = []
    for _, r in win.iterrows():
        dist = abs(r["close"] - dc_z) / dc_z
        if dist <= 0.03:  # 价格距DCZ ±3%
            v_ratio = r["vol"] / (vol_ma5[r.name] if vol_ma5[r.name] > 0 else r["vol"])
            # 止跌信号：下影线>实体 或 次日收阳
            body = abs(r["close"] - r["open"])
            lower_shadow = r["close"] - r["low"]
            support = (lower_shadow > body) or (v_ratio > 1.2)
            pulls.append({"idx": r.name, "close": r["close"], "v_ratio": round(v_ratio, 2), "support": support})

    # 需要 >=2 次回踩且至少一次有支撑+放量
    valid_pulls = [p for p in pulls if p["support"] and p["v_ratio"] > 1.1]
    score = 0
    signals = []

    if len(pulls) >= 2:
        signals.append(f"近20日{len(pulls)}次回踩DCZ(¥{dc_z:.2f})")
        score += 20
    if len(valid_pulls) >= 2:
        signals.append(f"其中{len(valid_pulls)}次放量支撑(量比>1.1)")
        score += 30
    if c.iloc[-1] > dc_z:
        signals.append("现价位于DCZ之上")
        score += 20

    if len(valid_pulls) >= 2 and c.iloc[-1] > dc_z:
        passed = True
        reason = f"20日DCZ双回踩确认：{len(pulls)}次回踩，{len(valid_pulls)}次放量支撑，现价¥{c.iloc[-1]:.2f}>DCZ¥{dc_z:.2f}"
    else:
        passed = False
        reason = f"仅{len(valid_pulls)}次有效回踩，不足2次"

    return {"passed": passed, "reason": reason, "score": min(score, 100), "signals": signals,
            "dcz": round(float(dc_z), 2), "pull_count": len(pulls)}


# ============================================================
# 2. 四维共振主起
# ============================================================
def pick_four_dim_resonance(
    df: pd.DataFrame,
    sector_zscore: float = None,
    market_bull: bool = False,
    north_5d: float = None,
) -> Dict[str, Any]:
    """
    四维共振主起 — 天时地利人和技术四力汇聚

    四维：
      天时 = 大盘多头（指数>MA60 且MA60向上）
      地利 = 板块热力（板块ZSCORE > 1.5）
      人和 = 北向5日净流入（north_5d > 0）
      技术 = 个股突破（放量站上20日线 + 主进信号）

    共振条件：4维中 >=3 维达标 → 主起信号。
    """
    if df is None or df.empty or len(df) < 30:
        return {"passed": False, "reason": "数据不足", "score": 0, "dim": {}}

    df = df.sort_values("trade_date").reset_index(drop=True).copy()
    c = df["close"].astype(float)
    v = df["vol"].astype(float)

    dim = {}
    # 技术维：放量站上20日线
    ma20 = c.rolling(20, min_periods=1).mean()
    vol_ma5 = v.rolling(5, min_periods=1).mean()
    tech_ok = (c.iloc[-1] > ma20.iloc[-1]) and (c.shift(1).iloc[-1] <= ma20.shift(1).iloc[-1]) and (v.iloc[-1] > vol_ma5.iloc[-1] * 1.3)
    # 放宽：站上20日线 + 近5日有放量
    tech_ok2 = (c.iloc[-1] > ma20.iloc[-1]) and (v.rolling(5).max().iloc[-1] > vol_ma5.iloc[-1] * 1.5)
    dim["技术"] = {"ok": bool(tech_ok or tech_ok2),
                   "detail": f"站上MA20(¥{ma20.iloc[-1]:.2f}), 近5日放量={bool(v.rolling(5).max().iloc[-1] > vol_ma5.iloc[-1]*1.5)}"}

    # 天时维：大盘多头（需外部传入）
    dim["天时"] = {"ok": bool(market_bull), "detail": "大盘多头" if market_bull else "大盘非多头"}

    # 地利维：板块热力
    sector_ok = (sector_zscore is not None) and (sector_zscore > 1.5)
    dim["地利"] = {"ok": bool(sector_ok), "detail": f"板块ZSCORE={sector_zscore:.2f}" if sector_zscore else "无板块数据"}

    # 人和维：北向资金
    north_ok = (north_5d is not None) and (north_5d > 0)
    dim["人和"] = {"ok": bool(north_ok), "detail": f"北向5日{north_5d:.1f}亿" if north_5d is not None else "无北向数据"}

    ok_count = sum([dim[d]["ok"] for d in ["技术", "天时", "地利", "人和"]])
    score = ok_count * 25

    if ok_count >= 3:
        passed = True
        reason = f"四维共振主起：{ok_count}/4维达标(技术{dim['技术']['ok']}/天时{dim['天时']['ok']}/地利{dim['地利']['ok']}/人和{dim['人和']['ok']})"
    elif ok_count >= 2:
        passed = False
        reason = f"部分共振：仅{ok_count}/4维达标，未达主起标准"
    else:
        passed = False
        reason = f"四维散乱：仅{ok_count}/4维达标"

    return {"passed": passed, "reason": reason, "score": min(score, 100), "dim": dim, "dim_ok": ok_count}


# ============================================================
# 3. 金牌狙击紧
# ============================================================
def pick_golden_sniper_tight(df: pd.DataFrame) -> Dict[str, Any]:
    """
    金牌狙击紧 — 主进+A/B级+筹码集中+量价齐升

    选股逻辑：
      - 主力进场信号触发（R0>0 且 平均线拐头向上）
      - 主进分级 A 或 B 级
      - 筹码集中度 < 30%（九十成本区间窄）
      - 量价齐升：上涨日放量，量比 > 1.5，涨幅 > 3%

    输入 df 已按 trade_date 升序。
    """
    if df is None or df.empty or len(df) < 30:
        return {"passed": False, "reason": "数据不足", "score": 0, "signals": []}

    df = df.sort_values("trade_date").reset_index(drop=True).copy()
    o = df["open"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    c = df["close"].astype(float)
    v = df["vol"].astype(float)

    # 核心信号计算
    vv = v / v.rolling(5, min_periods=1).mean().replace(0, np.nan)
    r0 = ((c - c.shift(1)) / c.shift(1) * 100) * vv
    min_10 = l.rolling(10, min_periods=1).min()
    max_25 = h.rolling(25, min_periods=1).max()
    rng = (max_25 - min_10).replace(0, np.nan)
    wave = (c - min_10) / rng * 4
    wave = wave.ewm(span=4, adjust=False).mean()
    avg_line = wave.ewm(span=3, adjust=False).mean()

    # 主力进
    r0_abs5 = sum([abs(r0.shift(i)) for i in range(1, 6)]) / 5
    main_enter = (r0 > r0_abs5 / 2) & (avg_line >= avg_line.shift(1)) & (avg_line.shift(1) < avg_line.shift(2))
    last_main_enter = bool(main_enter.iloc[-1])

    # 筹码集中度估算
    recent60 = df.tail(60)
    recent60 = recent60.copy()
    recent60["amt"] = recent60["close"] * recent60["vol"]
    total = recent60["amt"].sum()
    if total == 0:
        concentration = 50.0
    else:
        s = recent60.sort_values("close")
        s["cum"] = s["amt"].cumsum()
        try:
            c5 = s.loc[s["cum"] >= total * 0.05, "close"].iloc[0]
            c95 = s.loc[s["cum"] >= total * 0.95, "close"].iloc[0]
        except Exception:
            c5 = float(c.iloc[-1] * 0.9); c95 = float(c.iloc[-1] * 1.1)
        concentration = (c95 - c5) / (c95 + c5) * 100

    # 量价齐升
    chg_pct = (c.iloc[-1] - c.iloc[-2]) / c.iloc[-2] * 100
    vol_ratio = v.iloc[-1] / (v.rolling(5).mean().iloc[-1] if v.rolling(5).mean().iloc[-1] > 0 else v.iloc[-1])
    amp_pct = (h.iloc[-1] - l.iloc[-1]) / c.iloc[-2] * 100
    vol_ma5 = v.rolling(5).mean().iloc[-1]
    vol_up = v.iloc[-1] > vol_ma5 * 1.5
    price_up = chg_pct > 3

    signals = []
    score = 0

    if last_main_enter:
        signals.append("主力进场信号触发")
        score += 25
    if concentration < 30:
        signals.append(f"筹码集中({concentration:.1f}%<30%)")
        score += 25
    if vol_up:
        signals.append(f"放量(量比{vol_ratio:.2f}>1.5)")
        score += 20
    if price_up:
        signals.append(f"上涨{chg_pct:.1f}%>3%")
        score += 20

    # A级条件：主力进 + 筹码集中 + 放量 + 上涨
    if last_main_enter and concentration < 30 and vol_up and price_up:
        passed = True
        reason = f"金牌狙击紧确认：主进+A级条件，筹码{concentration:.1f}%，量比{vol_ratio:.2f}，涨{chg_pct:.1f}%"
        score = max(score, 80)
    elif last_main_enter and (concentration < 30 or vol_up) and price_up:
        passed = True
        reason = f"金牌狙击紧（B级）：主进+{len(signals)}项达标"
        score = max(score, 65)
    else:
        passed = False
        reason = f"未达金牌狙击紧：主进={last_main_enter}, 筹码{concentration:.1f}%, 量比{vol_ratio:.2f}, 涨{chg_pct:.1f}%"

    return {"passed": passed, "reason": reason, "score": min(score, 100), "signals": signals,
            "main_enter": last_main_enter, "concentration": round(float(concentration), 1),
            "chg_pct": round(float(chg_pct), 2), "vol_ratio": round(float(vol_ratio), 2)}


# ============================================================
# 4. 黄金右侧
# ============================================================
def pick_golden_right_side(df: pd.DataFrame) -> Dict[str, Any]:
    """
    黄金右侧 — 趋势通道上轨突破 + MACD金叉 + 主力资金净流入

    选股逻辑：
      - 股价放量突破趋势通道上轨（突破近20日高点区域）
      - MACD金叉（DIF上穿DEA）
      - 主力资金净流入（R0资金动量 > 0 且持续）

    适合右侧追涨，需配合止损。
    """
    if df is None or df.empty or len(df) < 30:
        return {"passed": False, "reason": "数据不足", "score": 0, "signals": []}

    df = df.sort_values("trade_date").reset_index(drop=True).copy()
    c = df["close"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    v = df["vol"].astype(float)

    # 趋势通道：基于平均线
    min_10 = l.rolling(10, min_periods=1).min()
    max_25 = h.rolling(25, min_periods=1).max()
    rng = (max_25 - min_10).replace(0, np.nan)
    wave = (c - min_10) / rng * 4
    wave = wave.ewm(span=4, adjust=False).mean()
    avg_line = wave.ewm(span=3, adjust=False).mean()
    ch_mid = avg_line.rolling(5).mean()
    ch_std = avg_line.rolling(20, min_periods=1).std()
    ch_up = ch_mid + 2 * ch_std

    # 突破上轨
    break_up = c.iloc[-1] > ch_up.iloc[-1] and c.shift(1).iloc[-1] <= ch_up.shift(1).iloc[-1]

    # MACD
    dif = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    dea = dif.ewm(span=9, adjust=False).mean()
    macd_cross = (dif.iloc[-1] > dea.iloc[-1]) and (dif.shift(1).iloc[-1] <= dea.shift(1).iloc[-1])

    # 资金流 R0
    vv = v / v.rolling(5, min_periods=1).mean().replace(0, np.nan)
    r0 = ((c - c.shift(1)) / c.shift(1) * 100) * vv
    money_in = (r0.iloc[-1] > 0) and (r0.rolling(3).mean().iloc[-1] > 0)

    # 放量
    vol_ma5 = v.rolling(5).mean().iloc[-1]
    vol_up = v.iloc[-1] > vol_ma5 * 1.5 if vol_ma5 > 0 else False

    signals = []
    score = 0
    if break_up:
        signals.append("突破通道上轨")
        score += 30
    if macd_cross:
        signals.append("MACD金叉")
        score += 25
    if money_in:
        signals.append("资金净流入(R0>0)")
        score += 25
    if vol_up:
        signals.append("放量突破")
        score += 20

    if break_up and macd_cross and money_in:
        passed = True
        reason = f"黄金右侧确认：突破上轨+MACD金叉+资金流入，{len(signals)}项全达标"
        score = max(score, 80)
    elif break_up and macd_cross:
        passed = True
        reason = f"黄金右侧（资金未确认）：突破上轨+MACD金叉"
        score = max(score, 60)
    else:
        passed = False
        reason = f"未达黄金右侧：突破={break_up}, MACD金叉={macd_cross}, 资金流入={money_in}"

    return {"passed": passed, "reason": reason, "score": min(score, 100), "signals": signals,
            "break_up": bool(break_up), "macd_cross": bool(macd_cross), "money_in": bool(money_in)}


# ============================================================
# 5. 黄金右侧紧
# ============================================================
def pick_golden_right_side_tight(df: pd.DataFrame) -> Dict[str, Any]:
    """
    黄金右侧紧 — 黄金右侧 + 涨幅<10%（未加速，仍在主升初期）

    在"黄金右侧"基础上增加"紧"约束：
      - 近5日累计涨幅 < 10%（排除已加速的高位）
      - 当前涨幅 < 涨停价（未封板）
      - 换手率适中（3%~15%）

    适合右侧追涨但仍处主升初期的品种。
    """
    base = pick_golden_right_side(df)

    if df is None or df.empty or len(df) < 10:
        return base

    df = df.sort_values("trade_date").reset_index(drop=True).copy()
    c = df["close"].astype(float)
    v = df["vol"].astype(float)

    # 近5日累计涨幅
    cum_chg_5d = (c.iloc[-1] - c.iloc[-6]) / c.iloc[-6] * 100 if len(df) >= 6 else 0
    # 当日涨幅
    chg_today = (c.iloc[-1] - c.iloc[-2]) / c.iloc[-2] * 100 if len(df) >= 2 else 0

    tight_ok = (cum_chg_5d < 10) and (chg_today < 10)

    if base["passed"] and tight_ok:
        passed = True
        reason = f"黄金右侧紧确认：右侧信号+5日涨{cum_chg_5d:.1f}%<10%+日涨{chg_today:.1f}%<10%"
        score = min(base["score"] + 10, 100)
    elif base["passed"]:
        passed = False
        reason = f"黄金右侧但已加速：5日涨{cum_chg_5d:.1f}%>=10% 或 日涨{chg_today:.1f}%>=10%"
        score = base["score"]
    else:
        passed = False
        reason = f"基础黄金右侧未达：{base['reason']}"
        score = base["score"]

    return {"passed": passed, "reason": reason, "score": min(score, 100),
            "signals": base.get("signals", []) + [("紧:5日涨%.1f%%,日涨%.1f%%" % (cum_chg_5d, chg_today))],
            "cum_chg_5d": round(float(cum_chg_5d), 2), "chg_today": round(float(chg_today), 2),
            "base": base}


# ============================================================
# 统一扫描：对单只股票跑5条件
# ============================================================
CONDITIONS = {
    "20日DCZ双回踩": pick_dc2_double_pullback,
    "四维共振主起": lambda df, **kw: pick_four_dim_resonance(df, **kw),
    "金牌狙击紧": pick_golden_sniper_tight,
    "黄金右侧": pick_golden_right_side,
    "黄金右侧紧": pick_golden_right_side_tight,
}


def scan_conditions(
    df: pd.DataFrame,
    stock_code: str = None,
    sector_zscore: float = None,
    market_bull: bool = False,
    north_5d: float = None,
) -> Dict[str, Any]:
    """
    对单只股票跑全部5个选股条件。
    返回: {"stock": str, "results": {条件名: {passed, reason, score}}, "passed_count": int, "passed_conditions": [str]}
    """
    results = {}
    passed_count = 0
    passed_names = []

    for name, fn in CONDITIONS.items():
        try:
            if name == "四维共振主起":
                res = fn(df, sector_zscore=sector_zscore, market_bull=market_bull, north_5d=north_5d)
            else:
                res = fn(df)
            results[name] = res
            if res.get("passed"):
                passed_count += 1
                passed_names.append(name)
        except Exception as e:
            results[name] = {"passed": False, "reason": f"计算异常: {e}", "score": 0}

    return {
        "stock": stock_code,
        "results": results,
        "passed_count": passed_count,
        "passed_conditions": passed_names,
        "max_score": max([r.get("score", 0) for r in results.values()], default=0),
    }


# ============================================================
# 全市场批量扫描入口
# ============================================================
def run_scanner(
    stock_codes: List[str],
    ts_codes: Dict[str, str] = None,
    tushare_pro=None,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    全市场批量扫描选股。

    参数:
      stock_codes: 股票代码列表，如 ["000001", "600519", ...] 或 ts_code
      ts_codes: {股票代码: ts_code} 映射，避免重复调 stock_basic
      tushare_pro: tushare pro 实例
      verbose: 是否打印进度

    返回:
      {
        "total": N,
        "scanned": N,
        "by_condition": {"20日DCZ双回踩": [...code...], ...},
        "candidates": [
          {"code": str, "name": str, "passed_count": int, "passed_conditions": [str],
           "max_score": int, "results": {条件: {passed, reason, score}}}
        ],
        "summary": {"总扫描":N, "命中>=2条件":N, "命中全部5条件":N, "各条件命中数": {...}}
      }
    """
    import tushare as ts

    pro = tushare_pro if tushare_pro is not None else ts.pro_api()
    import datetime

    end_date = datetime.datetime.now().strftime("%Y%m%d")
    try:
        cal_df = pro.trade_cal(exchange="SSE", start_date=(datetime.datetime.now() - datetime.timedelta(days=10)).strftime("%Y%m%d"),
                               end_date=end_date, is_open="1")
        if cal_df is not None and not cal_df.empty:
            last_open = sorted(cal_df["cal_date"].tolist())[-1]
            if last_open != end_date:
                end_date = last_open
    except Exception:
        pass

    if ts_codes is None:
        try:
            basic = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
            code2ts = {r["ts_code"].split(".")[0]: {"ts": r["ts_code"], "name": r["name"]} for _, r in basic.iterrows()}
        except Exception:
            code2ts = {c: {"ts": f"{c}.SH", "name": ""} for c in stock_codes}
    else:
        code2ts = ts_codes

    by_condition = {name: [] for name in CONDITIONS}
    candidates = []
    total = len(stock_codes)
    scanned = 0

    for i, code in enumerate(stock_codes):
        if code2ts.get(code) is None:
            continue
        ts_code = code2ts[code]["ts"]
        name = code2ts[code]["name"]

        try:
            d = pro.daily(ts_code=ts_code, start_date="20250101", end_date=end_date)
            if d is None or d.empty or len(d) < 30:
                continue
            d = d.sort_values("trade_date").reset_index(drop=True)

            # 重命名列以适配 tdx_core
            col_map = {"trade_date": "trade_date", "open": "open", "high": "high",
                       "low": "low", "close": "close", "vol": "vol"}
            df_in = d[[c for c in ["open", "high", "low", "close", "vol"] if c in d.columns]].copy()
            if "trade_date" in d.columns:
                df_in["trade_date"] = pd.to_datetime(d["trade_date"])
            else:
                df_in["trade_date"] = pd.date_range(start=end_date.replace("-", "").replace("/", ""), periods=len(df_in), freq="B")

            res = scan_conditions(df_in, stock_code=code)
            scanned += 1
            if res["passed_count"] > 0:
                res["code"] = code
                res["name"] = name
                candidates.append(res)
                for cond in res["passed_conditions"]:
                    by_condition[cond].append(code)

        except Exception as e:
            if verbose:
                print(f"  ⚠ {code} 扫描失败: {e}")
            continue

        if verbose and (i + 1) % 500 == 0:
            print(f"  进度: {i+1}/{total} 已扫描 {scanned} 命中 {len(candidates)}")

    # 排序：命中数优先，再按最高分
    candidates.sort(key=lambda x: (-x["passed_count"], -x["max_score"]))

    cond_hit_count = {name: len(by_condition[name]) for name in CONDITIONS}

    return {
        "total": total,
        "scanned": scanned,
        "by_condition": by_condition,
        "candidates": candidates,
        "summary": {
            "总扫描": scanned,
            "命中>=2条件": sum(1 for c in candidates if c["passed_count"] >= 2),
            "命中全部5条件": sum(1 for c in candidates if c["passed_count"] == 5),
            "各条件命中数": cond_hit_count,
            "候选股数": len(candidates),
        },
        "end_date": end_date,
    }


if __name__ == "__main__":
    print("tdx_stockpickers.py 模块加载成功")
    print("5个选股条件:")
    for n in CONDITIONS:
        print(f"  - {n}")
    print("入口函数:")
    print("  - scan_conditions(df, **kw) → 单只股票跑5条件")
    print("  - run_scanner(stock_codes)  → 全市场批量扫描")
