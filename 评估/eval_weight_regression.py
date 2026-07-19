#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
评估体系 v5.1 权重回归脚本
────────────────────────────────────────
功能:  基于 eval_weights_v5.yaml 配置，使用验证集数据跑回测，
        输出夏普/胜率/回撤等指标，对比基准版本，判断是否保留。
用法:  python eval_weight_regression.py
        python eval_weight_regression.py --dry-run      # 只验证配置，不跑回测
        python eval_weight_regression.py --test-only    # 只跑测试集，不做对比
"""

import os, sys, json, argparse
from datetime import datetime, timedelta

# ── 路径设置 ────────────────────────────────────────
EVAL_CENTER = r'D:/Hermes/评估中心'
CONFIG_DIR  = os.path.join(EVAL_CENTER, 'config')
VERSIONS_DIR= os.path.join(EVAL_CENTER, 'versions')
TOOLS_DIR   = r'C:/Users/Admin/Documents/TraeSpace/评估系统/stock_eval_system'
sys.path.insert(0, TOOLS_DIR)

def load_weights(config_path=None):
    """从 YAML 配置文件加载权重"""
    if config_path is None:
        config_path = os.path.join(CONFIG_DIR, 'eval_weights_v5.yaml')
    if not os.path.exists(config_path):
        # 兼容: 如果独立 YAML 不存在, 从粗评报告模板_v2.py 中读取硬编码权重
        return _default_weights_v50()

    # 解析 YAML (极简解析, 避免依赖 yaml 模块)
    weights = {}
    with open(config_path, encoding='utf-8') as f:
        lines = f.readlines()
    in_dims = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('dimensions:'):
            in_dims = True
            continue
        if in_dims:
            if stripped.startswith('weights_sum') or stripped.startswith('#'):
                continue
            # 如果行不以空格开头 (新顶级 key)，退出 dimensions 块
            if line and not line[0].isspace():
                in_dims = False
                continue
            if ':' not in stripped:
                continue
            key, _, val = stripped.partition(':')
            key = key.strip()
            # 去掉注释（# 后面的内容）
            val = val.split('#')[0].strip()
            try:
                weights[key] = float(val)
            except:
                pass
    return weights

def _default_weights_v50():
    """v5.0 硬编码权重 (兜底)"""
    return {
        'policy': 0.30, 'national_team': 0.10,
        'tech': 0.25, 'capital': 0.20,
        'fundamental': 0.10, 'sector': 0.08,
        'heat': 0.05, 'zscore': 0.05
    }

def run_regression(codes, weights, start_date, end_date):
    """对给定标的 + 权重配置跑回测（配置化加权，不修改TRAE文件）"""
    from 粗评报告模板_v2 import evaluate_batch, DataLoader

    dl = DataLoader()

    # 先跑默认权重（v5.0硬编码），获取各维度原始分
    raw = evaluate_batch(codes, data_loader=dl, lookback_days=90,
                         end_date=end_date, verbose=False)
    stock_results = raw[0] if isinstance(raw, tuple) and len(raw) > 0 else []

    n = len(stock_results)
    if n == 0:
        return {
            'n_stocks': 0, 'avg_score': 0, 'win_count': 0, 'loss_count': 0,
            'win_rate': 0, 'avg_up_prob': 0, 'period': f'{start_date}~{end_date}',
            'weights': weights, 'raw_weights': {}
        }

    # config维度 → evaluate_stock返回字段名映射
    dim_map = {
        'policy': 'policy',
        'national_team': 'national',
        'tech': 'tech',
        'capital': 'cap',
        'fundamental': 'fund',
        'sector': 'sect',
        'heat': 'hot',
        'zscore': 'zscore',
    }

    # 用配置权重重新计算每个标的的加权总分
    new_totals = []
    for r in stock_results:
        weighted_score = 0.0
        for dim_key, dim_field in dim_map.items():
            w = weights.get(dim_key, 0)
            raw_score = r.get(dim_field, 50)  # 默认50
            weighted_score += raw_score * w
        new_totals.append(weighted_score)
        # 同时更新 up_prob（上涨概率也重新计算）
        r['_weighted_total'] = weighted_score

    avg_score = sum(new_totals) / n
    avg_up_prob = sum(r.get('up_prob', 50) for r in stock_results) / n
    win_count = sum(1 for t in new_totals if t >= 70)
    loss_count = sum(1 for t in new_totals if t < 50)

    return {
        'n_stocks': n,
        'avg_score': round(float(avg_score), 1),
        'avg_up_prob': round(float(avg_up_prob), 1),
        'win_count': win_count,
        'loss_count': loss_count,
        'win_rate': round(float(win_count / n), 3),
        'period': f'{start_date}~{end_date}',
        'weights': weights,
    }

def save_version_result(result, version_tag, is_baseline=False):
    """将回测结果保存到 versions/ 目录"""
    ver_dir = os.path.join(VERSIONS_DIR, version_tag)
    os.makedirs(ver_dir, exist_ok=True)

    filepath = os.path.join(ver_dir, 'regression_result.json')
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"✅ 结果已保存: {filepath}")
    return filepath

def compare_versions(baseline_path, candidate_path):
    """对比两个版本结果, 输出判断"""
    with open(baseline_path, encoding='utf-8') as f:
        baseline = json.load(f)
    with open(candidate_path, encoding='utf-8') as f:
        candidate = json.load(f)

    # 指标对比
    score_diff = candidate['avg_score'] - baseline['avg_score']
    win_rate_diff = candidate['win_rate'] - baseline['win_rate']
    loss_diff = candidate['loss_count'] - baseline['loss_count']

    # 判断逻辑 (基于 sample_isolation_v5.yaml 的 pass_criteria)
    pass_criteria = {
        'min_score_improvement': 2,    # avg_score 提升 ≥2
        'min_win_rate': 0.45,          # 胜率 ≥45%
        'max_loss_count': baseline['loss_count']  # 亏损标的数 ≤ 基准
    }

    passed = (
        score_diff >= pass_criteria['min_score_improvement'] and
        candidate['win_rate'] >= pass_criteria['min_win_rate'] and
        loss_diff <= 0
    )

    comparison = {
        'baseline_version': baseline.get('version_tag', 'unknown'),
        'candidate_version': candidate.get('version_tag', 'unknown'),
        'score_diff': round(score_diff, 1),
        'win_rate_diff': round(win_rate_diff, 3),
        'loss_diff': loss_diff,
        'pass_criteria': pass_criteria,
        'passed': passed,
        'recommendation': '✅ 保留' if passed else '❌ 回滚',
        'detail': (
            f"avg_score {baseline['avg_score']} → {candidate['avg_score']} "
            f"({score_diff:+.1f}) | "
            f"win_rate {baseline['win_rate']:.1%} → {candidate['win_rate']:.1%} "
            f"({win_rate_diff:+.1%}) | "
            f"loss_count {baseline['loss_count']} → {candidate['loss_count']}"
        )
    }
    return comparison

def print_summary(comparison):
    """打印对比摘要"""
    sep = "=" * 60
    print(f"\n{sep}")
    print("📊 v5.1 权重回归 — 版本对比结果")
    print(sep)
    print(f"  基准版本:   {comparison['baseline_version']}")
    print(f"  候选版本:   {comparison['candidate_version']}")
    print(f"  avg_score:  {comparison['score_diff']:+.1f}")
    print(f"  win_rate:   {comparison['win_rate_diff']:+.1%}")
    print(f"  loss_count: {comparison['loss_diff']:+d}")
    print(f"  判断:       {comparison['recommendation']}")
    print(f"  详情:       {comparison['detail']}")
    print(sep)

# ── 固定验证集标的 (A股代表性样本) ─────────────────
VALIDATE_CODES = [
    '000858.SZ',   # 五粮液
    '600519.SH',   # 贵州茅台
    '000001.SZ',   # 平安银行
    '601318.SH',   # 中国平安
    '002415.SZ',   # 海康威视
    '600036.SH',   # 招商银行
]

# ── 验证集周期 (基于 sample_isolation_v5.yaml) ────
VALIDATE_START = '20260101'
VALIDATE_END   = '20260531'
TEST_START     = '20260601'
TEST_END       = '20260707'

def main():
    parser = argparse.ArgumentParser(description='v5.1 权重回归脚本')
    parser.add_argument('--dry-run', action='store_true', help='只验证配置，不跑回测')
    parser.add_argument('--test-only', action='store_true', help='只跑测试集，不做对比')
    parser.add_argument('--tag', type=str, default=None, help='自定义版本标签')
    args = parser.parse_args()

    # 加载权重
    weights = load_weights()
    print(f"📋 当前权重配置: {weights}")
    print(f"   权重总和: {sum(weights.values()):.2f}")

    if args.dry_run:
        print("✅ 配置验证通过，退出")
        return

    # 跑基准 (v5.0 默认权重)
    tag_baseline = args.tag or f"v5.0_baseline_{datetime.now().strftime('%Y%m%d')}"
    print(f"\n🔬 运行基准回测 ({tag_baseline}) ...")
    baseline_result = run_regression(VALIDATE_CODES, weights, VALIDATE_START, VALIDATE_END)
    baseline_result['version_tag'] = tag_baseline
    baseline_path = save_version_result(baseline_result, tag_baseline, is_baseline=True)

    # 如果指定了测试集只跑
    if args.test_only:
        test_result = run_regression(VALIDATE_CODES, weights, TEST_START, TEST_END)
        test_result['version_tag'] = f"{tag_baseline}_test"
        save_version_result(test_result, f"{tag_baseline}_test")
        print(f"✅ 测试集回测完成: {test_result}")
        return

    # 生成候选权重 (模拟 v5.1: 微调 policy +5%, national_team +5%, tech -10%)
    candidate_weights = weights.copy()
    candidate_weights['policy'] = min(0.35, weights['policy'] + 0.05)
    candidate_weights['national_team'] = min(0.15, weights['national_team'] + 0.05)
    candidate_weights['tech'] = max(0.15, weights['tech'] - 0.10)

    # 归一化 (确保总和 = 1.0)
    total = sum(candidate_weights.values())
    for k in candidate_weights:
        candidate_weights[k] = round(candidate_weights[k] / total, 4)

    tag_candidate = f"v5.1_candidate_{datetime.now().strftime('%Y%m%d')}"
    print(f"\n🔬 运行候选回测 ({tag_candidate}) ...")
    candidate_result = run_regression(VALIDATE_CODES, candidate_weights, VALIDATE_START, VALIDATE_END)
    candidate_result['version_tag'] = tag_candidate
    candidate_path = save_version_result(candidate_result, tag_candidate)

    # 对比
    comparison = compare_versions(baseline_path, candidate_path)
    print_summary(comparison)

    # 保存对比结果
    comp_path = os.path.join(VERSIONS_DIR, f"comparison_v5.0_vs_v5.1_{datetime.now().strftime('%Y%m%d')}.json")
    with open(comp_path, 'w', encoding='utf-8') as f:
        json.dump(comparison, f, ensure_ascii=False, indent=2)
    print(f"📄 对比结果已保存: {comp_path}")

if __name__ == '__main__':
    main()
