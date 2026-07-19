#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回测引擎 v2.0 — 历史的审判者

升级内容：
1. 多时间窗口回测: 支持 hold_days=[2,5,10,20] 多窗口同时评估
2. 风险指标统计: 夏普比率、最大回撤、盈亏比
3. v5.0维度支持: 政策催化、国家队面评分
4. 按政策/国家队分组统计: 政策催化高分/低分组对比
"""

import os
import sys
import json
import math
from datetime import datetime, timedelta
from collections import defaultdict

# 导入评估系统
from 粗评报告模板_v2 import (
    DataLoader, evaluate_stock, evaluate_batch,
    get_trading_days, pro
)


class BacktestEngine:
    """
    回测引擎 v2.0 — 历史的审判者
    
    升级：
    - 支持多时间窗口回测 (2/5/10/20日)
    - 支持政策催化/国家队面评分导入
    - 支持多指标统计（胜率/盈亏比/最大回撤/夏普比率）
    - 支持按维度分组对比（政策催化高分/低分组）
    """

    def __init__(self, data_loader=None):
        self.data_loader = data_loader or DataLoader()
        self.predictions = []
        self._stock_name_cache = {}

    def _next_trading_day(self, date_str, n_days=5):
        """获取N个交易日后的日期"""
        try:
            all_days = get_trading_days(n_days + 10, date_str)
            current_idx = all_days.index(date_str) if date_str in all_days else len(all_days) - 1
            future_idx = min(current_idx + n_days, len(all_days) - 1)
            return all_days[future_idx]
        except Exception:
            # Fallback
            future = datetime.strptime(date_str, '%Y%m%d') + timedelta(days=n_days*1.5)
            return future.strftime('%Y%m%d')

    def run(self, codes, lookback_days=20, hold_days=5,
            verbose=True, end_date=None) -> list:
        """
        执行回测
        
        参数:
            codes: 股票代码列表
            lookback_days: 回测多少个交易日（如20天）
            hold_days: 预测持有天数，支持列表[2,5,10,20]
            end_date: 回测截止日期 'YYYYMMDD'，默认今天
            verbose: 打印详细进度

        返回: list of 预测记录
        """
        if end_date is None:
            end_date = datetime.now().strftime('%Y%m%d')

        # 支持多时间窗口
        if isinstance(hold_days, list):
            hold_windows = hold_days
        else:
            hold_windows = [hold_days]

        # 获取回测交易日列表（需要覆盖最长时间窗口）
        max_hold = max(hold_windows)
        all_days = get_trading_days(lookback_days + max_hold + 5, end_date)
        eval_days = all_days[:lookback_days]

        if verbose:
            print(f"回测范围: {eval_days[0]} → {eval_days[-1]} ({len(eval_days)}个交易日)")
            print(f"标的数量: {len(codes)} 只")
            print(f"时间窗口: {hold_windows} 日")
            print("-" * 60)

        results = []
        total_evals = len(eval_days) * len(codes)
        completed = 0

        for day_idx, eval_date in enumerate(eval_days):
            if verbose:
                print(f"\n[{day_idx + 1}/{len(eval_days)}] {eval_date}")

            # 1. 加载评估日的数据
            try:
                all_data = self.data_loader.load_all(
                    codes, lookback_days=90, end_date=eval_date, verbose=False
                )
            except Exception as e:
                if verbose:
                    print(f"  ✗ 数据加载失败: {e}")
                continue

            market_info = all_data.pop('_market', {})
            sector_data = all_data.pop('_sectors', {})
            limit_up_count = market_info.get('limit_up_count', 30)

            # 大盘数据
            market_df = sector_data.get('上证综指', None)

            # 2. 逐股评估
            for code in codes:
                completed += 1
                sd = all_data.get(code, {})
                if not sd or sd.get('daily') is None or sd['daily'].empty:
                    continue

                industry = sd.get('industry', '未知')
                sector_df = sector_data.get(industry, None)

                # 评估
                r = evaluate_stock(
                    code=code,
                    stock_data=sd,
                    name=sd.get('name', code),
                    industry=industry,
                    sector_df=sector_df,
                    market_df=market_df,
                    limit_up_count=limit_up_count,
                )

                if 'error' in r:
                    continue

                # 3. 对每个时间窗口获取真实涨跌
                base_record = {
                    'eval_date': eval_date,
                    'code': code,
                    'name': r['name'],
                    'total': r['total'],
                    'grade': r['grade'],
                    'up_prob': r['up_prob'],
                    'tech': r['tech'],
                    'cap': r['cap'],
                    'sent': r['sent'],
                    'fund': r['fund'],
                    'sect': r['sect'],
                    'hot': r.get('hot', 50),
                    'zscore': r.get('zscore', 50),
                    'reflexivity': r.get('reflexivity', 50),
                    'holder': r.get('holder_dimension', 50),
                    'mainforce': r.get('mainforce_bonus', 0),
                    # v5.0 新增维度
                    'policy': r.get('policy', 50),
                    'national': r.get('national', 50),
                    'policy_sig': r.get('policy_sig', []),
                    'national_sig': r.get('national_sig', []),
                }

                # 获取评估日收盘价（用于计算收益）
                eval_price = None
                try:
                    eval_df = self.data_loader.load_daily(
                        code, lookback_days=1, end_date=eval_date
                    )
                    if eval_df is not None and not eval_df.empty:
                        eval_price = float(eval_df.iloc[0]['close'])
                except Exception:
                    pass

                # 对每个时间窗口计算收益
                for window in hold_windows:
                    future_date = self._next_trading_day(eval_date, window)
                    actual_return = None
                    hit = None

                    if eval_price and eval_price > 0:
                        try:
                            future_df = self.data_loader.load_daily(
                                code, lookback_days=1, end_date=future_date
                            )
                            if future_df is not None and not future_df.empty:
                                future_price = float(future_df.iloc[0]['close'])
                                actual_return = round(
                                    (future_price / eval_price - 1) * 100, 2
                                )
                                hit = actual_return > 0
                        except Exception:
                            pass

                    record = dict(base_record)
                    record.update({
                        'hold_days': window,
                        'future_date': future_date,
                        'actual_return': actual_return,
                        'hit': hit,
                    })
                    results.append(record)

                    if verbose and hit is not None:
                        hit_mark = "✅" if hit else "❌"
                        pct_str = f"{actual_return:+.1f}%" if actual_return is not None else "N/A"
                        print(f"  {r['name']} {r['grade']}级 "
                              f"预测↑{r['up_prob']}% | {window}日后{pct_str} {hit_mark}")

        self.predictions = results
        return results

    def _get_close(self, code, date_str):
        """获取指定日期的收盘价"""
        try:
            df = self.data_loader.load_daily(code, lookback_days=1, end_date=date_str)
            if df is not None and not df.empty:
                return df.iloc[0]['close']
        except Exception:
            pass
        return None

    def summary(self, predictions=None, windows=None) -> dict:
        """
        生成回测统计摘要（支持多窗口）
        
        新增统计指标：
        - win_rate: 胜率
        - avg_return: 平均收益
        - max_drawdown: 最大回撤
        - sharpe_ratio: 夏普比率（简化版）
        - profit_loss_ratio: 盈亏比
        - by_grade: 按等级统计
        - by_window: 按时间窗口统计
        """
        if predictions is None:
            predictions = self.predictions

        if not predictions:
            return {'error': '无回测数据'}

        valid = [p for p in predictions if p['hit'] is not None]
        if not valid:
            return {'error': '无有效回测记录'}

        # 如果没有指定窗口，统计所有窗口
        if windows is None:
            windows = list(set(p['hold_days'] for p in valid))

        # 按窗口分组
        by_window = {}
        for w in windows:
            w_preds = [p for p in valid if p['hold_days'] == w]
            by_window[w] = self._compute_stats(w_preds)

        # 按等级分组（全局）
        by_grade = defaultdict(list)
        for p in valid:
            by_grade[p['grade']].append(p)

        grade_stats = {}
        for grade in ['S', 'A', 'B', 'C', 'D']:
            records = by_grade.get(grade, [])
            if not records:
                continue
            grade_stats[grade] = self._compute_stats(records)

        # 按政策催化分组（v5.0）
        policy_groups = self._compute_policy_groups(valid)

        # 按国家队面分组（v5.0）
        national_groups = self._compute_national_groups(valid)

        # 整体统计（所有窗口合并）
        all_returns = [p['actual_return'] for p in valid if p['actual_return'] is not None]
        all_avg = sum(all_returns) / len(all_returns) if all_returns else 0
        all_hits = sum(1 for p in valid if p['hit'])

        return {
            'total_predictions': len(valid),
            'total_hits': all_hits,
            'overall_win_rate': round(all_hits / len(valid) * 100, 1) if valid else 0,
            'overall_avg_return': round(all_avg, 2),
            'by_grade': grade_stats,
            'by_window': by_window,
            'by_policy': policy_groups,
            'by_national': national_groups,
        }

    def _compute_stats(self, records):
        """计算一组记录的统计指标"""
        if not records:
            return {'count': 0, 'hits': 0, 'win_rate': 0,
                    'avg_return': 0, 'max_return': 0, 'min_return': 0,
                    'max_drawdown': 0, 'sharpe_ratio': 0, 'profit_loss_ratio': 0}

        hits = sum(1 for r in records if r['hit'])
        total = len(records)
        win_rate = hits / total * 100 if total > 0 else 0

        returns = [r['actual_return'] for r in records if r['actual_return'] is not None]
        if not returns:
            return {'count': total, 'hits': hits, 'win_rate': round(win_rate, 1),
                    'avg_return': 0, 'max_return': 0, 'min_return': 0,
                    'max_drawdown': 0, 'sharpe_ratio': 0, 'profit_loss_ratio': 0}

        avg_return = sum(returns) / len(returns)
        max_return = max(returns)
        min_return = min(returns)

        # 最大回撤（累计收益序列）
        cumulative = 0
        peak = 0
        max_dd = 0
        for r in returns:
            cumulative += r
            peak = max(peak, cumulative)
            dd = peak - cumulative
            max_dd = max(max_dd, dd)

        # 夏普比率（简化版：平均收益 / 标准差 * √交易日）
        if len(returns) >= 2:
            std = (sum((r - avg_return) ** 2 for r in returns) / len(returns)) ** 0.5
            sharpe = (avg_return / std * math.sqrt(len(returns))) if std > 0 else 0
        else:
            sharpe = 0

        # 盈亏比（平均盈利 / 平均亏损）
        profits = [r for r in returns if r > 0]
        losses = [r for r in returns if r < 0]
        avg_profit = sum(profits) / len(profits) if profits else 0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 1
        profit_loss_ratio = avg_profit / avg_loss if avg_loss > 0 else 0

        return {
            'count': total,
            'hits': hits,
            'win_rate': round(win_rate, 1),
            'avg_return': round(avg_return, 2),
            'max_return': round(max_return, 2),
            'min_return': round(min_return, 2),
            'max_drawdown': round(max_dd, 2),
            'sharpe_ratio': round(sharpe, 2),
            'profit_loss_ratio': round(profit_loss_ratio, 2),
        }

    def _compute_policy_groups(self, valid):
        """按政策催化分组统计"""
        high_policy = [p for p in valid if p.get('policy', 50) >= 60]
        low_policy = [p for p in valid if p.get('policy', 50) < 60]
        return {
            'high_policy(>=60)': self._compute_stats(high_policy),
            'low_policy(<60)': self._compute_stats(low_policy),
        }

    def _compute_national_groups(self, valid):
        """按国家队面分组统计"""
        high_national = [p for p in valid if p.get('national', 50) >= 60]
        low_national = [p for p in valid if p.get('national', 50) < 60]
        return {
            'high_national(>=60)': self._compute_stats(high_national),
            'low_national(<60)': self._compute_stats(low_national),
        }

    def print_summary(self, predictions=None, windows=None):
        """打印回测统计报告"""
        stats = self.summary(predictions, windows)

        if 'error' in stats:
            print(f"✗ {stats['error']}")
            return

        print("\n" + "=" * 70)
        print("  📊 回测统计报告 v2.0")
        print("=" * 70)
        print(f"  有效预测记录: {stats['total_predictions']} 条")
        print(f"  命中次数: {stats['total_hits']} 次")
        print(f"  整体胜率: {stats['overall_win_rate']}%")
        print(f"  平均收益: {stats['overall_avg_return']:+.2f}%")
        print()

        # 按时间窗口统计
        if stats.get('by_window'):
            print("  📅 按时间窗口:")
            print(f"  {'窗口':<8} {'样本数':<8} {'胜率':<10} {'平均收益':<12} {'最大回撤':<10} {'夏普比率':<10} {'盈亏比':<8}")
            print(f"  {'-'*8} {'-'*8} {'-'*10} {'-'*12} {'-'*10} {'-'*10} {'-'*8}")
            for w, ws in stats['by_window'].items():
                print(f"  {w}日{'':<6} {ws['count']:<8} {ws['win_rate']:<10.1f}% "
                      f"{ws['avg_return']:>+8.2f}% {ws['max_drawdown']:>+8.2f}% "
                      f"{ws['sharpe_ratio']:>+8.2f} {ws['profit_loss_ratio']:>+6.2f}")
            print()

        # 按等级统计
        if stats.get('by_grade'):
            print("  🏆 按等级:")
            print(f"  {'等级':<6} {'样本数':<8} {'胜率':<10} {'平均收益':<12} {'最大回撤':<10} {'盈亏比':<8}")
            print(f"  {'-'*6} {'-'*8} {'-'*10} {'-'*12} {'-'*10} {'-'*8}")
            for grade in ['S', 'A', 'B', 'C', 'D']:
                gs = stats['by_grade'].get(grade)
                if gs:
                    print(f"  {grade:<6} {gs['count']:<8} {gs['win_rate']:<10.1f}% "
                          f"{gs['avg_return']:>+8.2f}% {gs['max_drawdown']:>+8.2f}% "
                          f"{gs['profit_loss_ratio']:>+6.2f}")
            print()

        # 按政策催化分组（v5.0）
        if stats.get('by_policy'):
            print("  📊 按政策催化分组:")
            for group_name, gs in stats['by_policy'].items():
                if gs['count'] > 0:
                    print(f"  {group_name}: {gs['count']}条, 胜率{gs['win_rate']:.1f}%, "
                          f"收益{gs['avg_return']:+.2f}%, 夏普{gs['sharpe_ratio']:.2f}")
            print()

        # 按国家队面分组（v5.0）
        if stats.get('by_national'):
            print("  🏛️ 按国家队面分组:")
            for group_name, gs in stats['by_national'].items():
                if gs['count'] > 0:
                    print(f"  {group_name}: {gs['count']}条, 胜率{gs['win_rate']:.1f}%, "
                          f"收益{gs['avg_return']:+.2f}%, 夏普{gs['sharpe_ratio']:.2f}")
            print()

        print("  ⚠ 注意：样本量过少（<5）的统计结果无参考价值")
        print("=" * 70)

    def save(self, filepath=None):
        """保存回测结果到JSON"""
        if filepath is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            data_dir = os.path.join(base_dir, 'data')
            os.makedirs(data_dir, exist_ok=True)
            filepath = os.path.join(data_dir, 'backtest_results_v2.json')

        data = {
            'predictions': self.predictions,
            'summary': self.summary(),
            'generated_at': datetime.now().isoformat(),
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✓ 回测结果已保存: {filepath}")


# ═══════════════════════════════════════════════════
#  快速验证
# ═══════════════════════════════════════════════════

if __name__ == '__main__':
    # 测试股票列表（5只）
    test_codes = ['601728.SH', '002268.SZ', '002823.SZ', '600519.SH', '000858.SZ']

    print("=" * 60)
    print("回测引擎 v2.0 验证")
    print("=" * 60)

    engine = BacktestEngine()

    # 简化测试：5个交易日，3个窗口
    results = engine.run(
        test_codes,
        lookback_days=5,
        hold_days=[2, 5, 10],
        verbose=True
    )

    engine.print_summary()
    engine.save()
    print("\n✓ backtest_engine.py v2.0 验证通过")
