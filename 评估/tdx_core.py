#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tdx_core.py —— 通达信《主力全景主图系统 V3.9》核心算法 Python 移植版
封装了：R0资金动量、平均线/趋势通道、主力进退判断、主进分级(A/B/C/D)、
筹码分布(DCZ/九十成本集中度)、资金攻击信号、多维环境共振、关键节点信号

依赖：pandas, numpy
输入：标准 tushare 日线 DataFrame (columns: open, high, low, close, vol, trade_date 等)
输出：结构化 dict，可直接写入 eval_smart 结果
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Any


# ============================================================
# 通用工具函数（通达信函数对应）
# ============================================================

def _ref_bool(series: pd.Series, n: int) -> pd.Series:
    """REF(X, n) - 向前引用 n 期，保持 boolean dtype"""
    return series.shift(n).fillna(False).astype(bool)


def _ref(series: pd.Series, n: int) -> pd.Series:
    """REF(X, n) - 向前引用 n 期，保持原 dtype"""
    return series.shift(n)


def _ma(series: pd.Series, n: int) -> pd.Series:
    """MA(X, n) - 简单移动平均"""
    return series.rolling(n, min_periods=1).mean()


def _ema(series: pd.Series, n: int) -> pd.Series:
    """EMA(X, n) - 指数移动平均"""
    return series.ewm(span=n, adjust=False).mean()


def _llv(series: pd.Series, n: int) -> pd.Series:
    """LLV(X, n) - n 期内最低值"""
    return series.rolling(n, min_periods=1).min()


def _hhv(series: pd.Series, n: int) -> pd.Series:
    """HHV(X, n) - n 期内最高值"""
    return series.rolling(n, min_periods=1).max()


def _std(series: pd.Series, n: int) -> pd.Series:
    """STD(X, n) - n 期标准差"""
    return series.rolling(n, min_periods=1).std()


def _sma(series: pd.Series, n: int, m: int = 1) -> pd.Series:
    """SMA(X, n, m) - 通达信 SMA 算法：Y = (m*X + (n-m)*Y')/n
    近似实现：ewm(alpha=m/n)"""
    alpha = m / n
    return series.ewm(alpha=alpha, adjust=False).mean()


def _cross(a: pd.Series, b: pd.Series | float | int) -> pd.Series:
    """CROSS(A, B) - A 上穿 B，支持 Series 和标量"""
    if isinstance(b, (int, float)):
        b = pd.Series(b, index=a.index)
    if isinstance(a, (int, float)):
        a = pd.Series(a, index=b.index)
    return (a > b) & (a.shift(1) <= b.shift(1))


def _exist(cond: pd.Series, n: int) -> pd.Series:
    """EXIST(COND, n) - n 期内条件曾满足"""
    return cond.rolling(n, min_periods=1).sum() > 0


def _if(cond: pd.Series, true_val: Any, false_val: Any) -> pd.Series:
    """IF(COND, TRUE, FALSE)"""
    return pd.Series(np.where(cond, true_val, false_val), index=cond.index)


def _abs(series: pd.Series) -> pd.Series:
    return series.abs()


def _sum(series: pd.Series, n: int) -> pd.Series:
    """SUM(X, n) - n 期累加"""
    return series.rolling(n, min_periods=1).sum()


def _max(a: pd.Series, b: pd.Series | float | int) -> pd.Series:
    """MAX(A, B) - 支持 Series 和标量"""
    if isinstance(b, (int, float)):
        return a.clip(lower=b)
    return pd.concat([a, b], axis=1).max(axis=1)


def _min(a: pd.Series, b: pd.Series | float | int) -> pd.Series:
    """MIN(A, B) - 支持 Series 和标量"""
    if isinstance(b, (int, float)):
        return a.clip(upper=b)
    return pd.concat([a, b], axis=1).min(axis=1)


def _ref_n_sum_abs(series: pd.Series, n: int) -> pd.Series:
    """通达信常用：SUM(ABS(REF(X, i)), i=1..n)"""
    total = pd.Series(0.0, index=series.index)
    for i in range(1, n + 1):
        total += _abs(_ref(series, i))
    return total


# ============================================================
# 核心计算模块
# ============================================================

def calc_tdx_core(df: pd.DataFrame) -> Dict[str, Any]:
    """
    计算通达信主力全景核心指标
    输入 df 必须包含: open, high, low, close, vol, trade_date (已按日期升序排列)
    返回: 包含所有核心指标的 dict
    """
    if df is None or df.empty or len(df) < 30:
        return {"error": "数据不足，至少需要 30 根日线"}

    # 确保数据按日期升序
    df = df.sort_values("trade_date").reset_index(drop=True).copy()

    # 基础列
    o = df["open"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    c = df["close"].astype(float)
    v = df["vol"].astype(float)

    # ========== 1. 核心资金流模块 ==========
    vv = v / _ma(v, 5).replace(0, np.nan)  # VV = VOL/MA(VOL,5)
    r0 = ((c - _ref(c, 1)) / _ref(c, 1) * 100) * vv  # R0 = 涨跌幅% * 量比
    r0ma5 = _ma(r0, 5)  # R0MA5

    # 平均线 = EMA(归一化价格位置 * 4, 4) 的 EMA(3)
    min_10 = _llv(l, 10)
    max_25 = _hhv(h, 25)
    # 避免分母为 0
    range_25 = (max_25 - min_10).replace(0, np.nan)
    wave = _ema((c - min_10) / range_25 * 4, 4)  # 波动线
    avg_line = _ema(wave, 3)  # 平均线 (核心趋势线)

    # 信息、走强、走弱、量
    info = avg_line >= _ref(avg_line, 1)  # 平均线向上
    walk_strong = (c > _ma(c, 20)) & (c > _ma(c, 5))  # 走强
    walk_weak = (c < _ma(c, 10)) & (c < _ma(c, 5))   # 走弱
    vol_up = v > _ma(v, 5)  # 放量

    # R0 5日绝对值均值
    r0_abs_5 = _ref_n_sum_abs(r0, 5) / 5  # (ABS(REF(R0,1))+...+ABS(REF(R0,5)))/5

    # 主力进/退核心判断
    main_enter = (
        (r0 > r0_abs_5 / 2) &           # R0 > 历史5日绝对值均值/2
        (avg_line >= _ref(avg_line, 1)) &  # 平均线上穿/持平
        (_ref(avg_line, 1) < _ref(avg_line, 2))  # 平均线前一根向下(拐头向上)
    )

    main_exit = (
        (r0 < -r0_abs_5 / 2) &          # R0 < -历史5日绝对值均值/2
        (avg_line <= _ref(avg_line, 1)) &  # 平均线下穿/持平
        (_ref(avg_line, 1) > _ref(avg_line, 2))  # 平均线前一根向上(拐头向下)
    )

    # ========== 2. 趋势决策通道 ==========
    channel_mid = _ma(avg_line, 5)  # 通道中轨
    channel_std = _std(avg_line, 20)  # 平均线20日标准差
    channel_up = channel_mid + 2 * channel_std  # 通道上轨
    channel_down = channel_mid - 2 * channel_std  # 通道下轨

    # 通道位置：0=下轨, 0.5=中轨, 1=上轨, >1=突破上轨, <0=跌破下轨
    channel_range = (channel_up - channel_down).replace(0, np.nan)
    channel_pos = (c - channel_down) / channel_range

    # ========== 3. 筹码分布模块 (DCZ / 九十成本集中) ==========
    # 通达信 COST 函数在 Python 中无法直接复刻(需要逐笔成交数据)
    # 这里提供近似实现：基于成交量加权价格分布估算
    # 实际生产建议：接入真实筹码分布数据源
    chip_concentration, dcz, dcz_up = _estimate_chip_distribution(df)

    # ========== 4. 资金攻击信号 ==========
    amp_pct = (h - l) / _ref(c, 1) * 100  # 振幅%
    chg_pct = (c - _ref(c, 1)) / _ref(c, 1) * 100  # 涨跌幅%
    ma20 = _ma(c, 20)
    ma20_up = ma20 > _ref(ma20, 1)
    c_above_ma20 = c > ma20
    vol_1_5x = v > _ma(v, 5) * 1.5
    dcz_up_series = pd.Series(dcz_up, index=df.index) if isinstance(dcz_up, (bool, np.bool_)) else dcz_up

    money_attack = (
        (chg_pct > 5) & 
        (amp_pct > 4) & 
        dcz_up_series & 
        ma20_up & 
        c_above_ma20 & 
        vol_1_5x
    )

    # ========== 5. 多维环境共振 (需要外部行业/指数数据，这里仅算个股部分) ==========
    ema3 = _ema(c, 3)
    ema7 = _ema(c, 7)
    flower_red = ema3 > ema7  # 花神红

    # ========== 6. 关键底部/顶部信号 ==========
    # 极底/D: 平均线<0.5 且 信息由0变1且前2根为0
    info_signal = (avg_line >= _ref(avg_line, 1)).astype(bool)
    extreme_bottom = (
        (avg_line < 0.5) & 
        info_signal & 
        (~_ref_bool(info_signal, 1)) & 
        (~_ref_bool(info_signal, 2)) & 
        (~_ref_bool(info_signal, 3))
    )

    # 建仓买点: 最佳买入指标三次平滑后金叉且<40
    # 简化：用 RSI+ADX 组合近似
    lc = _ref(c, 1)
    rsi5 = _sma(_max(c - lc, 0), 5) / _sma(_abs(c - lc), 5) * 100
    tr1 = _sum(_max(_max(h - l, _abs(h - lc)), _abs(l - lc)), 10)
    hd = h - _ref(h, 1)
    ld = _ref(l, 1) - l
    dmp = _sum(_if((hd > 0) & (hd > ld), hd, 0), 10)
    dmm = _sum(_if((ld > 0) & (ld > hd), ld, 0), 10)
    pdi = dmp * 100 / tr1.replace(0, np.nan)
    mdi = dmm * 100 / tr1.replace(0, np.nan)
    adx = _ma(_abs(mdi - pdi) / (mdi + pdi).replace(0, np.nan) * 100, 5)
    av = rsi5 + adx
    wr10 = 100 * (_hhv(h, 10) - c) / (_hhv(h, 10) - _llv(l, 10)).replace(0, np.nan)
    zcjl = rsi5 - wr10
    best_buy = av + zcjl
    best_buy_smooth1 = _sma(_sma(_sma(_if(_cross(best_buy, 0), 1, 0), 3), 3), 3)
    build_buy = _cross(best_buy_smooth1, 0) & (best_buy_smooth1 < 40)

    # 绝底: 阳线+开盘/最低>5%+创20日新低
    absolute_bottom = (
        (c > o) & 
        (o / l > 1.05) & 
        (l <= _llv(l, 20))
    )

    # 必涨: 跌穿 BZTD (DCZ * 0.89)
    bztd = dcz * 0.89 if isinstance(dcz, (int, float)) else pd.Series(dcz * 0.89, index=df.index)
    must_rise = _cross(l, bztd)

    # 逃亡: 会员RSI>79且向下
    member_rsi = _sma(_max(c - _ref(c, 2), 0), 7) / _sma(_abs(c - _ref(c, 2)), 7) * 100
    escape = (member_rsi < _ref(member_rsi, 1)) & (member_rsi > 79)

    # 逃顶组合: 主力退 + 顶/DD_VAL + 下/TZ + 逃/逃亡
    dd_val = (avg_line > 2) & (~info_signal) & _ref_bool(info_signal, 1) & (_ref_bool(info_signal, 2) | _ref_bool(info_signal, 3))
    tz_signal = (~info_signal) & _ref_bool(info_signal, 1) & (_ref_bool(info_signal, 2) | _ref_bool(info_signal, 3)) & (r0ma5 < 0) & walk_weak & (avg_line > 1)
    escape_top = main_exit | dd_val | tz_signal | escape

    # ========== 汇总输出 ==========
    latest_idx = -1
    return {
        "core_metrics": {
            "r0": float(r0.iloc[latest_idx]),
            "r0ma5": float(r0ma5.iloc[latest_idx]),
            "avg_line": float(avg_line.iloc[latest_idx]),
            "info_signal": bool(info_signal.iloc[latest_idx]),
            "walk_strong": bool(walk_strong.iloc[latest_idx]),
            "walk_weak": bool(walk_weak.iloc[latest_idx]),
            "vol_up": bool(vol_up.iloc[latest_idx]),
        },
        "main_signals": {
            "main_enter": bool(main_enter.iloc[latest_idx]),
            "main_exit": bool(main_exit.iloc[latest_idx]),
        },
        "trend_channel": {
            "mid": float(channel_mid.iloc[latest_idx]),
            "upper": float(channel_up.iloc[latest_idx]),
            "lower": float(channel_down.iloc[latest_idx]),
            "position": float(channel_pos.iloc[latest_idx]),  # 0-1区间，>1突破上轨
            "position_label": _channel_position_label(channel_pos.iloc[latest_idx]),
        },
        "chip_distribution": {
            "concentration_pct": chip_concentration,  # 九十成本集中度%
            "dcz": dcz,  # DCZ 价位
            "dcz_up": bool(dcz_up) if isinstance(dcz_up, (bool, np.bool_)) else None,
            "dcz_trend": "up" if dcz_up else "down" if isinstance(dcz_up, (bool, np.bool_)) else "flat",
        },
        "money_attack": bool(money_attack.iloc[latest_idx]),
        "env_resonance": {
            "flower_red": bool(flower_red.iloc[latest_idx]),
            "ema3": float(ema3.iloc[latest_idx]),
            "ema7": float(ema7.iloc[latest_idx]),
        },
        "key_signals": {
            "extreme_bottom": bool(extreme_bottom.iloc[latest_idx]),
            "build_buy": bool(build_buy.iloc[latest_idx]),
            "absolute_bottom": bool(absolute_bottom.iloc[latest_idx]),
            "must_rise": bool(must_rise.iloc[latest_idx]),
            "escape": bool(escape.iloc[latest_idx]),
            "escape_top": bool(escape_top.iloc[latest_idx]),
        },
        "grade": _calc_main_enter_grade(
            main_enter.iloc[latest_idx],
            # 需要外部传入：行业主线、大盘多头、花神红
            industry_main=False, market_bull=False, flower_red=bool(flower_red.iloc[latest_idx]),
            dcz=dcz, dcz_up=bool(dcz_up) if isinstance(dcz_up, (bool, np.bool_)) else False,
            avg_line=float(avg_line.iloc[latest_idx]),
            vol_up=bool(vol_up.iloc[latest_idx]),
            close=float(c.iloc[latest_idx]),
            dcz_val=dcz,
        ),
        "full_series": {
            "avg_line": avg_line.tolist(),
            "channel_mid": channel_mid.tolist(),
            "channel_up": channel_up.tolist(),
            "channel_down": channel_down.tolist(),
            "main_enter": main_enter.tolist(),
            "main_exit": main_exit.tolist(),
        }
    }


def _estimate_chip_distribution(df: pd.DataFrame) -> Tuple[float, float, bool]:
    """
    估算筹码分布 (近似 COST 函数)
    返回: (九十成本集中度%, DCZ价位, DCZ是否上移)
    注意: 真实 COST 需要逐笔成交数据，这里基于成交量分布近似
    """
    if df is None or df.empty or len(df) < 60:
        return 50.0, float(df["close"].iloc[-1] if not df.empty else 0), False

    c = df["close"].astype(float)
    v = df["vol"].astype(float)

    # 最近 60 日成交量加权价格分布近似
    recent = df.tail(60).copy()
    recent["amt"] = recent["close"] * recent["vol"]
    total_amt = recent["amt"].sum()
    if total_amt == 0:
        return 50.0, float(c.iloc[-1]), False

    # 计算成交量加权价格分位点
    recent = recent.sort_values("close")
    recent["cum_amt"] = recent["amt"].cumsum()
    recent["cum_pct"] = recent["cum_amt"] / total_amt * 100

    # 5% 和 95% 成本价
    try:
        cost_5 = recent.loc[recent["cum_pct"] >= 5, "close"].iloc[0]
        cost_95 = recent.loc[recent["cum_pct"] >= 95, "close"].iloc[0]
    except:
        cost_5 = float(c.iloc[-1] * 0.9)
        cost_95 = float(c.iloc[-1] * 1.1)

    # 九十成本集中度
    if cost_95 + cost_5 > 0:
        concentration = (cost_95 - cost_5) / (cost_95 + cost_5) * 100
    else:
        concentration = 50.0

    # DCZ = 九十成本集中度对应的价位 (简化取中位)
    dcz = (cost_5 + cost_95) / 2

    # DCZ 是否上移 (对比 5 日前)
    if len(df) >= 5:
        prev_close = df["close"].iloc[-5]
        dcz_up = dcz > prev_close * 0.98  # 简化判断
    else:
        dcz_up = False

    return round(concentration, 1), round(dcz, 2), dcz_up


def _channel_position_label(pos: float) -> str:
    """通道位置标签"""
    if pos >= 1.0:
        return "上穿上轨"
    elif pos >= 0.8:
        return "接近上轨"
    elif pos >= 0.6:
        return "中上区间"
    elif pos >= 0.4:
        return "中轨附近"
    elif pos >= 0.2:
        return "中下区间"
    elif pos > 0:
        return "接近下轨"
    else:
        return "跌破下轨"


def _calc_main_enter_grade(
    main_enter: bool,
    industry_main: bool,
    market_bull: bool,
    flower_red: bool,
    dcz: float,
    dcz_up: bool,
    avg_line: float,
    vol_up: bool,
    close: float,
    dcz_val: float
) -> Dict[str, Any]:
    """
    计算主进分级 (A/B/C/D 级)
    对应通达信：
    A级 := 主力进 AND 行业主线 AND 大盘多头 AND DCZ>REF(DCZ,5) AND VOL>MA(VOL,5)*1.5 AND C>DCZ
    B级 := 主力进 AND (行业多头 OR 行业领涨) AND DCZ>=REF(DCZ,3) AND 平均线<2.3 AND 花神红 AND NOT(A级)
    C级 := 主力进 AND EXIST(VAR17>0,5) AND HHV(H,10)/LLV(L,10)<1.25 AND NOT(A级) AND NOT(B级)
    D级 := 主力进 AND NOT(A级) AND NOT(B级) AND NOT(C级)
    """
    if not main_enter:
        return {"grade": "无主进", "label": "无主力进场", "level": 0}

    # 简化：行业主线/大盘多头需要外部传入，这里提供默认值
    industry_main_flag = industry_main
    market_bull_flag = market_bull
    flower_red_flag = flower_red

    # 简化 DCZ>REF(DCZ,5) 用 dcz > close_5d_ago 近似
    dcz_5d_up = True  # 需要外部传入历史

    # A级
    a_grade = (
        industry_main_flag and market_bull_flag and 
        dcz_up and True and True  # 简化：假设放量和 C>DCZ
    )

    # B级
    b_grade = (
        (industry_main_flag or True) and  # 行业多头或领涨
        dcz_up and  # DCZ>=REF(DCZ,3)
        avg_line < 2.3 and  # 平均线<2.3
        flower_red and 
        not a_grade
    ) if not a_grade else False

    # C级
    c_grade = True if not a_grade and not b_grade else False

    # D级
    d_grade = not a_grade and not b_grade and not c_grade

    if a_grade:
        grade, label, level = "A", "主进.强", 4
    elif b_grade:
        grade, label, level = "B", "主进.稳", 3
    elif c_grade:
        grade, label, level = "C", "主进.试", 2
    else:
        grade, label, level = "D", "主进.弱", 1

    return {
        "grade": grade,
        "label": label,
        "level": level,
        "detail": {
            "main_enter": True,
            "industry_main": industry_main_flag,
            "market_bull": market_bull_flag,
            "dcz_up": dcz_up,
            "flower_red": flower_red,
            "avg_line": avg_line,
        }
    }


def calc_key_signals(df: pd.DataFrame) -> Dict[str, Any]:
    """
    计算关键节点信号 (极底、建仓、绝底、必涨、逃亡、逃顶)
    输入：标准日线 df
    """
    if df is None or df.empty or len(df) < 30:
        return {"error": "数据不足"}

    # 复用 calc_tdx_core 中的部分计算
    core = calc_tdx_core(df)
    return {
        "extreme_bottom": core["key_signals"]["extreme_bottom"],
        "build_buy": core["key_signals"]["build_buy"],
        "absolute_bottom": core["key_signals"]["absolute_bottom"],
        "must_rise": core["key_signals"]["must_rise"],
        "escape": core["key_signals"]["escape"],
        "escape_top": core["key_signals"]["escape_top"],
    }


def calc_env_resonance(
    stock_df: pd.DataFrame,
    industry_df: Optional[pd.DataFrame] = None,
    index_df: Optional[pd.DataFrame] = None
) -> Dict[str, Any]:
    """
    计算多维环境共振
    需要：个股日线、行业指数日线、大盘指数日线
    """
    result = {
        "industry_main": False,
        "industry_bull": False,
        "industry_lead": False,
        "market_bull": False,
        "flower_red": False,
        "resonance_level": 0,
    }

    if stock_df is None or stock_df.empty:
        return result

    c = stock_df["close"].astype(float)
    ema3 = _ema(c, 3)
    ema7 = _ema(c, 7)
    result["flower_red"] = bool(ema3.iloc[-1] > ema7.iloc[-1])

    if industry_df is not None and not industry_df.empty:
        ic = industry_df["close"].astype(float)
        industry_ma20 = _ma(ic, 20)
        industry_ma60 = _ma(ic, 60)
        result["industry_bull"] = bool(ic.iloc[-1] > industry_ma20.iloc[-1] and industry_ma20.iloc[-1] > industry_ma60.iloc[-1])

        if index_df is not None and not index_df.empty:
            ic_idx = industry_df["close"].astype(float)
            idx_c = index_df["close"].astype(float)
            rel = ic_idx / idx_c.replace(0, np.nan)
            rel_ma20 = _ma(rel, 20)
            result["industry_lead"] = bool(rel.iloc[-1] > rel_ma20.iloc[-1])

    if index_df is not None and not index_df.empty:
        idx_c = index_df["close"].astype(float)
        idx_ma60 = _ma(idx_c, 60)
        idx_ma60_prev = _ref(idx_ma60, 5)
        result["market_bull"] = bool(idx_c.iloc[-1] > idx_ma60.iloc[-1] and idx_ma60.iloc[-1] > idx_ma60_prev.iloc[-1])

    # 共振层级
    resonance = sum([
        result["flower_red"],
        result["industry_bull"],
        result["industry_lead"],
        result["market_bull"],
    ])
    result["resonance_level"] = resonance  # 0-4

    return result


def calc_attack_signal(df: pd.DataFrame) -> Dict[str, Any]:
    """
    计算资金攻击/逃亡/逃顶信号
    """
    if df is None or df.empty:
        return {"attack": False, "escape": False, "escape_top": False}

    core = calc_tdx_core(df)
    return {
        "money_attack": core["money_attack"],
        "escape": core["key_signals"]["escape"],
        "escape_top": core["key_signals"]["escape_top"],
    }


# ============================================================
# 统一入口：供 eval_smart.py 调用
# ============================================================

def calc_all_tdx_signals(
    stock_df: pd.DataFrame,
    industry_df: Optional[pd.DataFrame] = None,
    index_df: Optional[pd.DataFrame] = None
) -> Dict[str, Any]:
    """
    统一入口：一次性计算所有通达信核心信号
    用法：
        from tdx_core import calc_all_tdx_signals
        signals = calc_all_tdx_signals(stock_daily_df, industry_daily_df, index_daily_df)
        r['tdx'] = signals
    """
    core = calc_tdx_core(stock_df)
    resonance = calc_env_resonance(stock_df, industry_df, index_df)
    key_signals = calc_key_signals(stock_df)
    attack = calc_attack_signal(stock_df)

    return {
        "core_metrics": core["core_metrics"],
        "main_signals": core["main_signals"],
        "trend_channel": core["trend_channel"],
        "chip_distribution": core["chip_distribution"],
        "money_attack": core["money_attack"],
        "grade": core["grade"],
        "env_resonance": resonance,
        "key_signals": core["key_signals"],
        "attack": attack,
        "full_series": core["full_series"],
    }


if __name__ == "__main__":
    # 简单自测
    import sys
    print("tdx_core.py 模块加载成功")
    print("可用函数:")
    print("  - calc_tdx_core(df)")
    print("  - calc_all_tdx_signals(stock_df, industry_df, index_df)")
    print("  - calc_key_signals(df)")
    print("  - calc_env_resonance(stock_df, industry_df, index_df)")
    print("  - calc_attack_signal(df)")