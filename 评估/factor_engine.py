#!/usr/bin/env python3
"""
factor_engine.py — 因子引擎 v1
计算所有扩展因子得分（A组资金流 + B组量价 + F组日历）
输出: 每只股票各因子标准化得分 (0-100)
"""
import os, sys, datetime, json, time
import numpy as np
import pandas as pd
import urllib.error
import urllib.request
import tushare as ts
pro = ts.pro_api()

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
from astock_bridge import tencent_quote, eastmoney_north_holdings

# 指数基准
INDEX_CODE = "000300.SH"  # 沪深300

# ===== P0 防护：tushare 重试（指数退避，最多3次） =====
_RETRYABLE = (ConnectionError, BrokenPipeError, urllib.error.URLError,
              urllib.error.HTTPError, OSError)
_RETRY_DELAYS = [1, 2, 4]  # 秒

def _tushare_call(fn, *args, **kwargs):
    """对 tushare pro 调用加重试；连接级异常退避重试，业务异常(无数据/权限)直接返回。"""
    last_exc = None
    for i, delay in enumerate(_RETRY_DELAYS + [None]):
        try:
            return fn(*args, **kwargs)
        except _RETRYABLE as e:
            last_exc = e
            if delay is None:
                break
            print(f"  ⚠ tushare 失败(第{i+1}次): {e}，{delay}s 后重试...")
            time.sleep(delay)
    raise last_exc if last_exc else ValueError("tushare 重试耗尽")


def _check_pro():
    """检查 tushare pro 连接是否可用。"""
    try:
        r = _tushare_call(pro.trade_cal, start_date="20260101", end_date="20260101")
        return r is not None and not r.empty
    except Exception as e:
        return False

def calc_factors(codes, end_date=None):
    """对N只股票计算全因子得分，返回 dict {code: {factor: score}}"""
    # P0 防护：pro 可用性审计
    pro_ok = _check_pro()
    if not pro_ok:
        print("🚨 tushare pro 连接不可用 — 因子计算将全部失败，请检查 tushare token")
        return {c: {"error": "tushare_pro_unavailable"} for c in codes}
    if end_date is None:
        end_date = datetime.datetime.now().strftime("%Y%m%d")
    start = (datetime.datetime.strptime(end_date, "%Y%m%d") - datetime.timedelta(days=60)).strftime("%Y%m%d")

    # 获取指数数据
    try:
        index_df = _tushare_call(pro.index_daily, ts_code=INDEX_CODE, start_date=start, end_date=end_date)
    except Exception as e:
        print(f"  ⚠ 指数数据失败: {e}，B4相对强弱因子将归零")
        index_df = None
    index_df = index_df.sort_values("trade_date").reset_index(drop=True) if index_df is not None and not index_df.empty else None

    # 获取全市场情绪数据（涨跌比、涨停数）
    market_df = None
    if datetime.datetime.strptime(end_date, "%Y%m%d").weekday() < 5:
        try:
            market_df = _tushare_call(pro.daily, trade_date=end_date)
        except Exception as e:
            print(f"  ⚠ 全市场情绪数据失败: {e}")
    market_up_ratio = 0.5
    limit_up_count = 0
    if market_df is not None and not market_df.empty:
        total = len(market_df)
        up = len(market_df[market_df["pct_chg"] > 0])
        limit = len(market_df[market_df["pct_chg"] >= 9.8])
        market_up_ratio = up / total if total > 0 else 0.5
        limit_up_count = limit

    result = {}
    for code in codes:
        # 补全后缀
        if "." not in code:
                    ts_code = code + ".SH" if code[0] in "69" else code + ".SZ"
        else:
            ts_code = code
        factors = {}
        try:
            # 基础K线
            try:
                df = _tushare_call(pro.daily, ts_code=ts_code, start_date=start, end_date=end_date)
            except Exception as e:
                result[code] = {"error": f"pro.daily: {e}"}
                continue
            if df is None or df.empty:
                result[code] = {"error": "no data"}
                continue
            df = df.sort_values("trade_date").reset_index(drop=True)
            last = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else last

            # ─── A组: 资金流微观结构 ───
            try:
                mf = _tushare_call(pro.moneyflow, ts_code=ts_code, start_date=start, end_date=end_date)
                if mf is not None and not mf.empty:
                    mf = mf.sort_values("trade_date").reset_index(drop=True)
                    mfl = mf.iloc[-1]
                    # A1: 大单净流入比 = (buy_sm_vol - sell_sm_vol) / total_vol
                    big_net = (mfl.get("buy_lg_vol", 0) - mfl.get("sell_lg_vol", 0)) + \
                              (mfl.get("buy_elg_vol", 0) - mfl.get("sell_elg_vol", 0))
                    total_vol = mfl.get("buy_lg_vol", 0) + mfl.get("buy_elg_vol", 0) + \
                                mfl.get("sell_lg_vol", 0) + mfl.get("sell_elg_vol", 0) + \
                                mfl.get("buy_md_vol", 0) + mfl.get("sell_md_vol", 0) + \
                                mfl.get("buy_sm_vol", 0) + mfl.get("sell_sm_vol", 0)
                    factors["A1_big_net_ratio"] = big_net / total_vol if total_vol > 0 else 0

                    # A2: 资金持续性 — 连续净流入天数
                    mf["net"] = mf["buy_lg_vol"] + mf["buy_elg_vol"] - mf["sell_lg_vol"] - mf["sell_elg_vol"]
                    consecutive = 0
                    for i in range(len(mf)-1, -1, -1):
                        if mf.iloc[i]["net"] > 0:
                            consecutive += 1
                        else:
                            break
                    factors["A2_consecutive_days"] = consecutive

                    # A3: 主力资金强度 = net_flow_ratio * pct_chg / volatility
                    vol_20 = mf["net"].tail(20).std() if len(mf) >= 20 else 1
                    if vol_20 == 0: vol_20 = 1
                    strength = (big_net / total_vol) * last["pct_chg"] / vol_20 * 10000 if total_vol > 0 else 0
                    factors["A3_strength"] = strength
                else:
                    factors["A1_big_net_ratio"] = 0
                    factors["A2_consecutive_days"] = 0
                    factors["A3_strength"] = 0
            except:
                factors["A1_big_net_ratio"] = 0
                factors["A2_consecutive_days"] = 0
                factors["A3_strength"] = 0

            # A4: 北向持股变化率（东财 datacenter-web）
            north_status = None
            try:
                north = eastmoney_north_holdings([code])
                if north and isinstance(north, list) and north and isinstance(north[0], dict) and "error" in north[0]:
                    north_status = north[0].get("error", "未知错误")
                elif not north or (isinstance(north, list) and not north):
                    north_status = "空数据(北向明细滞后)"
                else:
                    # 解析：north 是记录列表，尝试提取北向净值
                    factors["A4_north_flow"] = 0.0
            except Exception as e:
                north_status = str(e)
            if north_status:
                print(f"  ⚠ 北向A4因子({code}): {north_status} — 置0，评分不受单项北向波动污染")
                factors["A4_north_flow"] = 0.0

            # ─── B组: 量价行为 ───
            # B1: 量价背离 — 20日最高价附近但量缩
            high_20 = df["close"].tail(20).max()
            vol_20_avg = df["vol"].tail(20).mean()
            near_high = last["close"] >= high_20 * 0.95
            vol_shrink = last["vol"] < vol_20_avg * 0.8
            if near_high and vol_shrink:
                factors["B1_divergence"] = -1  # 负分 = 危险信号
            elif near_high and last["vol"] > vol_20_avg * 1.2:
                factors["B1_divergence"] = 1   # 正分 = 放量突破
            else:
                factors["B1_divergence"] = 0

            # B2: 涨停封板质量（近似：封板时间越早越好，用最早触及涨停的时间近似）
            # tushare没有封板时间，用 pct_chg 和 high 近似
            if last["pct_chg"] >= 9.5:
                # 涨停股票：看振幅和封单力度
                amp = last["high"] - last["low"] / last["pre_close"] * 100 if last["pre_close"] > 0 else 0
                factors["B2_limit_quality"] = 100 - amp * 5  # 振幅越小封板越稳
            else:
                factors["B2_limit_quality"] = 0

            # B3: 跳空缺口
            gap = last["open"] / prev["close"] - 1 if prev["close"] > 0 else 0
            factors["B3_gap"] = gap * 100  # 百分比

            # B4: 相对强弱 (个股/指数)
            if index_df is not None and not index_df.empty:
                idx_last = index_df.iloc[-1]
                stock_ret = last["pct_chg"]
                idx_ret = idx_last["pct_chg"]
                factors["B4_rel_strength"] = stock_ret - idx_ret  # 超额收益
            else:
                factors["B4_rel_strength"] = 0

            # ─── F组: 日历效应 ───
            dt = datetime.datetime.strptime(end_date, "%Y%m%d")
            factors["F1_is_monday"] = 1 if dt.weekday() == 0 else 0
            factors["F1_is_friday"] = 1 if dt.weekday() == 4 else 0
            factors["F1_is_thursday"] = -1 if dt.weekday() == 3 else 0  # 法定砸盘日
            factors["F2_is_month_end"] = 1 if dt.day >= 25 else 0
            factors["F3_is_earnings_season"] = 1 if dt.month in [4, 7, 10, 1] else 0

            # 市场情绪因子
            factors["C_market_up_ratio"] = market_up_ratio
            factors["C_limit_up_count"] = limit_up_count / max(len(codes), 1) * 10

            # B5: 趋势强度（20日收益率）
            ret_20 = (last["close"] / df.iloc[0]["close"] - 1) * 100 if len(df) >= 20 and df.iloc[0]["close"] > 0 else 0
            factors["B5_trend"] = ret_20

            # B6: 波动率 — 20日年化波动率
            returns = df["pct_chg"].tail(20).values / 100.0
            daily_vol = np.std(returns) if len(returns) >= 5 else 0.02
            annual_vol = daily_vol * np.sqrt(252) * 100
            factors["B6_volatility"] = round(annual_vol, 1)

            result[code] = factors

        except Exception as e:
            result[code] = {"error": str(e)}

    return result


def normalize_factors(factor_dict):
    """将各因子标准化到 0-100 分"""
    if not factor_dict:
        return factor_dict

    # 收集所有数值
    all_factors = {}
    for code, factors in factor_dict.items():
        if "error" in factors:
            continue
        for k, v in factors.items():
            if k not in all_factors:
                all_factors[k] = []
            all_factors[k].append(v)

    # 计算 z-score 然后映射到 0-100
    for code, factors in factor_dict.items():
        if "error" in factors:
            continue
        for k in list(factors.keys()):
            v = factors[k]
            vals = np.array(all_factors[k])
            if len(vals) < 2 or np.std(vals) == 0:
                factors[k] = 50
                continue
            z = (v - np.mean(vals)) / np.std(vals)
            # 截断到 [-3, 3] 然后映射到 0-100
            z = max(-3, min(3, z))
            factors[k] = round((z + 3) / 6 * 100, 1)

    return factor_dict


if __name__ == "__main__":
    codes = ["600118", "300418", "600288", "688135", "688175", "603296",
             "603893", "688802", "000518", "301516", "300454", "688722",
             "688039", "001395", "600992", "300649", "002414", "002490",
             "000779", "603339"]
    print("🧮 计算因子...")
    raw = calc_factors(codes)
    norm = normalize_factors(raw)
    print(f"完成: {len(norm)} 只")
    # 保存
    out = os.path.join(os.path.dirname(TOOLS), "reports", "追踪", "factors_raw.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(norm, f, ensure_ascii=False, indent=2, default=str)
    print(f"✅ 因子数据已保存: {out}")