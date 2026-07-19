#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能合并评估器 — 八维度 + a-stock-data实时行情 + 周线分析 + 通达信主力全景 + ZSCORE四维共振 + 反身性三阶段

去冗余 v2:
- 参考系统 generate_report() 中的反身性/周线/ZSCORE 章节被 strip 掉，避免双重输出
- _calc_sbi_fixed() 修复 moneyflow 缺失时 capital_factor=0 导致 SBI 偏移问题
"""

import os
import sys
import re
import json
import argparse
import numpy as np
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

REF_SYSTEM = r'C:\Users\Admin\Documents\TraeSpace\评估系统\stock_eval_system'
sys.path.insert(0, REF_SYSTEM)

import tushare as ts
ts.set_token('3de9976db504a798ec235a8cfaa5292ba7b5cb7f20957d6929e04287')
pro = ts.pro_api()

from 粗评报告模板_v2 import (
    evaluate_batch, generate_report, load_zscore_data, match_zscore,
    calc_zscore_resonance, calc_reflexivity, detect_bubble_signals
)
from astock_bridge import tencent_quote
from weekly_analysis import analyze_weekly
from tdx_core import calc_all_tdx_signals

OUTPUT_DIR = os.path.join(ROOT, 'reports', '粗评')


# ============================================================
# SBI 修复版 — 解决 moneyflow 缺失时 capital_factor=0 导致象限反转
# ============================================================

def _calc_sbi_fixed(df, mf_df):
    """
    修复版 SBI 计算：
    - 当 mf_df 为空时，capital_factor 用价格动量均值填充而非 0
    - 保留原始 5 因子加权结构不变
    """
    if df is None or df.empty or len(df) < 20:
        return 0, {}

    import pandas as pd
    close = pd.to_numeric(df['close'], errors='coerce')
    vol = pd.to_numeric(df['vol'], errors='coerce')
    pct_chg = pd.to_numeric(df['pct_chg'], errors='coerce')

    ret_5d = pct_chg.head(5).sum()
    ret_20d_avg = pct_chg.head(20).mean() * 5
    # 近似换手率（假设流通股本 = close * 1e8 简化估算）
    turnover = vol / (close * 1e8)
    avg_turnover_20 = turnover.head(20).mean()
    latest_turnover = turnover.iloc[0]

    factors = {}

    # 1. 价格动量溢价 (25%)
    if abs(ret_20d_avg) > 0.1:
        pm_premium = (ret_5d - ret_20d_avg) / abs(ret_20d_avg)
    else:
        pm_premium = ret_5d / 10
    factors['price_momentum'] = max(-1, min(1, pm_premium))

    # 2. 换手率溢价 (20%)
    if avg_turnover_20 > 0:
        to_premium = (latest_turnover - avg_turnover_20) / avg_turnover_20
    else:
        to_premium = 0
    factors['turnover_premium'] = max(-1, min(1, to_premium))

    # 3. 资金流入强度 (25%) — 修复：空 mf 时用动量均值兜底
    if mf_df is not None and not mf_df.empty and 'net_mf_amount' in mf_df.columns:
        mf_5d = mf_df.head(5)
        net_mf = mf_5d['net_mf_amount'].sum()
        amt_5d = 0
        if 'buy_amount' in mf_5d.columns and 'sell_amount' in mf_5d.columns:
            amt_5d = mf_5d['buy_amount'].sum() + mf_5d['sell_amount'].sum()
        capital_factor = net_mf / amt_5d if amt_5d > 0 else 0
    else:
        # 兜底：用价格动量因子均值近似，避免直接归零
        capital_factor = factors['price_momentum']
    factors['capital_inflow'] = max(-1, min(1, capital_factor))

    # 4. 情绪扩散指数 (15%)
    if len(vol) >= 10:
        vol_ma10 = vol.head(10).mean()
        high_vol_days = sum(vol.head(10) > vol_ma10 * 1.5)
        diffusion = (high_vol_days / 10) * 2 - 1
    else:
        diffusion = 0
    factors['sentiment_diffusion'] = max(-1, min(1, diffusion))

    # 5. 量价背离 (15%)
    latest_pct = pct_chg.iloc[0]
    latest_vol_ratio = vol.iloc[0] / vol.iloc[1:6].mean() if len(vol) >= 6 else 1.0
    if latest_pct > 1 and latest_vol_ratio > 1.2:
        vp_divergence = 1.0
    elif latest_pct > 1 and latest_vol_ratio < 0.8:
        vp_divergence = -0.5
    elif latest_pct < -1 and latest_vol_ratio > 1.5:
        vp_divergence = -1.0
    else:
        vp_divergence = 0
    factors['vol_price_divergence'] = vp_divergence

    sbi = (
        factors['price_momentum'] * 0.25 +
        factors['turnover_premium'] * 0.20 +
        factors['capital_inflow'] * 0.25 +
        factors['sentiment_diffusion'] * 0.15 +
        factors['vol_price_divergence'] * 0.15
    ) * 100

    return max(-100, min(100, round(sbi, 1))), factors


# ============================================================
# Markdown 去冗：移除参考系统中的重复章节
# ============================================================

def strip_ref_sections(md: str) -> str:
    """
    从参考系统 generate_report() 产出的 md 中移除：
    - 反身性四象限分析区块（## 🔄 反身性四象限分析 ... 下一节前）
    - 周线趋势分析区块（## 📈 周线趋势分析 ... 下一节前）
    - 板块ZSCORE比价分析区块（## 📐 板块ZSCORE比价分析 ... 下一节前）
    """
    sections_to_strip = [
        r'^## \U0001f504 反身性四象限分析\n',
        r'^## \U0001f4c8 周线趋势分析\n',
        r'^## \U0001f4d0 板块ZSCORE比价分析\n',
    ]
    section_markers = ['🔄 反身性四象限分析', '📈 周线趋势分析', '📐 板块ZSCORE比价分析']

    result = []
    skip_until_next_section = False
    lines = md.split('\n')

    for i, line in enumerate(lines):
        if skip_until_next_section:
            # 遇到新的 ## 章节则停止跳过
            if re.match(r'^## ', line):
                skip_until_next_section = False
                result.append(line)
            continue

        # 检查是否命中要移除的章节
        for marker in section_markers:
            if marker in line and re.match(r'^## ', line):
                skip_until_next_section = True
                break
        else:
            result.append(line)

    # 清理多余空行（连续3行以上空行→1行）
    cleaned = re.sub(r'\n{4,}', '\n\n\n', '\n'.join(result))
    return cleaned


# ============================================================
# 解析 / 格式化函数（各层独立，不依赖参考系统输出）
# ============================================================

def _resolve_to_codes(stock_list):
    """中文名/简写代码 → 完整 ts_code"""
    try:
        basic_df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,name')
        name2code = {r['name']: r['ts_code'] for _, r in basic_df.iterrows()}
        short2code = {r['ts_code'].split('.')[0]: r['ts_code'] for _, r in basic_df.iterrows()}
    except Exception as e:
        raise RuntimeError(f"无法拉取 tushare stock_basic: {e}") from e

    out, unresolved = [], []
    for x in stock_list:
        x = x.strip() if isinstance(x, str) else str(x)
        if not x:
            continue
        if x in name2code.values():
            out.append(x); continue
        if x.isdigit() and len(x) == 6 and x in short2code:
            out.append(short2code[x]); continue
        if x in name2code:
            out.append(name2code[x]); continue
        m = [v for k, v in name2code.items() if x in k]
        if m:
            out.append(m[0]); continue
        unresolved.append(x)
    if unresolved:
        raise RuntimeError(f"以下标的无法解析为 ts_code: {unresolved!r}")
    return out


def _format_zscore_section(results, zscore_df, end_date, verbose=True):
    """生成 ZSCORE 四维共振章节 markdown"""
    md = "\n---\n\n## 📊 ZSCORE 四维共振层 (核心 15%权重)\n\n"
    md += "> 算法来源: 评估系统板块热度观察模块 ZSCORE四维共振模型\n"
    md += "> 核心: 天时(板块ZSCORE位置)/地利(主线题材)/人和(资金量能)/技术(个股趋势共振)\n\n"

    if zscore_df is None or zscore_df.empty:
        md += "\n> ⚠ ZSCORE板块数据不可用（数据管道未就绪）\n\n"
        return md

    md += "| 股票 | 行业 | 匹配板块 | Z综合 | 信号 | 天时 | 地利 | 人和 | 技术 |\n"
    md += "|------|------|----------|-------|------|------|------|------|------|\n"

    for r in results:
        try:
            basic = pro.stock_basic(ts_code=r['code'], fields='industry')
            industry = basic['industry'].iloc[0] if not basic.empty else '未知'
        except:
            industry = '未知'

        stock_df = None
        try:
            d = pro.daily(ts_code=r['code'], start_date='20250101', end_date=end_date)
            if not d.empty:
                d = d.sort_values('trade_date').reset_index(drop=True)
                stock_df = d
        except:
            pass

        try:
            zr = calc_zscore_resonance(industry, zscore_df, stock_df=stock_df)
        except:
            zr = {'dimensions': {}, 'signals': [], 'zscore_info': {}, 'score': 50}

        dims = zr.get('dimensions', {})
        zs = zr.get('zscore_info', {})
        sigs = zr.get('signals', [])
        md += (f"| {r.get('name', '?')} {r.get('code', '')} | {industry} | "
                f"{zs.get('matched_board', '—')} | {zs.get('z_composite', '—')} | "
                f"{', '.join(sigs) if sigs else '—'} | "
                f"{'✅' if dims.get('天时') else '⚪'} | "
                f"{'✅' if dims.get('地利') else '⚪'} | "
                f"{'✅' if dims.get('人和') else '⚪'} | "
                f"{'✅' if dims.get('技术') else '⚪'} |\n")
    return md


def _format_reflexivity_section(results, end_date, verbose=True):
    """生成 反身性三阶段章节 markdown"""
    md = "\n---\n\n## 🔄 反身性三阶段诊断层 (核心 15%权重)\n\n"
    md += "> 算法来源: Soros反身性理论 + SBI主流偏见指数 + 四象限模型 (v5.0)\n"
    md += "> 核心: 主流偏见指数(SBI -100~+100) × 价格趋势(-1~+1) → 四象限定位\n\n"

    md += "### 反身性诊断结果\n\n"
    md += "| 股票 | 阶段 | SBI指数 | 价格趋势 | 象限 | 反身性强度 | 核心信号 | 操作建议 |\n"
    md += "|------|------|---------|----------|------|------------|----------|----------|\n"

    for r in results:
        try:
            d = pro.daily(ts_code=r['code'], start_date='20240101', end_date=end_date)
            mf = None
            try:
                mf = pro.moneyflow(ts_code=r['code'], start_date='20240101', end_date=end_date)
            except:
                mf = None
            holder_data = None
            try:
                h = pro.stk_holdernumber(ts_code=r['code'], enddate=end_date)
                holder_data = {'holder_pct': h['holder_pct'].iloc[0]} if not h.empty else None
            except:
                holder_data = None

            if d is None or d.empty:
                md += f"| {r.get('name', '?')} {r.get('code', '')} | 数据不足 | — | — | — | — | — | 数据不足 |\n"
                continue

            d = d.sort_values('trade_date').reset_index(drop=True)
            ref = calc_reflexivity(d, mf_df=mf, holder_data=holder_data)

            stage = ref.get('stage', 0)
            stage_name = ref.get('stage_name', '未知')
            quadrant = ref.get('quadrant', 'Q0')
            sbi = ref.get('sbi', 0)
            pt = ref.get('price_trend', 0)
            strength = ref.get('reflexivity_strength', 0)
            op = ref.get('operation', '观望')
            bubble = ref.get('bubble_signals', [])

            se = {'1': '🟢', '2': '🟡', '3': '🔴', '4': '🔵'}.get(str(stage), '⚪')
            qe = {'Q1': '🟢', 'Q2': '🟡', 'Q3': '🔴', 'Q4': '🔵'}.get(quadrant, '⚪')

            md += (f"| {r.get('name', '?')} {r.get('code', '')} | "
                    f"{se}{stage_name} | {sbi:+.0f} | {pt:+.2f} | "
                    f"{qe}{quadrant} | {strength:+.0f} | "
                    f"{'; '.join(bubble) if bubble else '—'} | {op} |\n")
        except Exception as e:
            md += f"| {r.get('name', '?')} {r.get('code', '')} | 计算失败 | — | — | — | — | — | {str(e)[:30]} |\n"

    # 泡沫风险预警
    md += "\n### 反身性泡沫风险预警\n\n"
    md += "| 股票 | 顶部背离 | 买盘枯竭 | 估值泡沫 | 筹码分散 | 风险等级 |\n"
    md += "|------|----------|----------|----------|----------|----------|\n"
    for r in results:
        try:
            d = pro.daily(ts_code=r['code'], start_date='20240101', end_date=end_date)
            mf = None
            try:
                mf = pro.moneyflow(ts_code=r['code'], start_date='20240101', end_date=end_date)
            except:
                mf = None
            if d is not None and not d.empty:
                d = d.sort_values('trade_date').reset_index(drop=True)
                bf = detect_bubble_signals(d, mf_df=mf)
                signals_str = ' / '.join(bf) if bf else '无'
                risk = '高' if len(bf) >= 2 else ('中' if len(bf) == 1 else '低')
                md += f"| {r.get('name', '?')} {r.get('code', '')} | {signals_str} | — | — | — | {risk} |\n"
            else:
                md += f"| {r.get('name', '?')} {r.get('code', '')} | 数据不足 | — | — | — | — |\n"
        except:
            md += f"| {r.get('name', '?')} {r.get('code', '')} | — | — | — | — | — |\n"
    return md


def _format_tdx_section(results):
    """生成 通达信主力全景章节 markdown"""
    md = "\n---\n\n## 🎯 通达信主力全景层 (核心 35%权重)\n\n"
    md += "> 算法来源: 通达信《主力全景主图系统 V3.9》核心算法 Python 移植\n"
    md += "> 核心: 主力资金分级(A/B/C/D) + 筹码分布(DCZ/九十成本) + 趋势决策通道 + 资金攻击/逃亡信号\n\n"

    # 主进分级
    md += "### 主进分级\n\n"
    md += "| 股票 | 主进信号 | 分级标签 | 环境共振 | 资金攻击 |\n"
    md += "|------|----------|----------|----------|----------|\n"
    for r in results:
        tdx = r.get('tdx', {})
        if not tdx or 'error' in tdx:
            md += f"| {r.get('name', '?')} {r.get('code', '')} | 数据异常 | - | - | - |\n"
            continue
        grade_info = tdx.get('grade', {})
        main_sig = '✅ 主力进' if tdx.get('main_signals', {}).get('main_enter') else '❌ 主力退'
        res = tdx.get('env_resonance', {})
        lv = res.get('resonance_level', 0)
        desc = ['无共振', '单一共振', '双重共振', '三重共振', '四重共振'][min(lv, 4)]
        md += (f"| {r.get('name', '?')} {r.get('code', '')} | {main_sig} | "
                f"**{grade_info.get('grade', '-')}级·{grade_info.get('label', '-') or '-'}** "
                f"| {desc} | {'✅ 攻击' if tdx.get('money_attack', False) else '❌'} |\n")

    # 筹码分布
    md += "\n### 筹码分布分析\n\n"
    md += "| 股票 | DCZ | DCZ趋势 | 九十成本集中% | 散户状态 | 筹码解读 |\n"
    md += "|------|-----|---------|---------------|----------|----------|\n"
    for r in results:
        tdx = r.get('tdx', {})
        if not tdx or 'error' in tdx:
            continue
        chip = tdx.get('chip_distribution', {})
        conc = chip.get('concentration_pct', '-')
        if isinstance(conc, (int, float)):
            state = "集中" if conc > 60 else ("中性" if conc > 40 else "分散")
        else:
            state = "-"
        md += (f"| {r.get('name', '?')} {r.get('code', '')} | {chip.get('dcz', '-')} | "
                f"{chip.get('dcz_trend', '-')} | {conc}% | {state} | "
                f"{'主力强力吸筹' if chip.get('dcz_up') else '散户分散'} |\n")

    # 趋势决策通道
    md += "\n### 趋势决策通道\n\n"
    md += "| 股票 | 当前价 | 中轨 | 上轨 | 下轨 | 通道位置 | 操作提示 |\n"
    md += "|------|--------|------|------|------|----------|----------|\n"
    for r in results:
        tdx = r.get('tdx', {})
        if not tdx or 'error' in tdx:
            continue
        ch = tdx.get('trend_channel', {})
        pos = ch.get('position', 0)
        if pos >= 1:
            hint = "趋势加速,警惕短期回踩"
        elif pos <= 0:
            hint = "超卖反弹机会"
        elif pos > 0.8:
            hint = "接近上轨,警惕回踩"
        elif pos < 0.2:
            hint = "接近下轨,关注支撑"
        else:
            hint = "通道中轨附近震荡"
        price = r.get('tencent', {}).get('price', 0)
        if not isinstance(price, (int, float)):
            price = 0
        md += (f"| {r.get('name', '?')} {r.get('code', '')} | ¥{price:.2f} | "
                f"{ch.get('mid', '-')} | {ch.get('upper', '-')} | {ch.get('lower', '-')} | "
                f"{ch.get('position_label', '-')} | {hint} |\n")

    # 多维环境共振
    md += "\n### 多维环境共振\n\n"
    md += "| 股票 | 花神红 | 行业多头 | 行业领涨 | 大盘多头 | 共振层级 |\n"
    md += "|------|--------|----------|----------|----------|----------|\n"
    for r in results:
        tdx = r.get('tdx', {})
        if not tdx or 'error' in tdx:
            continue
        res = tdx.get('env_resonance', {})
        lv = res.get('resonance_level', 0)
        desc = ['无共振', '单一共振', '双重共振', '三重共振', '四重共振'][min(lv, 4)]
        md += (f"| {r.get('name', '?')} {r.get('code', '')} | "
                f"{'🟢' if res.get('flower_red') else '⚪'} | "
                f"{'🟢' if res.get('industry_bull') else '⚪'} | "
                f"{'🟢' if res.get('industry_lead') else '⚪'} | "
                f"{'🟢' if res.get('market_bull') else '⚪'} | {desc} |\n")

    return md


def _format_weekly_section(results):
    """生成 周线技术分析章节 markdown"""
    md = "\n---\n\n## 📈 周线技术分析层 (中长期)\n\n"
    md += "> 注: 即使日内涨停封死无法买入, **周线信号决定值不值得加入自选股观察池**\n\n"
    md += "| 股票 | 总分 | 等级 | 周趋势 | 均线 | 位置(12周) | 量能 | MACD | 趋势 |\n"
    md += "|------|------|------|--------|------|------------|------|------|------|\n"
    for r in results:
        wk = r.get('weekly_ext') or {}
        if not wk or 'error' in wk:
            continue
        ma = wk.get('ma', {})
        pos = wk.get('position', {})
        vol = wk.get('volume', {})
        macd = wk.get('macd', {})
        trd = wk.get('trend', {})
        md += (f"| **{r.get('name', '?')}** | **{wk['total_score']}**/200 | **{wk['grade']}级** | "
                f"{wk['trend_label']} | {ma.get('detail', '-') or '-'} ({ma.get('score', 0)}/45) | "
                f"{pos.get('zone', '-') or '-'} ({pos.get('position_pct', '-')}%) | "
                f"{vol.get('detail', '-') or '-'} | "
                f"{macd.get('detail', '-') or '-'} ({macd.get('score', 0)}/55) | "
                f"{trd.get('detail', '-') or '-'} |\n")

    md += "\n**解读**:\n"
    for r in results:
        wk = r.get('weekly_ext') or {}
        if not wk or 'error' in wk:
            continue
        n = r.get('name', '?')
        grade = wk.get('grade')
        label = wk.get('trend_label')
        if grade in ('S', 'A'):
            md += f"- **{n}**: 周线**{wk['total_score']}/200** {label} — 中长期强势, **值得加入自选股观察池**\n"
            if '金叉' in wk.get('macd', {}).get('detail', ''):
                md += f"  - ✅ **周线MACD金叉**: 中期趋势反转买点出现\n"
        elif grade == 'B':
            md += f"- **{n}**: 周线**{wk['total_score']}/200** {label} — 中长期偏强, 可持有观察\n"
        elif grade == 'C':
            md += f"- **{n}**: 周线**{wk['total_score']}/200** {label} — 中长期震荡, 不推荐中期建仓\n"
        else:
            md += f"- **{n}**: 周线**{wk['total_score']}/200** {label} — 中长期弱势, 避免\n"
    return md


def _format_tencent_section(results):
    """生成 a-stock-data 实时行情章节 markdown"""
    md = "\n---\n\n## 📡 a-stock-data 实时行情叠加层\n\n"
    md += "> 数据来源: 腾讯财经 qt.gtimg.cn (不封IP, 实时更新)\n\n"
    md += "| 股票 | 现价 | 涨跌 | 振幅% | PE(TTM) | PB | 量比 | 换手% | 涨停价 | 跌停价 | 市值(亿) |\n"
    md += "|------|------|------|-------|---------|----|------|--------|--------|--------|----------|\n"
    for r in results:
        if 'tencent' not in r:
            continue
        q = r['tencent']
        md += (f"| **{q.get('name', '?')}** {r.get('code', '')} "
                f"| ¥{q.get('price', 0):.2f} | {q.get('change_pct', 0):+.2f}% | "
                f"{q.get('amplitude_pct', 0):.2f}% | {q.get('pe_ttm', 0):.1f}x | "
                f"{q.get('pb', 0):.2f}x | {q.get('vol_ratio', 0):.2f} | "
                f"{q.get('turnover_pct', 0):.2f}% | ¥{q.get('limit_up', 0):.2f} | "
                f"¥{q.get('limit_down', 0):.2f} | {q.get('mcap_yi', 0):.0f} |\n")
    md += "\n**a-stock-data 覆盖了评估中心原本拿不到的 4 个维度**:\n"
    md += "1. **振幅%** — 衡量当日波动率，>3% 即为高波动\n"
    md += "2. **量比** — 当前成交量 vs 最近5日均量，>1.5 即放量\n"
    md += "3. **涨跌停价** — T+1止损分层的关键参考\n"
    md += "4. **实时 PE/PB** — 比 tushare 的 daily_basic(昨收) 更接近当前交易价\n"
    return md


# ============================================================

def _format_chip_section(results):
    md = "\n---\n\n## \U0001f4ca 筹码面分析\n\n"
    md += "> 股东户数变化趋势判断筹码集中度\n\n"
    md += "| 股票 | 股东户数 | 变化% | 趋势 | 判断 |\n"
    md += "|------|----------|-------|------|------|\n"
    for r in results:
        if not r.get("code"): continue
        holder = r.get("holder_data", {})
        if not holder:
            try:
                h = pro.stk_holdernumber(ts_code=r["code"], start_date="20250101", end_date=datetime.now().strftime("%Y%m%d"))
                if h is not None and not h.empty:
                    h = h.sort_values("ann_date", ascending=False)
                    holder = {"count": int(h.iloc[0].get("holder_num", 0)),
                              "change_pct": float(h.iloc[0].get("change_pct", 0)) if len(h) > 1 else 0}
                    r["holder_data"] = holder
            except: pass
        if not holder:
            md += f"| {r.get('name', '?')} | — | — | — | 无数据 |\n"
            continue
        cnt, chg = holder["count"], holder["change_pct"]
        if chg > 8: t, j = "\U0001f4c9分散", "筹码发散主力出货\u26a0\ufe0f"
        elif chg > 3: t, j = "\u27a1\ufe0f略分散", "筹码略发散正常波动"
        elif chg > -3: t, j = "\u27a1\ufe0f稳定", "筹码稳定中性"
        elif chg > -8: t, j = "\U0001f4c8集中", "筹码集中温和吸筹\U0001f48e"
        else: t, j = "\U0001f4c8大幅集中", "筹码迅速集中主力扫货\U0001f525"
        md += f"| {r.get('name', '?')} | {cnt:,} | {chg:+.1f}% | {t} | {j} |\n"
    return md

def _format_stop_loss_section(results):
    md = "\n---\n\n## \U0001f6e1\ufe0f T+1分层止损与盈亏比\n\n"
    md += "| 股票 | 现价 | 目标价 | 首日-12% | 次日ATR | 常态-8% | 盈亏比 |\n"
    md += "|------|------|--------|----------|---------|---------|--------|\n"
    for r in results:
        code, name = r.get("code", ""), r.get("name", "?")
        q = r.get("tencent", {})
        price = q.get("price", 0)
        if price <= 0:
            md += f"| {name} | — | — | — | — | — | — |\n"
            continue
        atr = price * 0.05
        try:
            d = pro.daily(ts_code=code, start_date="20240601", end_date=datetime.now().strftime("%Y%m%d"))
            if d is not None and not d.empty:
                d = d.sort_values("trade_date").reset_index(drop=True)
                d["tr"] = np.maximum(d["high"] - d["low"], np.maximum(abs(d["high"] - d["close"].shift(1)), abs(d["low"] - d["close"].shift(1))))
                atr = float(d["tr"].tail(20).mean())
        except: pass
        if atr <= 0: atr = price * 0.05
        sd1 = round(price * 0.88, 2); satr = round(price - atr * 1.5, 2); sn = round(price * 0.92, 2)
        tgt = round(price + atr * 2.5, 2)
        rr = round((tgt - price) / (price - sn), 1) if price > sn else 0
        lu = q.get("limit_up", 0)
        if lu > 0 and price >= lu * 0.995:
            md += f"| {name} \U0001f6a8 | \u00a5{price:.2f} | \u00a5{tgt:.2f} | \u00a5{sd1:.2f} | \u00a5{satr:.2f} | \u00a5{sn:.2f} | \U0001f6ab涨停 |\n"
            continue
        md += f"| {name} | \u00a5{price:.2f} | \u00a5{tgt:.2f} | \u00a5{sd1:.2f} | \u00a5{satr:.2f} | \u00a5{sn:.2f} | {rr}:1 |\n"
    return md
# 主入口
# ============================================================

def run_smart_eval(stock_list, title=None, output_dir=None, verbose=True):
    """智能合并评估主入口"""
    if output_dir is None:
        output_dir = OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)

    if title is None:
        title = f"智能合并评估_{len(stock_list)}只_{datetime.now().strftime('%Y%m%d_%H%M')}"

    if verbose:
        print(f"\n{'='*60}")
        print(f"智能合并评估 — 八维度 + a-stock-data + 周线 + ZSCORE + 反身性 + 通达信 (去冗v2)")
        print(f"{'='*60}\n")

    # 回退到最近交易日
    end_date = datetime.now().strftime('%Y%m%d')
    try:
        cal_df = pro.trade_cal(exchange='SSE',
                               start_date=(datetime.now() - timedelta(days=10)).strftime('%Y%m%d'),
                               end_date=end_date, is_open='1')
        if cal_df is not None and not cal_df.empty:
            last_open = sorted(cal_df['cal_date'].tolist())[-1]
            if last_open != end_date:
                if verbose:
                    print(f"⏰ 注意: 今天 {end_date} 是非交易日, 回退到最近交易日 {last_open}\n")
                end_date = last_open
    except Exception as e:
        if verbose:
            print(f"⚠ 交易日历检查失败: {e}")

    # 阶段1: tushare八维度评估
    if verbose:
        print("阶段 1/5: tushare 八维度评估...")
    stock_list_resolved = _resolve_to_codes(stock_list)
    if verbose and stock_list_resolved != stock_list:
        print(f"  代码映射: {list(zip(stock_list, stock_list_resolved))}")

    results, meta = evaluate_batch(stock_list_resolved, lookback_days=90, end_date=end_date, verbose=verbose)

    # ★ 修复反身性 SBI：对每只股票用 _calc_sbi_fixed 覆写
    if verbose:
        print("  ★ 修复反身性 SBI (moneyflow 缺失兜底)...")
    for r in results:
        if 'code' not in r:
            continue
        try:
            d = pro.daily(ts_code=r['code'], start_date='20240101', end_date=end_date)
            mf = None
            try:
                mf = pro.moneyflow(ts_code=r['code'], start_date='20240101', end_date=end_date)
            except:
                mf = None
            if d is not None and not d.empty:
                d = d.sort_values('trade_date').reset_index(drop=True)
                # 只覆写 SBI，不重算整个反身性（反身性象限已在 evaluate_batch 中算好）
                sbi_fixed, factors = _calc_sbi_fixed(d, mf)
                r['reflexivity_sbi'] = sbi_fixed
                # 同时更新 results 中 evaluate_batch 产出的其他 SBI 相关字段
                if 'reflexivity_score' in r:
                    r['reflexivity_sbi'] = sbi_fixed
        except:
            pass

    # 阶段2: a-stock-data实时行情 + 周线分析
    if verbose:
        print("阶段 2/5: a-stock-data 实时行情 + 周线分析...")
    pure_codes = [r['code'].split(".")[0] if "." in r['code'] else r['code']
                  for r in results if 'code' in r]
    tencent_quotes = tencent_quote(pure_codes)

    for r in results:
        if 'code' not in r:
            continue
        pure = r['code'].split(".")[0] if "." in r['code'] else r['code']
        if pure in tencent_quotes:
            q = tencent_quotes[pure]
            r['tencent'] = q
            r['tencent_pe'] = q.get('pe_ttm', 0)
            r['tencent_pb'] = q.get('pb', 0)
            r['tencent_amplitude'] = q.get('amplitude_pct', 0)
            r['tencent_vol_ratio'] = q.get('vol_ratio', 0)
            r['tencent_limit_up'] = q.get('limit_up', 0)
            r['tencent_limit_down'] = q.get('limit_down', 0)
            r['tencent_mcap_yi'] = q.get('mcap_yi', 0)
        r['weekly_ext'] = analyze_weekly(r['code'], end_date=end_date)

    # 阶段3: 通达信主力全景
    if verbose:
        print("阶段 3/5: 通达信主力全景层计算...")
    for r in results:
        if 'code' not in r:
            continue
        try:
            d = pro.daily(ts_code=r['code'], start_date='20240101', end_date=end_date)
            if not d.empty:
                d = d.sort_values('trade_date').reset_index(drop=True)
                tdx_signals = calc_all_tdx_signals(d)
                r['tdx'] = tdx_signals
        except Exception as e:
            if verbose:
                print(f"  ⚠ {r.get('name', r.get('code'))} 通达信计算失败: {e}")
            r['tdx'] = {'error': str(e)}

    # 实时行情速览面板
    if verbose:
        print("\n┌" + "─" * 80 + "┐")
        print("│ a-stock-data 实时行情叠加层 (腾讯 qt.gtimg.cn · 不封IP)            │")
        print("├" + "─" * 80 + "┤")
        for r in results:
            if 'tencent' not in r:
                print(f"│ {r.get('name', '?'):<10}  (无数据)                                              │")
                continue
            q = r['tencent']
            print(f"│ {q.get('name', '?'):<10} ¥{q.get('price', 0):>6.2f} {q.get('pe_ttm', 0):>8.1f}x "
                  f"{q.get('pb', 0):>4.2f}x {q.get('amplitude_pct', 0):>5.1f}% "
                  f"{q.get('vol_ratio', 0):>4.1f} {q.get('turnover_pct', 0):>4.1f} "
                  f"¥{q.get('limit_up', 0):>4.2f}/¥{q.get('limit_down', 0):<4.2f} │")
        print("└" + "─" * 80 + "┘\n")

    # 周线速览面板
    if verbose:
        print("\n┌" + "─" * 80 + "┐")
        print("│ 周线技术分析层 (中长期评估 · tushare.weekly)                  │")
        print("├" + "─" * 80 + "┤")
        for r in results:
            wk = r.get('weekly_ext') or {}
            if not wk or 'error' in wk:
                print(f"│ {r.get('name', '?'):<10}  (周线数据不足)                                  │")
                continue
            print(f"│ {r.get('name', '?'):<10} {wk['total_score']:>3}/200 {wk['grade']:<3} "
                  f"{wk['trend_label']:<14} {wk['position']['zone']:<14} {wk['macd']['detail']:<8} │")
        print("└" + "─" * 80 + "┘\n")

    # 生成八维度核心报告（参考系统 generate_report）
    base_report = generate_report(stock_list=stock_list_resolved, report_name=title + "_核心", save_dir=output_dir)

    # 读取基础报告并去冗：移除参考系统中的重复章节
    if base_report and os.path.exists(base_report):
        with open(base_report, 'r', encoding='utf-8') as f:
            md = f.read()
        # 用正则移除目标章节（反身性四象限/周线趋势/ZSCORE比价 — 参考系统版）
        import re as _re
        md = _re.sub(r'## 🔄 反身性四象限分析\n(?:.*?\n)*?(?=## |$)', '', md, flags=_re.DOTALL)
        md = _re.sub(r'## 📈 周线趋势分析\n(?:.*?\n)*?(?=## |$)', '', md, flags=_re.DOTALL)
        md = _re.sub(r'## 📐 板块ZSCORE比价分析\n(?:.*?\n)*?(?=## |$)', '', md, flags=_re.DOTALL)
        md = _re.sub(r'\n{4,}', '\n\n\n', md)
        if verbose:
            print(f"  ★ 去冗完成: {len(md.split(chr(10)))}行")
    else:
        base_report = os.path.join(output_dir, title + "_核心.md")
        md = f"# {title} 核心评估报告\n\n"
        md += "> ⚠️ 以下标的涨停封死，已纳入全维度评估并标记\\n\\n"
        limit_names = [r.get('name', '?') for r in results if r.get('tencent', {}).get('limit_up', 0) > 0 and r.get('tencent', {}).get('price', 0) >= r.get('tencent', {}).get('limit_up', 0) * 0.995]
        if limit_names:
            md += f"\U0001f6a8 **涨停封死**: {', '.join(limit_names)}\\n\\n"
            md += '### \U0001f4ca 评分速览（含涨停标的）\\n\\n'
            md += '| 股票 | 状态 | 现价 | 涨跌% | 技术 | 资金 | 情绪 | 基础 | 板块 | 热度 |\\n'
            md += '|------|------|------|-------|------|------|------|------|------|------|\\n'
            for r in results:
                lu = r.get('tencent', {}).get('limit_up', 0)
                pct = r.get('tencent', {}).get('pct_chg', 0)
                price = r.get('tencent', {}).get('price', 0)
                status = '\U0001f6a8' if (lu > 0 and price >= lu * 0.995) else '\u2705'
                sc = r.get('scores', {})
                md += f"| {r.get('name', '?')} | {status} | \\u00a5{price:.2f} | {pct:+.2f}% | {sc.get('tech', '\u2014')} | {sc.get('capital', '\u2014')} | {sc.get('sentiment', '\u2014')} | {sc.get('fundamental', '\u2014')} | {sc.get('sector', '\u2014')} | {sc.get('heat', '\u2014')} |\\n"

    # 追加扩展层（仅自己的版本，不与参考系统重复）
    md += _format_tencent_section(results)
    md += _format_weekly_section(results)

    # 阶段4: ZSCORE四维共振
    if verbose:
        print("阶段 4/5: ZSCORE 四维共振分析...")
    zscore_df = None
    try:
        zscore_result = load_zscore_data(verbose=False)
        if zscore_result is None:
            pass
        elif isinstance(zscore_result, tuple):
            zscore_df = zscore_result[0]
        else:
            zscore_df = zscore_result
    except Exception as e:
        if verbose:
            print(f"  ⚠ ZSCORE数据加载失败(降级): {e}")
    md += _format_zscore_section(results, zscore_df, end_date, verbose)

    # 阶段5: 反身性三阶段诊断
    if verbose:
        print("阶段 5/5: 反身性三阶段诊断...")
    try:
        md += _format_reflexivity_section(results, end_date, verbose)
    except Exception as e:
        if verbose:
            print(f"  ⚠ 反身性章节计算失败(降级): {e}")
        md += "\n---\n\n## 🔄 反身性三阶段诊断层 (核心 15%权重)\n\n> ⚠ 反身性数据管道异常，降级为静默（详见控制台）\n\n"

    # 通达信主力全景
    try:
        md += _format_tdx_section(results)
    except Exception as e:
        if verbose:
            print(f"  ⚠ 通达信主力全景章节计算失败(降级): {e}")
        md += "\n---\n\n## 🎯 通达信主力全景层 (核心 35%权重)\n\n> ⚠ 通达信主力全景数据管道异常，降级为静默（详见控制台）\n\n"

    if verbose: print('筹码面分析...')
    md += _format_chip_section(results)
    if verbose: print('T+1分层止损与盈亏比...')
    md += _format_stop_loss_section(results)
    md += f"\n\n---\n\n*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n"

    with open(base_report, 'w', encoding='utf-8') as f:
        f.write(md)

    if verbose:
        print(f"\n✅ 报告已生成: {base_report}")
    return base_report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='智能合并评估 — 八维度 + a-stock-data + 周线 + ZSCORE + 反身性 + 通达信')
    parser.add_argument('--stocks', '-s', type=str, default=None, help='股票名逗号分隔')
    parser.add_argument('--codes', '-c', type=str, default=None, help='完整代码逗号分隔')
    parser.add_argument('--file', '-f', type=str, default=None, help='输入文件（每行一只）')
    parser.add_argument('--title', '-t', type=str, default=None)
    parser.add_argument('--output', '-o', type=str, default=None)
    args = parser.parse_args()

    inputs = []
    if args.stocks:
        inputs += [s.strip() for s in args.stocks.split(',') if s.strip()]
    if args.codes:
        inputs += [s.strip() for s in args.codes.split(',') if s.strip()]
    if args.file:
        p = os.path.abspath(args.file)
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                inputs += [l.strip() for l in f if l.strip() and not l.startswith('#')]

    if not inputs:
        print("用法: python eval_smart.py --stocks '紫光股份,艾迪精密'")
        sys.exit(1)

    p = run_smart_eval(inputs, title=args.title, output_dir=os.path.abspath(args.output) if args.output else None)
    if p:
        print(f"\n✅ 报告: {p}")
