#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
评估中心 — 评估引擎主模块
复用 TraeSpace/评估系统 的核心逻辑，封装为易用接口
不修改参考文件夹任何内容。

用法:
    python eval_engine.py --stocks "拓邦股份,艾迪精密,星帅尔"
    python eval_engine.py --codes "002139.SZ,603638.SH,002860.SZ"
    python eval_engine.py --file input.txt  (每行一个股票名或代码)
"""

import os
import sys
import json
import argparse
from datetime import datetime, timedelta

# ═══════════════════════════════════════════════════
# 将参考系统的 stock_eval_system 目录加入 sys.path
# 这样可以直接 import 其中的模块，复用全部逻辑
# ═══════════════════════════════════════════════════
REF_SYSTEM_DIR = r'C:\Users\Admin\Documents\TraeSpace\评估系统\stock_eval_system'
if REF_SYSTEM_DIR not in sys.path:
    sys.path.insert(0, REF_SYSTEM_DIR)

# 导入参考系统核心模块（不修改源文件）
from 粗评报告模板_v2 import (
    DataLoader,
    evaluate_batch,
    evaluate_stock,
    generate_report,
    SignalTracker,
    # 所有评估函数都可用
    calc_technical,
    calc_capital,
    calc_sentiment,
    calc_fundamental,
    calc_sector,
    calc_hot_theme,
    calc_zscore_resonance,
    calc_reflexivity,
    calibrate_prob,
    compute_atr,
    t1_stop_loss,
    check_tradeable,
    load_concept_mapping,
    load_north_flow,
    load_holder_data,
    load_zscore_data,
    match_zscore,
    THEME_MAP,
    THEME_PRIORITY,
    get_hot_sectors,
    ZSCORE_DATA_DIR,
)

# ═══════════════════════════════════════════════════
#  评估中心配置
# ═══════════════════════════════════════════════════
OUTPUT_BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # D:\Hermes\评估中心

# 子目录
REPORTS_粗评 = os.path.join(OUTPUT_BASE_DIR, 'reports', '粗评')
REPORTS_个股 = os.path.join(OUTPUT_BASE_DIR, 'reports', '个股')
REPORTS_组合 = os.path.join(OUTPUT_BASE_DIR, 'reports', '组合')
REPORTS_HTML = os.path.join(OUTPUT_BASE_DIR, 'reports', 'html')
DATA_DIR     = os.path.join(OUTPUT_BASE_DIR, 'data')

for d in [REPORTS_粗评, REPORTS_个股, REPORTS_组合, REPORTS_HTML, DATA_DIR]:
    os.makedirs(d, exist_ok=True)


# ═══════════════════════════════════════════════════
#  股票名称/代码解析
# ═══════════════════════════════════════════════════
import tushare as ts
ts.set_token('3de9976db504a798ec235a8cfaa5292ba7b5cb7f20957d6929e04287')
pro = ts.pro_api()

def resolve_stocks(input_list: list) -> list:
    """
    将股票名称或代码列表解析为标准 tushare 代码列表
    支持: 中文名、简写代码(如 002139)、完整ts_code(002139.SZ)
    """
    codes = []
    # 获取全量股票基础信息用于名称→代码映射
    try:
        basic_df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,name')
        name_map = {}
        short_map = {}
        for _, row in basic_df.iterrows():
            ts_code = row['ts_code']
            name = row['name']
            short = ts_code.split('.')[0]  # 如 002139
            name_map[name] = ts_code
            short_map[short] = ts_code
    except Exception:
        name_map = {}
        short_map = {}

    for item in input_list:
        item = item.strip()
        if not item:
            continue

        # 已经是完整ts_code格式
        if item in short_map.values() or ('.' in item and len(item) == 9):
            codes.append(item)
            continue

        # 简写代码（6位数字）
        if item.isdigit() and len(item) == 6:
            if item in short_map:
                codes.append(short_map[item])
            else:
                # 尝试补后缀
                for suffix in ['.SZ', '.SH', '.BJ']:
                    candidate = item + suffix
                    if candidate in name_map.values():
                        codes.append(candidate)
                        break
            continue

        # 中文名称精确匹配
        if item in name_map:
            codes.append(name_map[item])
            continue

        # 中文名称模糊匹配
        matched = False
        for name, ts_code in name_map.items():
            if item in name:
                codes.append(ts_code)
                matched = True
                break
        if matched:
            continue

        print(f"  ⚠ 无法解析: {item}")

    return codes


# ═══════════════════════════════════════════════════
#  评估报告生成器（封装）
# ═══════════════════════════════════════════════════

def run_evaluation(stocks_or_codes: list, report_title: str = None,
                   output_dir: str = None, verbose: bool = True) -> str:
    """
    主入口：输入股票列表，输出完整Markdown评估报告

    参数:
        stocks_or_codes: 股票名称或代码列表
        report_title: 报告标题（可选）
        output_dir: 输出目录（默认 reports/粗评/）
        verbose: 是否打印详细进度

    返回:
        str: 生成的报告文件路径
    """
    # 1. 解析代码
    if verbose:
        print(f"\n{'='*60}")
        print(f"评估中心 — 八维度评估 v4.2")
        print(f"{'='*60}")
        print(f"正在解析 {len(stocks_or_codes)} 个输入...")

    codes = resolve_stocks(stocks_or_codes)
    if not codes:
        print("✗ 未能解析任何有效股票代码")
        return None

    if verbose:
        print(f"  解析完成: {len(codes)} 只有效标的\n")

    # 2. 生成报告名称
    if report_title is None:
        ts_now = datetime.now().strftime('%Y%m%d_%H%M')
        report_title = f"粗评报告_{len(codes)}只_{ts_now}"

    if output_dir is None:
        output_dir = REPORTS_粗评

    os.makedirs(output_dir, exist_ok=True)

    # 3. 调用参考系统的 generate_report（复用全部逻辑）
    #    注意: generate_report 内部会调用 evaluate_batch → DataLoader → Tushare API
    #          含 Phase3 概念/北向/股东户数 + ZSCORE + 反身性
    filepath = generate_report(
        stock_list=codes,
        report_name=report_title,
        save_dir=output_dir,
    )

    return filepath


def run_single_stock_eval(code: str, verbose: bool = True) -> dict:
    """
    单只股票深度评估（返回结构化结果字典）
    """
    from 粗评报告模板_v2 import DataLoader, evaluate_stock

    dl = DataLoader()
    all_data = dl.load_all([code], lookback_days=90, verbose=verbose)
    sector_data = all_data.pop('_sectors', {})
    market_info = all_data.pop('_market', {})

    sd = all_data.get(code, {})
    if not sd:
        return {'code': code, 'error': '数据加载失败'}

    industry = sd.get('industry', '未知')
    sector_df = sector_data.get(industry)
    market_df = sector_data.get('上证综指')

    # Phase3 数据
    concept_map = load_concept_mapping([code], verbose=False)
    north_flow = load_north_flow()
    holder_map = load_holder_data([code], verbose=False)
    zscore_df, zscore_date, zscore_fresh = load_zscore_data(verbose=False)

    limit_up_count = market_info.get('limit_up_count', 30)
    hot_sectors = get_hot_sectors(top_n=5)

    result = evaluate_stock(
        code=code,
        stock_data=sd,
        name=sd.get('name', code),
        industry=industry,
        sector_df=sector_df,
        market_df=market_df,
        limit_up_count=limit_up_count,
        hot_sectors=hot_sectors,
        concepts=concept_map.get(code, []),
        north_flow=north_flow,
        holder_data=holder_map.get(code),
        zscore_df=zscore_df,
    )

    return result


def run_batch_evaluation(codes: list, verbose: bool = True) -> tuple:
    """
    批量评估（复用 evaluate_batch），返回 (results, meta)
    """
    from 粗评报告模板_v2 import evaluate_batch
    return evaluate_batch(codes, lookback_days=90, verbose=verbose)


# ═══════════════════════════════════════════════════
#  信号跟踪器封装
# ═══════════════════════════════════════════════════

def tracker_stats():
    """查看信号跟踪器统计数据"""
    tracker = SignalTracker(save_path=os.path.join(DATA_DIR, 'signal_tracker.json'))
    tracker.print_stats()
    return tracker.stats()


def tracker_verify():
    """手动触发信号验证"""
    tracker = SignalTracker(save_path=os.path.join(DATA_DIR, 'signal_tracker.json'))
    verified = tracker.verify_pending(verbose=True)
    if verified > 0:
        tracker.print_stats()
    return verified


# ═══════════════════════════════════════════════════
#  CLI 入口
# ═══════════════════════════════════════════════════

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='评估中心 — 股票八维度评估报告生成器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python eval_engine.py --stocks "拓邦股份,艾迪精密,星帅尔"
  python eval_engine.py --codes "002139.SZ,603638.SH,002860.SZ"
  python eval_engine.py --file my_stocks.txt
  python eval_engine.py --stats           # 查看信号统计
  python eval_engine.py --verify          # 验证到期信号
        """
    )

    parser.add_argument('--stocks', '-s', type=str, default=None,
                        help='股票名称或代码，逗号分隔 (如 "拓邦股份,002139.SZ")')
    parser.add_argument('--codes', '-c', type=str, default=None,
                        help='Tushare完整代码，逗号分隔 (如 "002139.SZ,603638.SH")')
    parser.add_argument('--file', '-f', type=str, default=None,
                        help='输入文件路径，每行一个股票名或代码')
    parser.add_argument('--title', '-t', type=str, default=None,
                        help='自定义报告标题')
    parser.add_argument('--output', '-o', type=str, default=None,
                        help='自定义输出目录')
    parser.add_argument('--stats', action='store_true', default=False,
                        help='查看信号跟踪器统计数据')
    parser.add_argument('--verify', action='store_true', default=False,
                        help='验证所有到期信号')

    args = parser.parse_args()

    # 信号统计模式
    if args.stats:
        tracker_stats()
        sys.exit(0)

    if args.verify:
        tracker_verify()
        sys.exit(0)

    # 收集股票输入
    stock_inputs = []

    if args.stocks:
        stock_inputs.extend([s.strip() for s in args.stocks.split(',') if s.strip()])

    if args.codes:
        stock_inputs.extend([s.strip() for s in args.codes.split(',') if s.strip()])

    if args.file:
        filepath = os.path.abspath(args.file)
        if not os.path.exists(filepath):
            print(f"✗ 文件不存在: {filepath}")
            sys.exit(1)
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    stock_inputs.append(line)

    if not stock_inputs:
        print("✗ 未提供任何股票输入。使用 --stocks, --codes 或 --file 参数。")
        print("  示例: python eval_engine.py --stocks '拓邦股份,艾迪精密'")
        sys.exit(1)

    # 执行评估
    report_path = run_evaluation(
        stocks_or_codes=stock_inputs,
        report_title=args.title,
        output_dir=os.path.abspath(args.output) if args.output else None,
        verbose=True,
    )

    if report_path:
        print(f"\n{'='*60}")
        print(f"✅ 评估完成!")
        print(f"📄 报告路径: {report_path}")
        print(f"{'='*60}")
    else:
        print("\n✗ 评估失败，请检查股票代码/名称是否正确。")
        sys.exit(1)