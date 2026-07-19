#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
粗评报告模板 v2.0 — 深度调整版
核心改进：板块面不再假装，真正对比行业指数+大盘
"""

import os
import sys
import json
import tushare as ts
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict

# ═══════════════════════════════════════════════════
#  Tushare API 配置
# ═══════════════════════════════════════════════════
TUSHARE_TOKEN = '3de9976db504a798ec235a8cfaa5292ba7b5cb7f20957d6929e04287'
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

# ═══════════════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════════════

def get_trading_days(n_days=30, end_date=None):
    """获取最近N个交易日"""
    if end_date is None:
        end_date = datetime.now().strftime('%Y%m%d')
    
    start = (datetime.strptime(end_date, '%Y%m%d') - timedelta(days=n_days*2)).strftime('%Y%m%d')
    
    try:
        df = pro.trade_cal(exchange='SSE', start_date=start, end_date=end_date, is_open='1')
        if df is not None and not df.empty:
            dates = sorted(df['cal_date'].tolist())
            return dates[-n_days:] if len(dates) >= n_days else dates
    except Exception:
        pass
    
    # Fallback
    dates = []
    current = datetime.strptime(end_date, '%Y%m%d')
    while len(dates) < n_days:
        if current.weekday() < 5:
            dates.append(current.strftime('%Y%m%d'))
        current -= timedelta(days=1)
    return sorted(dates)


# ═══════════════════════════════════════════════════
#  统一数据加载器 (DataLoader)
# ═══════════════════════════════════════════════════
#  2026年市场主线映射表 (THEME_MAP) — 评估中心v2.0迁移
# ═══════════════════════════════════════════════════

THEME_MAP = {
    '软件服务': '🔥AI+数字经济', '互联网': '🔥AI+数字经济',
    '通信设备': '🔥AI+数字经济', '半导体': '🔥AI+数字经济',
    '元器件': '🔥AI+数字经济', '电器仪表': '🔥AI+数字经济',
    '专用机械': '⚙️新质生产力', '电气设备': '⚙️新质生产力',
    '机械基件': '⚙️新质生产力', '汽车配件': '⚙️新质生产力',
    '航空': '✈️低空经济', '航空航天': '✈️低空经济',
    '新型电力': '🔋新能源+储能', '供气供热': '🔋新能源+储能',
    '矿物制品': '🔋新能源+储能', '水力发电': '🔋新能源+储能',
    '白酒': '🛒消费复苏', '食品': '🛒消费复苏',
    '家用电器': '🛒消费复苏', '超市连锁': '🛒消费复苏',
    '文教休闲': '🛒消费复苏', '纺织服装': '🛒消费复苏',
    '煤炭开采': '🏛️中特估+央企', '银行': '🏛️中特估+央企',
    '证券': '🏛️中特估+央企', '水运': '🏛️中特估+央企',
    '建筑': '🏛️中特估+央企', '建筑工程': '🏛️中特估+央企',
    '生物制药': '💊医药健康', '医疗保健': '💊医药健康',
    '化学制药': '💊医药健康', '中成药': '💊医药健康',
    '化工原料': '🧪化工周期', '塑料': '🧪化工周期',
    '造纸': '🧪化工周期', '有色': '🧪化工周期',
    '区域地产': '🏗️地产基建', '其他建材': '🏗️地产基建',
    '服饰': '其他', '火力发电': '其他',
}

ZSCORE_DATA_DIR = r'C:\Users\Admin\Documents\TraeSpace\板块热度观察\data\processed'
CN_TRACKER_DONE = r'C:/Users/Admin/tmp/.cn_tracker.done'

THEME_PRIORITY = {
    '🔥AI+数字经济': 1, '⚙️新质生产力': 2, '✈️低空经济': 2,
    '🔋新能源+储能': 3, '💊医药健康': 3, '🏛️中特估+央企': 3,
    '🛒消费复苏': 4, '🧪化工周期': 4, '🏗️地产基建': 5, '其他': 6,
}


# ═══════════════════════════════════════════════════

class DataLoader:
    """统一数据加载器，含降级链和异常标记"""
    
    # 申万一级行业 → 申万行业指数代码
    SW_INDEX_MAP = {
        '银行': '801780.SI', '非银金融': '801790.SI', '房地产': '801180.SI',
        '建筑装饰': '801720.SI', '建筑材料': '801710.SI', '钢铁': '801040.SI',
        '有色金属': '801050.SI', '化工': '801030.SI', '采掘': '801020.SI',
        '农林牧渔': '801010.SI', '食品饮料': '801120.SI', '家用电器': '801110.SI',
        '纺织服装': '801130.SI', '轻工制造': '801140.SI', '医药生物': '801150.SI',
        '公用事业': '801160.SI', '交通运输': '801170.SI', '电子': '801080.SI',
        '计算机': '801750.SI', '传媒': '801760.SI', '通信': '801770.SI',
        '电气设备': '801730.SI', '机械设备': '801890.SI', '国防军工': '801740.SI',
        '汽车': '801880.SI', '商业贸易': '801200.SI', '休闲服务': '801210.SI',
        '综合': '801230.SI',
    }
    
    def __init__(self):
        self._industry_cache = {}
        self._sector_index_cache = {}
    
    def get_industry(self, code: str) -> str:
        """获取股票的申万行业分类"""
        if code in self._industry_cache:
            return self._industry_cache[code]
        
        try:
            df = pro.stock_basic(ts_code=code, fields='ts_code,industry')
            if df is not None and not df.empty:
                industry = df.iloc[0].get('industry', '未知')
            else:
                industry = '未知'
        except Exception:
            industry = '未知'
        
        self._industry_cache[code] = industry
        return industry
    
    def get_sector_index_code(self, industry: str) -> str:
        """行业名 → 申万行业指数代码"""
        return self.SW_INDEX_MAP.get(industry, '000001.SH')  # 默认上证综指
    
    def load_daily(self, code: str, lookback_days: int = 90, end_date: str = None) -> pd.DataFrame:
        """加载日线 + 每日指标"""
        if end_date is None:
            end_date = datetime.now().strftime('%Y%m%d')
        
        trading_days = get_trading_days(lookback_days + 10, end_date)
        start_date = trading_days[0]
        
        try:
            df = pro.daily(ts_code=code, start_date=start_date, end_date=end_date)
            if df is None or df.empty:
                return pd.DataFrame()
            
            df = df.sort_values('trade_date', ascending=False).reset_index(drop=True)
            
            # 每日指标
            try:
                basic = pro.daily_basic(
                    ts_code=code, start_date=start_date, end_date=end_date,
                    fields='ts_code,trade_date,turnover_rate,pe,pb,ps,total_mv,circ_mv'
                )
                if basic is not None and not basic.empty:
                    basic = basic.sort_values('trade_date', ascending=False).reset_index(drop=True)
                    df = df.merge(basic, on=['ts_code', 'trade_date'], how='left')
            except Exception:
                pass
            
            return df
        except Exception as e:
            print(f"    ⚠ {code} 日线数据加载失败: {e}")
            return pd.DataFrame()
    
    def load_moneyflow(self, code: str, lookback_days: int = 90, end_date: str = None) -> pd.DataFrame:
        """加载资金流向"""
        if end_date is None:
            end_date = datetime.now().strftime('%Y%m%d')
        
        trading_days = get_trading_days(lookback_days + 10, end_date)
        start_date = trading_days[0]
        
        try:
            mf = pro.moneyflow(ts_code=code, start_date=start_date, end_date=end_date)
            if mf is not None and not mf.empty:
                return mf.sort_values('trade_date', ascending=False).reset_index(drop=True)
        except Exception:
            pass
        
        return pd.DataFrame()
    
    def load_weekly(self, code: str, lookback_weeks: int = 52, end_date: str = None) -> pd.DataFrame:
        """加载周线数据（用于中长期趋势判断）
        
        参数:
            code: 股票代码
            lookback_weeks: 回溯周数（默认52周≈1年）
            end_date: 结束日期 YYYYMMDD
        
        返回:
            DataFrame: 周线数据，包含 open/high/low/close/vol/amount/pct_chg
        """
        if end_date is None:
            end_date = datetime.now().strftime('%Y%m%d')
        
        # 日线转周线的简单回退：取足够长的日线数据
        # 52周 ≈ 260个交易日，取300天保险
        trading_days = get_trading_days(lookback_weeks * 6 + 20, end_date)
        start_date = trading_days[0]
        
        try:
            # 优先使用 pro.weekly() 获取官方周线数据
            df = pro.weekly(ts_code=code, start_date=start_date, end_date=end_date)
            if df is not None and not df.empty:
                df = df.sort_values('trade_date', ascending=False).reset_index(drop=True)
                return df
        except Exception as e:
            print(f"    ⚠ {code} pro.weekly() 失败: {e}")
        
        # 回退方案：从日线数据合成周线
        try:
            daily_df = self.load_daily(code, lookback_days=lookback_weeks * 6 + 20, end_date=end_date)
            if daily_df is not None and not daily_df.empty and len(daily_df) >= 20:
                weekly = self._daily_to_weekly(daily_df)
                return weekly
        except Exception:
            pass
        
        return pd.DataFrame()
    
    def _daily_to_weekly(self, daily_df: pd.DataFrame) -> pd.DataFrame:
        """日线数据合成为周线数据"""
        df = daily_df.copy()
        df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
        df = df.sort_values('trade_date')
        
        # 按周聚合
        df['year_week'] = df['trade_date'].dt.strftime('%Y%W')
        weekly = df.groupby('year_week').agg({
            'trade_date': 'last',
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'vol': 'sum',
            'amount': 'sum',
        }).reset_index(drop=True)
        
        # 计算周涨跌幅
        weekly['pre_close'] = weekly['close'].shift(1)
        weekly['pct_chg'] = (weekly['close'] - weekly['pre_close']) / weekly['pre_close'] * 100
        weekly['change'] = weekly['close'] - weekly['pre_close']
        
        # 转回字符串日期格式
        weekly['trade_date'] = weekly['trade_date'].dt.strftime('%Y%m%d')
        weekly = weekly.sort_values('trade_date', ascending=False).reset_index(drop=True)
        
        return weekly
    
    def load_sector_index(self, industry: str, lookback_days: int = 90, end_date: str = None) -> pd.DataFrame:
        """加载行业指数日线，失败则降级到上证综指"""
        if end_date is None:
            end_date = datetime.now().strftime('%Y%m%d')
        
        index_code = self.get_sector_index_code(industry)
        trading_days = get_trading_days(lookback_days + 10, end_date)
        start_date = trading_days[0]
        
        try:
            df = pro.index_daily(ts_code=index_code, start_date=start_date, end_date=end_date)
            if df is not None and not df.empty:
                return df.sort_values('trade_date', ascending=False).reset_index(drop=True)
        except Exception:
            pass
        
        # 降级到上证综指
        try:
            df = pro.index_daily(ts_code='000001.SH', start_date=start_date, end_date=end_date)
            if df is not None and not df.empty:
                return df.sort_values('trade_date', ascending=False).reset_index(drop=True)
        except Exception:
            pass
        
        return pd.DataFrame()
    
    def load_limit_data(self, date_str: str = None) -> dict:
        """加载市场涨跌停数据"""
        if date_str is None:
            date_str = datetime.now().strftime('%Y%m%d')
        
        result = {'limit_up_count': 30, 'market_sentiment': 'neutral'}
        
        try:
            df = pro.limit_list_d(date=date_str)
            if df is not None and not df.empty:
                limit_up = df[df['limit'] == 'U']
                result['limit_up_count'] = len(limit_up)
                
                if result['limit_up_count'] > 80:
                    result['market_sentiment'] = 'hot'
                elif result['limit_up_count'] > 40:
                    result['market_sentiment'] = 'bullish'
                elif result['limit_up_count'] < 15:
                    result['market_sentiment'] = 'bearish'
        except Exception:
            pass
        
        return result
    
    def load_all(self, codes: list, lookback_days: int = 90, end_date: str = None, verbose: bool = True) -> dict:
        """批量加载所有数据"""
        if end_date is None:
            end_date = datetime.now().strftime('%Y%m%d')
        
        if verbose:
            print("正在加载股票基本信息...")
        
        # 获取所有股票信息
        try:
            basic_all = pro.stock_basic(exchange='', list_status='L', fields='ts_code,name,industry,list_date')
            stock_info = {}
            for _, row in basic_all.iterrows():
                stock_info[row['ts_code']] = row.to_dict()
        except Exception:
            stock_info = {}
        
        if verbose:
            print(f"正在加载 {len(codes)} 只股票日线数据...")
        
        result = {}
        for code in codes:
            info = stock_info.get(code, {})
            name = info.get('name', code)
            industry = info.get('industry', '未知')
            
            result[code] = {
                'name': name,
                'industry': industry,
                'daily': pd.DataFrame(),
                'moneyflow': pd.DataFrame(),
                'weekly': pd.DataFrame(),
            }
            
            # 日线
            df = self.load_daily(code, lookback_days, end_date)
            result[code]['daily'] = df
            
            if df is not None and not df.empty:
                latest = df.iloc[0]
                if verbose:
                    print(f"  ✓ {name} ¥{latest['close']:.2f} ({latest['pct_chg']:+.2f}%) [{industry}]")
            else:
                if verbose:
                    print(f"  ✗ {name} 无日线数据")
        
        # 资金流向
        if verbose:
            print("正在加载资金流向...")
        for code in codes:
            mf = self.load_moneyflow(code, lookback_days, end_date)
            result[code]['moneyflow'] = mf
        
        # 周线数据（用于中长期趋势判断）
        if verbose:
            print("正在加载周线数据...")
        for code in codes:
            wdf = self.load_weekly(code, lookback_weeks=52, end_date=end_date)
            result[code]['weekly'] = wdf
            if verbose and wdf is not None and not wdf.empty:
                print(f"  ✓ {result[code]['name']} 周线数据 {len(wdf)} 条")
        
        # 市场情绪
        if verbose:
            print("正在加载市场数据...")
        limit_info = self.load_limit_data(end_date)
        result['_market'] = limit_info
        
        # 行业指数
        if verbose:
            print("正在加载行业指数...")
        industries = {r['industry'] for r in result.values() if r.get('industry', '未知') != '未知'}
        sector_data = {}
        for ind in industries:
            si = self.load_sector_index(ind, lookback_days, end_date)
            sector_data[ind] = si
        
        result['_sectors'] = sector_data
        
        return result


# ═══════════════════════════════════════════════════
#  Phase 3: 付费API数据加载器 — 概念板块/北向资金/股东户数
# ═══════════════════════════════════════════════════

def load_concept_mapping(codes, verbose=True):
    """
    通过ths_member API获取每只股票的同花顺概念板块
    
    参数:
        codes: 股票代码列表
        verbose: 是否打印进度
    
    返回:
        dict: {code: [concept_name, ...], ...}
    """
    concept_map = {}
    
    if verbose:
        print("正在加载概念板块映射...")
    
    # 1. 先加载所有概念指数代码→名称映射（加载所有类型）
    concept_index_map = {}
    try:
        for idx_type in ['N', 'I', 'R', 'S', 'TH', 'BB', 'ST']:
            idx_df = pro.ths_index(type=idx_type)
            if idx_df is not None and not idx_df.empty:
                for _, row in idx_df.iterrows():
                    concept_index_map[row['ts_code']] = row['name']
        if verbose:
            print(f"  已加载{len(concept_index_map)}个指数")
    except Exception as e:
        if verbose:
            print(f"  ⚠ 概念指数加载失败: {str(e)[:50]}")
    
    # 2. 对每只股票，获取其所属概念板块（用con_code参数）
    for code in codes:
        try:
            df = pro.ths_member(con_code=code)
            if df is not None and not df.empty:
                concepts = []
                for _, row in df.iterrows():
                    concept_code = row['ts_code']  # 概念指数代码
                    concept_name = concept_index_map.get(concept_code, concept_code)
                    concepts.append(concept_name)
                # 过滤掉宽基指数（同花顺全A等），保留真正有意义的主题概念
                thematic_concepts = [c for c in concepts if not c.startswith('同花顺')]
                # 优先展示概念板块(N型885xxx) → 行业(I型700xxx) → 其他
                n_concepts = [c for c in thematic_concepts if '(A股)' not in c]
                ind_concepts = [c for c in thematic_concepts if '(A股)' in c]
                concept_map[code] = n_concepts + ind_concepts if n_concepts else thematic_concepts[:10]
                if verbose:
                    top_concepts = concept_map[code][:3] if len(concept_map[code]) > 3 else concept_map[code]
                    print(f"  ✓ {code}: {len(concept_map[code])}个主题概念 ({', '.join(top_concepts)}{'…' if len(concept_map[code]) > 3 else ''})")
            else:
                concept_map[code] = []
        except Exception as e:
            if verbose:
                print(f"  ⚠ {code} 概念加载失败: {str(e)[:50]}")
            concept_map[code] = []
    
    return concept_map


def load_north_flow(lookback_days=20, end_date=None):
    """
    通过moneyflow_hsgt API获取北向资金流向
    
    返回:
        dict: {
            'recent_flow': 最近5日累计净流入(亿),
            'direction': 'inflow'/'outflow'/'neutral',
            'daily_flows': [{date: net_flow}, ...],
            'strength': 连续净流入天数,
        }
    """
    if end_date is None:
        end_date = datetime.now().strftime('%Y%m%d')
    
    trading_days = get_trading_days(lookback_days + 10, end_date)
    start_date = trading_days[0] if trading_days else end_date
    
    result = {
        'recent_flow': 0, 'direction': 'neutral',
        'daily_flows': [], 'strength': 0,
    }
    
    try:
        df = pro.moneyflow_hsgt(start_date=start_date, end_date=end_date)
        if df is not None and not df.empty:
            df = df.sort_values('trade_date', ascending=False).reset_index(drop=True)
            
            # 最近5日北向净流入（万元→亿元）
            north_flows = df['north_money'].head(5).tolist()
            recent_flow = sum(float(f) for f in north_flows if f is not None and f != '' and not (isinstance(f, float) and np.isnan(f)))
            result['recent_flow'] = round(recent_flow / 10000, 2)  # 万元→亿元
            
            if recent_flow > 50:
                result['direction'] = 'inflow'
            elif recent_flow < -50:
                result['direction'] = 'outflow'
            else:
                result['direction'] = 'neutral'
            
            # 连续净流入天数
            strength = 0
            for _, row in df.iterrows():
                nm = row.get('north_money', 0) or 0
                try:
                    nm = float(nm)
                except (ValueError, TypeError):
                    nm = 0
                if nm > 0:
                    strength += 1
                else:
                    break
            result['strength'] = strength
            
            # 每日明细
            for _, row in df.head(10).iterrows():
                result['daily_flows'].append({
                    'date': row['trade_date'],
                    'north_money': round(float(row.get('north_money', 0) or 0), 2),
                })
    except Exception as e:
        print(f"  ⚠ 北向资金数据加载失败: {e}")
    
    return result


def load_holder_data(codes, end_date=None, verbose=True):
    """
    通过stk_holdernumber API获取股东户数变化趋势
    
    返回:
        dict: {
            code: {
                'trend': 'concentrating'/'dispersing'/'stable',
                'change_pct': 最近一期变化百分比,
                'latest_holder_num': 最新股东户数,
                'history': [...],
            }
        }
    """
    if end_date is None:
        end_date = datetime.now().strftime('%Y%m%d')
    
    holder_data = {}
    
    if verbose:
        print("正在加载股东户数数据...")
    
    for code in codes:
        try:
            df = pro.stk_holdernumber(ts_code=code, end_date=end_date)
            if df is not None and not df.empty:
                df = df.sort_values('end_date', ascending=False).reset_index(drop=True)
                
                latest = df.iloc[0]
                holder_num = int(latest['holder_num'])
                
                # 计算趋势：对比上一期
                if len(df) >= 2:
                    prev_num = int(df.iloc[1]['holder_num'])
                    change_pct = round((holder_num / prev_num - 1) * 100, 2)
                    
                    if change_pct < -5:
                        trend = 'concentrating'  # 筹码集中
                    elif change_pct > 5:
                        trend = 'dispersing'     # 筹码分散
                    else:
                        trend = 'stable'
                else:
                    change_pct = 0
                    trend = 'stable'
                
                holder_data[code] = {
                    'trend': trend,
                    'change_pct': change_pct,
                    'latest_holder_num': holder_num,
                    'history': [
                        {'end_date': row['end_date'], 'holder_num': int(row['holder_num'])}
                        for _, row in df.head(3).iterrows()
                    ],
                }
                
                if verbose:
                    trend_icon = '📈集中' if trend == 'concentrating' else ('📉分散' if trend == 'dispersing' else '➡️稳定')
                    print(f"  ✓ {code}: {holder_num}户 ({trend_icon} {change_pct:+.1f}%)")
            else:
                holder_data[code] = {'trend': 'stable', 'change_pct': 0, 'latest_holder_num': 0}
        except Exception as e:
            if verbose:
                print(f"  ⚠ {code} 股东户数加载失败: {str(e)[:50]}")
            holder_data[code] = {'trend': 'stable', 'change_pct': 0, 'latest_holder_num': 0}
    
    return holder_data


def load_zscore_data(verbose=True):
    """
    加载板块ZSCORE数据（从板块热度观察系统产出）
    
    数据新鲜度检查：如果最新文件距今超过2个交易日，标记为不新鲜
    
    返回:
        tuple: (DataFrame, date_str, is_fresh)
            DataFrame: 包含 sector_code, sector_name, z_price, z_vol, z_composite 等
            date_str: 数据日期字符串 (YYYYMMDD)
            is_fresh: bool, 是否新鲜（<=2天）
            如果加载失败返回 (None, None, False)
    """
    if not os.path.isdir(ZSCORE_DATA_DIR):
        if verbose:
            print(f"  ⚠ ZSCORE数据目录不存在: {ZSCORE_DATA_DIR}")
        return None, None, False
    
    # 查找所有 zscore_data_*.csv 文件，按日期降序排列
    zscore_files = []
    for fname in os.listdir(ZSCORE_DATA_DIR):
        if fname.startswith('zscore_data_') and fname.endswith('.csv'):
            # 提取日期
            date_part = fname.replace('zscore_data_', '').replace('.csv', '')
            if date_part.isdigit() and len(date_part) == 8:
                zscore_files.append((date_part, fname))
    
    if not zscore_files:
        if verbose:
            print(f"  ⚠ 未找到ZSCORE数据文件")
        return None, None, False
    
    # 按日期降序，取最新
    zscore_files.sort(key=lambda x: x[0], reverse=True)
    latest_date, latest_file = zscore_files[0]
    
    # 新鲜度检查：计算最新文件日期与今天的交易日差距
    today = datetime.now().strftime('%Y%m%d')
    try:
        # 获取交易日历计算差距
        cal_df = pro.trade_cal(exchange='SSE', start_date=latest_date, end_date=today, is_open='1')
        if cal_df is not None and not cal_df.empty:
            trading_days_between = len(cal_df) - 1  # 减1因为包含起始日
            is_fresh = trading_days_between <= 2
        else:
            # fallback: 简单日历天数
            d_latest = datetime.strptime(latest_date, '%Y%m%d')
            d_today = datetime.strptime(today, '%Y%m%d')
            is_fresh = (d_today - d_latest).days <= 3
    except Exception:
        is_fresh = True  # 无法判断时默认新鲜
    
    # 加载数据
    filepath = os.path.join(ZSCORE_DATA_DIR, latest_file)
    try:
        df = pd.read_csv(filepath, encoding='utf-8-sig')
        if df is not None and not df.empty:
            # 只保留最新日期的数据（ZSCORE CSV包含多日期历史数据）
            if 'trade_date' in df.columns:
                df['trade_date'] = df['trade_date'].astype(str)
                max_date = df['trade_date'].max()
                df = df[df['trade_date'] == max_date].copy()

            # 数据质量检查：检测是否所有 z_composite=0 且 z_price 为空（列名映射错误的历史问题）
            has_z_price = 'z_price' in df.columns
            has_z_composite = 'z_composite' in df.columns
            if has_z_price and has_z_composite:
                valid_z = df['z_composite'].notna() & (df['z_composite'] != 0)
                if valid_z.sum() == 0:
                    if verbose:
                        print(f"  ⚠ ZSCORE数据异常：所有板块 z_composite=0/z_price为空，可能因源数据列名映射错误导致")
                    is_fresh = False  # 强制标记为不新鲜，触发评估系统回退逻辑

            if verbose:
                fresh_mark = "✓ 新鲜" if is_fresh else "⚠ 滞后"
                print(f"  ✓ ZSCORE数据加载: {latest_date} ({len(df)}个板块) [{fresh_mark}]")
            return df, latest_date, is_fresh
        else:
            if verbose:
                print(f"  ⚠ ZSCORE数据文件为空: {latest_file}")
            return None, None, False
    except Exception as e:
        if verbose:
            print(f"  ⚠ ZSCORE数据加载失败: {e}")
        return None, None, False


# ═══════════════════════════════════════════════════
#  ZSCORE匹配与信号判断
# ═══════════════════════════════════════════════════

def _get_zscore_signal(z_composite):
    """根据ZSCORE综合值判断信号"""
    if pd.isna(z_composite) or z_composite == 0:
        return 'neutral', '数据不足/无信号'
    if z_composite >= 2.0:
        return 'overheat', '过热预警(≥2.0)'
    elif z_composite >= 1.0:
        return 'hot', '偏热(1.0~2.0)'
    elif z_composite <= -2.0:
        return 'oversold', '超跌机会(≤-2.0)'
    elif z_composite <= -1.0:
        return 'cold', '偏冷(-2.0~-1.0)'
    else:
        return 'neutral', '正常区间'


def match_zscore(industry, zscore_df):
    """
    将股票的申万行业匹配到ZSCORE板块数据
    
    匹配策略：
    1. 精确匹配 sector_name 包含 industry 关键词
    2. 模糊匹配 sector_name 与 industry 有交集
    
    返回:
        dict: {
            'z_price': float, 'z_vol': float, 'z_composite': float,
            'signal': str, 'signal_desc': str, 'sector_name': str,
            'matched': bool
        }
    """
    result = {
        'z_price': 0.0, 'z_vol': 0.0, 'z_composite': 0.0,
        'signal': 'neutral', 'signal_desc': '未匹配',
        'sector_name': '', 'matched': False,
    }
    
    if zscore_df is None or zscore_df.empty or not industry or industry == '未知':
        return result
    
    # 申万行业名 → 关键词列表（处理三级子行业名与申万一级的差异）
    # 例如 industry='电子' 可能对应 sector_name='半导体Ⅲ'、'元器件Ⅲ' 等
    industry_keywords = _build_industry_keywords(industry)
    
    best_match = None
    best_score = 0
    
    for _, row in zscore_df.iterrows():
        sname = str(row.get('sector_name', ''))
        score = 0
        
        # 精确包含
        for kw in industry_keywords:
            if kw in sname:
                score += 2
            elif sname in kw:
                score += 1
        
        # 也检查 sector_name 是否在 industry 中
        if industry in sname or sname in industry:
            score += 3
        
        if score > best_score:
            best_score = score
            best_match = row
    
    if best_match is not None and best_score >= 2:
        z_price = float(best_match.get('z_price', 0) or 0)
        z_vol = float(best_match.get('z_vol', 0) or 0)
        z_composite = float(best_match.get('z_composite', 0) or 0)
        
        sig, sig_desc = _get_zscore_signal(z_composite)
        
        result.update({
            'z_price': z_price,
            'z_vol': z_vol,
            'z_composite': z_composite,
            'signal': sig,
            'signal_desc': sig_desc,
            'sector_name': str(best_match.get('sector_name', '')),
            'matched': True,
        })
    
    return result


def _build_industry_keywords(industry):
    """构建行业关键词映射（申万一级 → 可能的子行业关键词）"""
    keyword_map = {
        '电子': ['电子', '半导体', '元器件', '集成电路', '芯片', '面板', 'LED', 'PCB'],
        '计算机': ['计算机', '软件', '信息服务', '信息技术', '互联网'],
        '通信': ['通信', '通信设备', '通信服务', '电信'],
        '医药生物': ['医药', '生物制药', '医疗保健', '化学制药', '中药', '中成药', 'CRO', '医疗器械'],
        '食品饮料': ['食品', '饮料', '白酒', '乳制品', '调味品'],
        '家用电器': ['家电', '家用电器', '白色家电', '黑色家电', '小家电'],
        '电气设备': ['电气', '电气设备', '电源', '储能', '光伏', '风电', '新能源'],
        '机械设备': ['机械', '机械设备', '专用机械', '通用机械', '机械基件', '机床'],
        '国防军工': ['军工', '航空', '航天', '国防', '军民融合'],
        '汽车': ['汽车', '汽车配件', '新能源汽车', '整车', '零部件'],
        '化工': ['化工', '化学', '化工原料', '塑料', '橡胶', '涂料'],
        '有色金属': ['有色', '有色金属', '稀土', '锂', '钴', '铜', '铝'],
        '钢铁': ['钢铁', '特钢', '普钢'],
        '银行': ['银行'],
        '非银金融': ['证券', '保险', '非银', '信托', '期货', '多元金融'],
        '房地产': ['房地产', '地产'],
        '建筑材料': ['建材', '建筑材料', '水泥', '玻璃', '其他建材'],
        '建筑装饰': ['建筑', '建筑装饰', '建筑工程'],
        '交通运输': ['交通', '运输', '物流', '航运', '航空运输', '铁路', '公路'],
        '公用事业': ['公用事业', '电力', '环保', '水务', '燃气'],
        '农林牧渔': ['农业', '畜牧', '饲料', '种业', '渔业'],
        '商业贸易': ['商业', '贸易', '零售', '百货', '超市', '连锁'],
        '休闲服务': ['休闲', '旅游', '酒店', '餐饮', '传媒', '影视', '游戏'],
        '纺织服装': ['纺织', '服装', '服饰'],
        '轻工制造': ['轻工', '造纸', '家居', '包装'],
        '采掘': ['采掘', '煤炭', '石油', '矿业', '天然气'],
        '综合': ['综合'],
    }
    
    # 直接返回关键词列表
    keywords = keyword_map.get(industry, [industry])
    # 加入行业名本身
    if industry not in keywords:
        keywords.insert(0, industry)
    return keywords


# ═══════════════════════════════════════════════════
#  ZSCORE四维共振评估
# ═══════════════════════════════════════════════════

def calc_zscore_resonance(industry, zscore_df, stock_df=None, sector_df=None, hot_theme=''):
    """
    板块ZSCORE四维共振评估 — 天时/地利/人和/技术共振
    
    维度说明：
    - 天时：板块ZSCORE位置（是否处于超跌反弹区或过热区）
    - 地利：行业是否为当前主线/热门方向
    - 人和：板块内资金面（成交量ZSCORE是否放大）
    - 技术：个股技术面是否与板块共振（个股趋势+板块ZSCORE方向一致）
    
    返回:
        dict: {
            'score': float (0~100),
            'signals': list[str],
            'resonance_count': int (0~4),
            'zscore_info': dict (match_zscore的结果),
            'dimensions': dict,
        }
    """
    base_result = {
        'score': 50,
        'signals': [],
        'resonance_count': 0,
        'zscore_info': {},
        'dimensions': {'天时': False, '地利': False, '人和': False, '技术': False},
    }
    
    # 1. 匹配ZSCORE数据
    zinfo = match_zscore(industry, zscore_df)
    base_result['zscore_info'] = zinfo
    
    if not zinfo['matched']:
        # 尝试使用行业指数5日涨幅作为简化替代
        if sector_df is not None and not sector_df.empty and len(sector_df) >= 5:
            s5d = sector_df['pct_chg'].head(5).sum()
            if s5d > 5:
                base_result['signals'].append(f"天时~行业5日涨{s5d:.1f}%·偏强(简化替代)")
            elif s5d < -5:
                base_result['signals'].append(f"天时~行业5日跌{s5d:.1f}%·偏弱(简化替代)")
            else:
                base_result['signals'].append(f"天时~行业5日涨{s5d:.1f}%·中性(简化替代)")
        else:
            base_result['signals'].append('ZSCORE未匹配板块')
        return base_result
    
    z_composite = zinfo['z_composite']
    z_price = zinfo['z_price']
    z_vol = zinfo['z_vol']
    score = 50
    signals = []
    dim_flags = {'天时': False, '地利': False, '人和': False, '技术': False}
    
    # ── 天时：板块ZSCORE位置 ──
    if z_composite <= -2.0:
        # 超跌区 — 反弹潜力大
        score += 20
        signals.append(f"天时✓板块超跌(z={z_composite:.1f})·反弹窗口")
        dim_flags['天时'] = True
    elif z_composite <= -1.0:
        # 偏冷区 — 低位企稳
        score += 12
        signals.append(f"天时✓板块偏冷(z={z_composite:.1f})·低位机会")
        dim_flags['天时'] = True
    elif z_composite >= 2.0:
        # 过热区 — 风险提示
        score -= 10
        signals.append(f"天时✗板块过热(z={z_composite:.1f})·追高风险")
    elif z_composite >= 1.0:
        # 偏热区 — 注意节奏
        score -= 3
        signals.append(f"天时~板块偏热(z={z_composite:.1f})")
    else:
        signals.append(f"天时~板块中性(z={z_composite:.1f})")
    
    # ── 地利：行业是否为当前主线 ──
    theme = THEME_MAP.get(industry, '其他')
    priority = THEME_PRIORITY.get(theme, 6)
    
    if priority <= 2:
        score += 15
        signals.append(f"地利✓{theme}·主线方向")
        dim_flags['地利'] = True
    elif priority <= 3:
        score += 8
        signals.append(f"地利~{theme}·活跃题材")
        dim_flags['地利'] = True
    else:
        signals.append(f"地利~{theme}·非主线")
    
    # 如果传入的hot_theme与当前theme一致，额外加分
    if hot_theme and hot_theme == theme:
        score += 5
        signals.append("地利✓热度验证一致")
    
    # ── 人和：板块成交量ZSCORE ──
    if not pd.isna(z_vol) and z_vol != 0:
        if z_vol >= 1.5:
            score += 12
            signals.append(f"人和✓放量确认(z_vol={z_vol:.1f})")
            dim_flags['人和'] = True
        elif z_vol >= 1.0:
            score += 6
            signals.append(f"人和~温和放量(z_vol={z_vol:.1f})")
            dim_flags['人和'] = True
        elif z_vol <= -1.5:
            score -= 5
            signals.append(f"人和✗缩量低迷(z_vol={z_vol:.1f})")
        else:
            signals.append(f"人和~量能中性(z_vol={z_vol:.1f})")
    else:
        signals.append("人和~量能数据不足")
    
    # ── 技术：个股趋势与板块ZSCORE方向一致性 ──
    tech_resonance = False
    if stock_df is not None and not stock_df.empty and len(stock_df) >= 5:
        pct5d = stock_df['pct_chg'].head(5).sum()
        close = stock_df.iloc[0]['close']
        ma20 = stock_df['close'].head(20).mean() if len(stock_df) >= 20 else close
        
        # 个股上涨 + 板块超跌/偏冷 → 技术共振（个股先于板块启动）
        if pct5d > 3 and z_composite <= -1.0:
            score += 15
            signals.append(f"技术✓个股先于板块启动(5日{pct5d:+.1f}%+板块z={z_composite:.1f})")
            tech_resonance = True
        # 个股上涨 + 板块偏热 → 顺势共振
        elif pct5d > 3 and z_composite > 0:
            score += 10
            signals.append(f"技术✓顺势共振(5日{pct5d:+.1f}%+板块向好)")
            tech_resonance = True
        # 个股在20日均线上方 + 板块向上
        elif close > ma20 and z_composite > 0.5:
            score += 8
            signals.append("技术✓均线多头+板块向上")
            tech_resonance = True
        # 个股下跌 + 板块过热 → 逆风
        elif pct5d < -3 and z_composite >= 1.5:
            score -= 8
            signals.append(f"技术✗逆风(5日{pct5d:+.1f}%+板块过热)")
        else:
            signals.append("技术~无明确共振")
    else:
        signals.append("技术~数据不足")
    
    dim_flags['技术'] = tech_resonance
    
    # 共振计数
    resonance_count = sum(1 for v in dim_flags.values() if v)
    
    # 四维全共振额外奖励
    if resonance_count == 4:
        score += 10
        signals.append("★四维共振·强烈信号")
    elif resonance_count == 3:
        score += 5
        signals.append("☆三维共振·较强信号")
    
    score = min(100, max(0, score))
    
    return {
        'score': score,
        'signals': signals,
        'resonance_count': resonance_count,
        'zscore_info': zinfo,
        'dimensions': dim_flags,
    }


# ═══════════════════════════════════════════════════
#  反身性分析模块 v4.2（Reflexivity Analysis — 三阶段模型）
# ═══════════════════════════════════════════════════

def detect_bubble_signals(df, mf_df, holder_data=None):
    """
    检测反身性第三阶段（证伪/泡沫破裂）的四个信号
    
    返回: list[str] — 检测到的证伪信号列表
    """
    bubble_signals = []
    if df is None or df.empty or len(df) < 5:
        return bubble_signals
    
    close = df['close'].astype(float)
    pct_chg = df['pct_chg'].astype(float)
    vol = df['vol'].astype(float)
    latest_close = close.iloc[0]
    latest_pct = pct_chg.iloc[0]
    
    # 信号1: 价格创新高（近5日高点）但资金大幅流出
    if mf_df is not None and not mf_df.empty:
        recent_high = close.head(5).max()
        is_near_high = latest_close >= recent_high * 0.98
        
        mf_5d = mf_df.head(5)
        net_mf_5d = mf_5d['net_mf_amount'].sum() if 'net_mf_amount' in mf_5d.columns else 0
        
        if is_near_high and net_mf_5d < -5000000:  # 5日净流出>500万
            bubble_signals.append("🚨 顶部背离: 价格创新高但资金大幅流出")
    
    # 信号2: 成交量萎缩但价格继续上涨（买盘枯竭）
    if len(vol) >= 5:
        recent_avg_vol = vol.head(3).mean()
        prev_avg_vol = vol.iloc[3:6].mean() if len(vol) >= 6 else vol.mean()
        vol_ratio = recent_avg_vol / prev_avg_vol if prev_avg_vol > 0 else 1.0
        
        if vol_ratio < 0.7 and latest_pct > 0:
            bubble_signals.append(f"🚨 买盘枯竭: 缩量上涨(量能萎缩{vol_ratio:.0%})")
    
    # 信号3: 基本面数据不及预期（PE过高或业绩下滑）
    # 尝试从df中获取daily_basic字段
    pe_ttm = None
    pb = None
    if 'pe_ttm' in df.columns:
        pe_ttm = pd.to_numeric(df.iloc[0].get('pe_ttm'), errors='coerce')
    if 'pb' in df.columns:
        pb = pd.to_numeric(df.iloc[0].get('pb'), errors='coerce')
    
    if pe_ttm is not None and not pd.isna(pe_ttm) and pe_ttm > 100:
        bubble_signals.append(f"🚨 估值泡沫: 滚动PE高达{pe_ttm:.1f}倍")
    if pb is not None and not pd.isna(pb) and pb > 10:
        bubble_signals.append(f"🚨 估值泡沫: PB高达{pb:.1f}倍")
    
    # 信号4: 大股东/高管减持（holder_data中检测户数激增）
    if holder_data is not None:
        holder_pct = holder_data.get('holder_pct', 0)
        if holder_pct > 30:
            bubble_signals.append(f"🚨 筹码分散: 股东户数激增{holder_pct:.1f}%（大股东减持迹象）")
    
    return bubble_signals


def _calc_sbi(df, mf_df):
    """
    计算主流偏见指数 (Sentiment Bias Index, SBI)
    取值范围: -100 ~ +100
    +值越大 = 市场越乐观/偏见越强
    -值越大 = 市场越悲观/偏见越强
    """
    if df is None or df.empty or len(df) < 20:
        return 0, {}
    
    close = df['close'].astype(float)
    vol = df['vol'].astype(float)
    pct_chg = df['pct_chg'].astype(float)
    
    # 基础统计
    ret_5d = pct_chg.head(5).sum()
    ret_20d_avg = pct_chg.head(20).mean() * 5  # 近20日平均5日涨幅
    turnover = vol / (close * 1e8)  # 近似换手率 (假设流通股本=close*1e8)
    avg_turnover_20 = turnover.head(20).mean()
    latest_turnover = turnover.iloc[0]
    
    factors = {}
    
    # 1. 价格动量溢价（25%权重）
    if abs(ret_20d_avg) > 0.1:
        pm_premium = (ret_5d - ret_20d_avg) / abs(ret_20d_avg)
    else:
        pm_premium = ret_5d / 10
    factors['price_momentum'] = max(-1, min(1, pm_premium))
    
    # 2. 换手率溢价（20%权重）
    if avg_turnover_20 > 0:
        to_premium = (latest_turnover - avg_turnover_20) / avg_turnover_20
    else:
        to_premium = 0
    factors['turnover_premium'] = max(-1, min(1, to_premium))
    
    # 3. 资金流入强度（25%权重）
    capital_factor = 0
    if mf_df is not None and not mf_df.empty and 'net_mf_amount' in mf_df.columns:
        mf_5d = mf_df.head(5)
        net_mf = mf_5d['net_mf_amount'].sum()
        amt_5d = mf_5d['buy_amount'].sum() + mf_5d['sell_amount'].sum() if 'buy_amount' in mf_5d.columns else 0
        if amt_5d > 0:
            capital_factor = net_mf / amt_5d  # 净流入占比
    factors['capital_inflow'] = max(-1, min(1, capital_factor))
    
    # 4. 情绪扩散指数（15%权重）
    if len(vol) >= 10:
        vol_ma10 = vol.head(10).mean()
        high_vol_days = sum(vol.head(10) > vol_ma10 * 1.5)
        diffusion = (high_vol_days / 10) * 2 - 1  # 映射到 [-1, 1]
    else:
        diffusion = 0
    factors['sentiment_diffusion'] = max(-1, min(1, diffusion))
    
    # 5. 量价背离（15%权重）
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
    
    # 加权合成 SBI
    sbi = (
        factors['price_momentum'] * 0.25 +
        factors['turnover_premium'] * 0.20 +
        factors['capital_inflow'] * 0.25 +
        factors['sentiment_diffusion'] * 0.15 +
        factors['vol_price_divergence'] * 0.15
    ) * 100
    
    return max(-100, min(100, sbi)), factors


def calc_reflexivity(df, mf_df=None, sector_df=None, hot_theme='',
                     holder_data=None):
    """
    反身性四象限分析 v5.0 — 基于主流偏见-价格趋势的连续评分模型
    
    核心维度:
      1. 主流偏见指数 (SBI): -100~+100，反映市场乐观/悲观程度
      2. 价格趋势方向: -1~+1，反映价格涨跌趋势
      
    四象限定位:
      Q1(+偏见, +价格): 自我强化 — 正反馈循环，趋势延续
      Q2(+偏见, -价格): 萌芽/纠偏 — 乐观但价格未反应，或暴涨后纠偏
      Q3(-偏见, -价格): 恐慌/弱势 — 负反馈循环，恐慌抛售
      Q4(-偏见, +价格): 背离反弹 — 反弹缺乏共识，易受利空打压
    
    返回: dict {
        'score': float,              # 0-100 综合反身性评分（强度绝对值）
        'stage': int,                # 保留兼容性: 1=Q1, 2=Q2, 3=Q3, 4=Q4
        'stage_name': str,           # 象限名称
        'quadrant': str,             # Q1/Q2/Q3/Q4
        'sbi': float,                # 主流偏见指数 -100~+100
        'price_trend': float,        # 价格趋势 -1~+1
        'reflexivity_strength': float, # 反身性强度 -100~+100
        'stage_signals': list,       # 象限特征信号
        'operation': str,            # 操作建议
        'bubble_signals': list,      # 泡沫信号（风险叠加层）
        'sbi_factors': dict,         # SBI各子因子详情
        'all_signals': list,         # 所有子指标信号
    }
    """
    # 默认值
    result = {
        'score': 50, 'stage': 0, 'stage_name': '阶段不明',
        'quadrant': 'Q0', 'sbi': 0, 'price_trend': 0,
        'reflexivity_strength': 0,
        'stage_signals': ['数据不足'],
        'operation': '➡️ 观望',
        'bubble_signals': [],
        'sbi_factors': {},
        'all_signals': ['数据不足'],
    }
    
    if df is None or df.empty or len(df) < 10:
        return result
    
    import numpy as np
    close = df['close'].astype(float)
    pct_chg = df['pct_chg'].astype(float)
    vol = df['vol'].astype(float)
    
    # 【修复】tushare 返回 df 按日期升序排列（老在前，新在后）
    # 必须用 .iloc[-1] 取最新值，.tail(5) 取最近 5 天
    latest_pct = pct_chg.iloc[-1]  # 最新交易日涨跌幅
    latest_close = close.iloc[-1]
    latest_vol = vol.iloc[-1]
    
    # ── 1. 计算主流偏见指数 SBI ──
    sbi, sbi_factors = _calc_sbi(df, mf_df)
    
    # ── 2. 计算价格趋势方向 ──
    ret_5d = pct_chg.tail(5).sum()  # 最近 5 天累计涨幅
    
    # 涨跌停日特殊处理
    is_limit_up = latest_pct >= 9.9      # 涨停
    is_limit_down = latest_pct <= -9.9   # 跌停
    
    if is_limit_up:
        price_trend = 0.95
        ret_5d_used = ret_5d
    elif is_limit_down:
        price_trend = -0.95
        ret_5d_used = ret_5d
    else:
        price_trend = np.tanh(ret_5d / 8.0)
        ret_5d_used = ret_5d
    
    # ── 3. 四象限定位 ──
    bias_threshold = 0.15
    trend_threshold = 0.15
    
    bias_norm = sbi / 100
    
    if bias_norm > bias_threshold and price_trend > trend_threshold:
        quadrant = "Q1"
        stage_name = "自我强化"
        stage = 1
        stage_signals = [
            f"偏见乐观(sbi={sbi:+.0f})",
            f"价格上涨({ret_5d_used:+.1f}%)",
            "正反馈循环"
        ]
        operation = "📈 趋势跟随，但必须设移动止盈"
        score = 60 + abs(sbi) * 0.25
    elif bias_norm > bias_threshold and price_trend <= trend_threshold:
        quadrant = "Q2"
        stage_name = "萌芽/纠偏"
        stage = 2
        stage_signals = [
            f"偏见乐观(sbi={sbi:+.0f})",
            f"价格未涨({ret_5d_used:+.1f}%)",
            "预期领先价格或纠偏中"
        ]
        operation = "💎 观察等待，若价格突破可跟进"
        score = 70 + abs(sbi) * 0.15
    elif bias_norm <= bias_threshold and price_trend > trend_threshold:
        # 【修复】涨停日即使偏见转负，仍应判定为偏强象限
        if is_limit_up:
            quadrant = "Q4"
            stage_name = "背离反弹"
            stage = 4
            stage_signals = [
                f"偏见悲观(sbi={sbi:+.0f})",
                f"涨停突破({ret_5d_used:+.1f}%)",
                "反弹缺乏共识，但价格强势确认"
            ]
            operation = "⚠️ 谨慎参与，反弹随时可能结束"
            score = 50 + abs(sbi) * 0.1
        else:
            quadrant = "Q4"
            stage_name = "背离反弹"
            stage = 4
            stage_signals = [
                f"偏见悲观(sbi={sbi:+.0f})",
                f"价格上涨({ret_5d_used:+.1f}%)",
                "反弹缺乏共识"
            ]
            operation = "⚠️ 谨慎参与，反弹随时可能结束"
            score = 40 + abs(sbi) * 0.1
    else:
        quadrant = "Q3"
        stage_name = "恐慌/弱势"
        stage = 3
        stage_signals = [
            f"偏见悲观(sbi={sbi:+.0f})",
            f"价格下跌({ret_5d_used:+.1f}%)",
            "负反馈循环"
        ]
        operation = "🚫 回避，等待情绪企稳"
        score = max(10, 30 - abs(sbi) * 0.2)
    
    # ── 4. 反身性强度 ──
    reflexivity_strength = bias_norm * price_trend * 100
    
    # ── 5. 泡沫信号检测（风险叠加层） ──
    bubble_signals = detect_bubble_signals(df, mf_df, holder_data)
    if bubble_signals:
        stage_signals.extend([f"⚠️ {s}" for s in bubble_signals])
        score = max(10, score - len(bubble_signals) * 8)
        operation = "🚨 " + operation.replace("📈 ", "").replace("💎 ", "").replace("⚠️ ", "") + "（泡沫风险叠加）"
    
    # ── 6. 收集所有信号 ──
    all_signals = stage_signals.copy()
    all_signals.append(f"SBI={sbi:+.0f} 价格趋势={price_trend:+.2f}")
    
    return {
        'score': min(100, max(0, score)),
        'stage': stage,
        'stage_name': stage_name,
        'quadrant': quadrant,
        'sbi': round(sbi, 1),
        'price_trend': round(price_trend, 2),
        'reflexivity_strength': round(reflexivity_strength, 1),
        'stage_signals': stage_signals,
        'operation': operation,
        'bubble_signals': bubble_signals,
        'sbi_factors': sbi_factors,
        'all_signals': all_signals,
    }


# ═══════════════════════════════════════════════════
#  周线分析模块 (Weekly Analysis)
# ═══════════════════════════════════════════════════

def calc_weekly(weekly_df):
    """
    周线级别技术面分析 — 中长期趋势判断
    
    评分维度（0-100分）：
      1. 均线排列（30%）：周MA5/MA10/MA20多头排列程度
      2. 趋势强度（25%）：近4/8/12周涨幅加权
      3. MACD状态（25%）：周线MACD柱状态
      4. 成交量确认（20%）：上涨周是否放量
    
    返回: dict {
        'score': float,        # 0-100 周线综合评分
        'trend': str,          # 趋势判断：强势上涨/上涨/震荡/下跌/深度下跌
        'signals': list,       # 信号列表
        'ma_status': str,      # 均线状态描述
        'macd_status': str,    # MACD状态描述
        'vol_status': str,     # 成交量状态描述
    }
    """
    result = {
        'score': 50,
        'trend': '震荡',
        'signals': [],
        'ma_status': '数据不足',
        'macd_status': '数据不足',
        'vol_status': '数据不足',
    }
    
    if weekly_df is None or weekly_df.empty or len(weekly_df) < 20:
        result['signals'].append('周线: 数据不足')
        return result
    
    close = weekly_df['close'].astype(float)
    vol = weekly_df['vol'].astype(float)
    pct_chg = weekly_df['pct_chg'].astype(float) if 'pct_chg' in weekly_df.columns else pd.Series([0] * len(weekly_df))
    
    # ── 1. 均线排列（30分） ──
    ma5 = close.rolling(window=5, min_periods=3).mean()
    ma10 = close.rolling(window=10, min_periods=5).mean()
    ma20 = close.rolling(window=20, min_periods=10).mean()
    
    latest_ma5 = ma5.iloc[0] if not ma5.empty and not pd.isna(ma5.iloc[0]) else 0
    latest_ma10 = ma10.iloc[0] if not ma10.empty and not pd.isna(ma10.iloc[0]) else 0
    latest_ma20 = ma20.iloc[0] if not ma20.empty and not pd.isna(ma20.iloc[0]) else 0
    
    ma_score = 0
    if latest_ma5 > latest_ma10 > latest_ma20:
        ma_score = 30
        result['ma_status'] = '周均线多头排列'
        result['signals'].append('周线·MA多头排列')
    elif latest_ma5 > latest_ma10:
        ma_score = 20
        result['ma_status'] = '短期均线金叉'
        result['signals'].append('周线·短期金叉')
    elif latest_ma5 > latest_ma20:
        ma_score = 10
        result['ma_status'] = '中期支撑有效'
    elif latest_ma5 < latest_ma10 < latest_ma20:
        ma_score = 0
        result['ma_status'] = '周均线空头排列'
        result['signals'].append('周线·MA空头排列')
    else:
        ma_score = 10
        result['ma_status'] = '均线缠绕'
    
    # ── 2. 趋势强度（25分） ──
    trend_score = 0
    if len(close) >= 12:
        ret_4w = (close.iloc[0] - close.iloc[3]) / close.iloc[3] * 100 if close.iloc[3] > 0 else 0
        ret_8w = (close.iloc[0] - close.iloc[7]) / close.iloc[7] * 100 if close.iloc[7] > 0 else 0
        ret_12w = (close.iloc[0] - close.iloc[11]) / close.iloc[11] * 100 if close.iloc[11] > 0 else 0
        
        weighted_ret = ret_4w * 0.5 + ret_8w * 0.3 + ret_12w * 0.2
        
        if weighted_ret > 15:
            trend_score = 25
            result['signals'].append(f'周线·强势上涨({weighted_ret:.1f}%)')
        elif weighted_ret > 5:
            trend_score = 20
            result['signals'].append(f'周线·上涨趋势({weighted_ret:.1f}%)')
        elif weighted_ret > -5:
            trend_score = 12
            result['signals'].append(f'周线·横盘震荡({weighted_ret:.1f}%)')
        elif weighted_ret > -15:
            trend_score = 5
            result['signals'].append(f'周线·下跌趋势({weighted_ret:.1f}%)')
        else:
            trend_score = 0
            result['signals'].append(f'周线·深度下跌({weighted_ret:.1f}%)')
        
        result['trend'] = '强势上涨' if weighted_ret > 15 else '上涨' if weighted_ret > 5 else '震荡' if weighted_ret > -5 else '下跌' if weighted_ret > -15 else '深度下跌'
    
    # ── 3. MACD状态（25分） ──
    macd_score = 0
    if len(close) >= 26:
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        macd_hist = (dif - dea) * 2
        
        latest_dif = dif.iloc[0] if not dif.empty else 0
        latest_dea = dea.iloc[0] if not dea.empty else 0
        latest_hist = macd_hist.iloc[0] if not macd_hist.empty else 0
        prev_hist = macd_hist.iloc[1] if len(macd_hist) > 1 else latest_hist
        
        if latest_dif > latest_dea and latest_hist > 0:
            if latest_hist > prev_hist:
                macd_score = 25
                result['macd_status'] = 'MACD红柱放大·强势'
                result['signals'].append('周线·MACD强势')
            else:
                macd_score = 20
                result['macd_status'] = 'MACD红柱缩小·注意'
        elif latest_dif > latest_dea:
            macd_score = 15
            result['macd_status'] = 'MACD金叉区'
            result['signals'].append('周线·MACD金叉')
        elif latest_dif < latest_dea and latest_hist < 0:
            macd_score = 5
            result['macd_status'] = 'MACD绿柱区·弱势'
            result['signals'].append('周线·MACD弱势')
        else:
            macd_score = 10
            result['macd_status'] = 'MACD死叉区'
    
    # ── 4. 成交量确认（20分） ──
    vol_score = 0
    if len(vol) >= 8 and len(pct_chg) >= 8:
        up_weeks = pct_chg.head(8) > 0
        up_vol = vol.head(8)[up_weeks].mean() if up_weeks.any() else 0
        down_vol = vol.head(8)[~up_weeks].mean() if (~up_weeks).any() else 0
        
        if up_vol > down_vol * 1.3:
            vol_score = 20
            result['vol_status'] = '上涨放量·健康'
            result['signals'].append('周线·放量上涨')
        elif up_vol > down_vol:
            vol_score = 15
            result['vol_status'] = '上涨温和放量'
        elif up_vol < down_vol * 0.7:
            vol_score = 5
            result['vol_status'] = '上涨缩量·谨慎'
            result['signals'].append('周线·缩量上涨')
        else:
            vol_score = 10
            result['vol_status'] = '量能中性'
    
    total = ma_score + trend_score + macd_score + vol_score
    result['score'] = min(100, max(0, total))
    
    if not result['signals']:
        result['signals'].append('周线: 数据不足或信号不明确')
    
    return result


# ═══════════════════════════════════════════════════
#  六维度评估引擎 v3.0（含热度面 + 概率校准）
# ═══════════════════════════════════════════════════

def calc_hot_theme(industry, stock_df, limit_stocks_by_sector=None,
                   limit_up_count=30, sector_index_df=None,
                   concepts=None):
    """
    热度面评估 — 查股票是否属于当前热门主线/热点板块
    评分因子：主线优先级(30分) + 板块涨停热度(20分) + 板块指数强弱(15分) + 个股引爆(10分)
    """
    score, signals = 50, []

    # 1. 主线匹配度
    theme = THEME_MAP.get(industry, '其他')
    priority = THEME_PRIORITY.get(theme, 6)

    if priority == 1:
        score += 25; signals.append(f"{theme}·全年主线")
    elif priority == 2:
        score += 18; signals.append(f"{theme}·重点方向")
    elif priority == 3:
        score += 10; signals.append(f"{theme}·活跃题材")
    elif priority == 4:
        score += 5; signals.append(f"{theme}·轮动题材")
    else:
        signals.append("非主线板块")

    # 2. 板块涨停热度
    sector_limit_count = 0
    if limit_stocks_by_sector and industry in limit_stocks_by_sector:
        sector_limit_count = limit_stocks_by_sector[industry]

    if sector_limit_count >= 5:
        score += 20; signals.append(f"板块{sector_limit_count}家涨停·🔥极热")
    elif sector_limit_count >= 3:
        score += 12; signals.append(f"板块{sector_limit_count}家涨停·较热")
    elif sector_limit_count >= 1:
        score += 5; signals.append("板块有涨停")

    # 3. 板块指数强弱
    if sector_index_df is not None and not sector_index_df.empty and len(sector_index_df) >= 10:
        s5d = sector_index_df['pct_chg'].head(5).sum()
        s20d = sector_index_df['pct_chg'].head(20).sum()
        if s5d > 5 and s20d > 10:
            score += 15; signals.append("板块趋势强势")
        elif s5d > 3:
            score += 8; signals.append("板块趋势偏强")
        elif s5d < -3:
            score -= 5; signals.append("板块趋势偏弱")
    else:
        signals.append("板块指数数据不足")

    # 4. 个股引爆
    if stock_df is not None and not stock_df.empty:
        pct = stock_df.iloc[0].get('pct_chg', 0)
        if pct >= 9.9:
            score += 10; signals.append("涨停·热点龙头")
        elif pct > 5 and sector_limit_count >= 3:
            score += 6; signals.append("板块联动上涨")

    # 5. 【Phase 3】动态概念匹配 — 查股票概念是否与热门板块重叠
    concept_bonus = 0
    matched_concepts = []
    if concepts and limit_stocks_by_sector:
        # 取当日涨停最多的前5个行业作为热门行业
        hot_industries = sorted(limit_stocks_by_sector.items(), key=lambda x: x[1], reverse=True)[:5]
        hot_industry_names = {ind for ind, cnt in hot_industries if cnt >= 3}
        
        for concept in concepts:
            for hot_ind in hot_industry_names:
                if hot_ind in concept or concept in hot_ind:
                    matched_concepts.append(concept)
                    break
        
        if len(matched_concepts) >= 3:
            concept_bonus = 12
            signals.append(f"概念共振({len(matched_concepts)}个热门概念)")
        elif len(matched_concepts) >= 1:
            concept_bonus = 6
            signals.append(f"概念关联({matched_concepts[0]})")
    
    score += concept_bonus

    # 非热点扣分
    if sector_limit_count == 0 and limit_up_count > 20 and concept_bonus == 0:
        score -= 5; signals.append("非当前热点板块")

    return min(100, max(0, score)), signals, theme, matched_concepts


def calibrate_prob(grade, raw_up_prob):
    """概率校准 — 根据历史回测偏差修正系统预测"""
    # 基于评估中心105条回测记录的偏差数据
    calibration = {
        'S': -10,   # 样本较少，保守估计偏乐观10%
        'A': -10,   # 系统预测63%，真实52.6%，偏乐观10%
        'B': -4,    # 系统预测56%，真实52.0%，偏乐观4%
        'C': +12,   # 系统预测42%，真实54.5%，偏保守12%
        'D': +20,   # 系统预测30%，真实100%，偏保守(小样本)
    }
    adjustment = calibration.get(grade, 0)
    return max(15, min(80, raw_up_prob + adjustment))


# ═══════════════════════════════════════════════════
#  Phase 2: 风控模块 — 可交易性检测 + T+1分层止损
# ═══════════════════════════════════════════════════

def compute_atr(df, period=14):
    """计算ATR用于T+1止损缓冲"""
    if df is None or len(df) < period + 1:
        return 0
    h = df['high'].head(period + 1)
    l = df['low'].head(period + 1)
    c_prev = df['close'].head(period + 1).shift(1).fillna(h.iloc[0])
    tr = pd.concat([h - l, (h - c_prev).abs(), (l - c_prev).abs()], axis=1).max(axis=1)
    return tr.head(period).mean()


def t1_stop_loss(entry_price, holding_days=0, atr=None):
    """
    T+1分层止损 — 适配A股T+1制度
    
    持有天数0(当日买入): -12% (T+1首日不可卖出，预留更大止损空间)
    持有天数1(次日):       ~-10% (含ATR*1.5隔夜跳空缓冲)
    持有天数2+(正常):      -8%  (标准止损)
    """
    if holding_days == 0:
        return entry_price * 0.88, -12
    elif holding_days == 1:
        atr_buffer = (atr or 0) * 1.5
        return max(entry_price * 0.88, entry_price * 0.90 - atr_buffer), -10
    else:
        return entry_price * 0.92, -8


def check_tradeable(code, daily_df=None):
    """
    可交易性检测 — 排除ST/停牌/涨跌停封死
    使用已加载的日线数据，避免重复API请求
    
    返回: {
        'tradeable': bool,
        'reason': str,
        'is_st': bool,
        'is_suspended': bool,
        'is_limit_up_locked': bool,
        'is_limit_down_locked': bool,
    }
    """
    result = {
        'tradeable': True, 'reason': None,
        'is_st': False, 'is_suspended': False,
        'is_limit_up_locked': False, 'is_limit_down_locked': False,
    }
    
    try:
        # 1. ST检测
        basic_df = pro.stock_basic(ts_code=code, fields='ts_code,name,list_status')
        if basic_df is not None and not basic_df.empty:
            name = basic_df.iloc[0].get('name', '')
            if 'ST' in name.upper():
                result['is_st'] = True
                result['tradeable'] = False
                result['reason'] = f"ST股票({name})"
                return result
            if basic_df.iloc[0].get('list_status') == 'D':
                result['tradeable'] = False
                result['reason'] = "已退市"
                return result
        
        # 2. 停牌检测 — 复用已加载的日线数据
        if daily_df is None or daily_df.empty:
            result['is_suspended'] = True
            result['tradeable'] = False
            result['reason'] = "无日线数据(可能停牌)"
            return result
        
        latest = daily_df.iloc[0]
        vol = float(latest.get('vol', 0) or 0)
        if vol == 0:
            result['is_suspended'] = True
            result['tradeable'] = False
            result['reason'] = "当日停牌(零成交)"
            return result
        
        # 3. 涨跌停封死检测（区分板块涨跌幅限制）
        pct = float(latest.get('pct_chg', 0) or 0)
        # 创业板/科创板 20%，北交所 30%，主板 10%
        if code.startswith(('300', '301', '688')):
            limit_pct = 19.9
        elif code.startswith('8'):
            limit_pct = 29.9
        else:
            limit_pct = 9.9
        
        if pct >= limit_pct:
            result['is_limit_up_locked'] = True
            result['reason'] = "涨停封死(无法买入)"
            result['tradeable'] = False
            return result
        if pct <= -limit_pct:
            result['is_limit_down_locked'] = True
            result['reason'] = "跌停封死(无法卖出)"
            result['tradeable'] = True  # 跌停可买
            return result
        
    except Exception as e:
        result['tradeable'] = False
        result['reason'] = f"检测异常: {str(e)[:50]}"
    
    return result


def calc_technical(df):
    """技术面评估 — 趋势、量价、波动、动量"""
    score, signals = 50, []
    
    if df is None or len(df) < 20:
        return 50, ['数据不足']
    
    latest = df.iloc[0]
    close = latest['close']
    pct = latest['pct_chg']
    
    # 均线趋势
    ma5 = df['close'].head(5).mean()
    ma10 = df['close'].head(10).mean()
    ma20 = df['close'].head(20).mean()
    
    if close > ma5 > ma10 > ma20:
        score += 20; signals.append("多头排列")
    elif close > ma5 > ma10:
        score += 12; signals.append("短期多头")
    elif close < ma5 < ma10 < ma20:
        score -= 15; signals.append("空头排列")
    elif close < ma20:
        score -= 10; signals.append("跌破20日线")
    
    # 偏离度
    if ma20 > 0:
        dist = (close - ma20) / ma20 * 100
        if -3 < dist < 3:
            score += 8; signals.append("贴近20日线")
        elif dist > 10:
            score -= 5; signals.append("远离20日线")
    
    # 量价配合
    vol_ma5 = df['vol'].head(5).mean()
    vol_ratio = latest['vol'] / vol_ma5 if vol_ma5 > 0 else 1
    
    if pct > 0 and vol_ratio > 1.3:
        score += 12; signals.append("放量上涨")
    elif pct > 0 and vol_ratio < 0.8:
        score += 3; signals.append("缩量上涨")
    elif pct < 0 and vol_ratio > 1.5:
        score -= 8; signals.append("放量下跌")
    elif pct < 0 and vol_ratio < 0.7:
        score += 5; signals.append("缩量下跌(企稳)")
    
    # 短期动量
    pct5d = df['pct_chg'].head(5).sum()
    if pct5d > 10:
        score += 12; signals.append("5日强势")
    elif pct5d > 5:
        score += 7; signals.append("5日偏强")
    elif pct5d < -10:
        score -= 10; signals.append("5日弱势")
    elif pct5d < -5:
        score -= 5; signals.append("5日偏弱")
    
    # 波动率
    vol20 = df['pct_chg'].head(20).std()
    if 1.5 < vol20 < 3.5:
        score += 5; signals.append("波动适中")
    elif vol20 > 5:
        score -= 5; signals.append("波动剧烈")
    
    return min(100, max(0, score)), signals


def calc_capital(df, mf_df, north_flow=None):
    """资金面评估 — 主力流向、持续性、筹码分布、北向资金"""
    score, signals = 50, []
    
    if mf_df is None or mf_df.empty:
        signals.append("资金数据缺失")
        return 50, signals, None
    
    m = mf_df.iloc[0]
    
    # 主力净流入（特大单+大单）
    buy_elg = m.get('buy_elg_amount', 0) or 0
    buy_lg = m.get('buy_lg_amount', 0) or 0
    sell_elg = m.get('sell_elg_amount', 0) or 0
    sell_lg = m.get('sell_lg_amount', 0) or 0
    
    main_net = (buy_elg + buy_lg) - (sell_elg + sell_lg)
    total = buy_elg + buy_lg + sell_elg + sell_lg
    
    if total > 0:
        ratio = main_net / total
        if ratio > 0.15:
            score += 20; signals.append("主力大幅流入")
        elif ratio > 0.05:
            score += 12; signals.append("主力净流入")
        elif ratio < -0.15:
            score -= 15; signals.append("主力大幅流出")
        elif ratio < -0.05:
            score -= 8; signals.append("主力净流出")
    
    # 5日资金持续性
    if len(mf_df) >= 5:
        mf_df = mf_df.copy()
        mf_df['main_net'] = (
            (mf_df['buy_elg_amount'].fillna(0) + mf_df['buy_lg_amount'].fillna(0)) -
            (mf_df['sell_elg_amount'].fillna(0) + mf_df['sell_lg_amount'].fillna(0))
        )
        net5 = mf_df['main_net'].head(5).sum()
        if net5 > 0:
            score += 10; signals.append("5日资金持续流入")
        elif net5 < 0:
            score -= 8; signals.append("5日资金持续流出")
    
    # 筹码分布（主力买、散户卖 = 筹码集中）
    buy_md = m.get('buy_md_amount', 0) or 0
    buy_sm = m.get('buy_sm_amount', 0) or 0
    sell_md = m.get('sell_md_amount', 0) or 0
    sell_sm = m.get('sell_sm_amount', 0) or 0
    retail_net = (buy_md + buy_sm) - (sell_md + sell_sm)
    
    if main_net > 0 and retail_net < 0:
        score += 10; signals.append("筹码集中")
    elif main_net < 0 and retail_net > 0:
        score -= 10; signals.append("筹码分散")
    
    # 【Phase 3】北向资金因子
    north_note = None
    if north_flow is not None:
        direction = north_flow.get('direction', 'neutral')
        strength = north_flow.get('strength', 0)
        recent_flow = north_flow.get('recent_flow', 0)
        
        if direction == 'inflow':
            if strength >= 5:
                score += 8; signals.append("北向持续流入")
                north_note = f"北向5日净流入{recent_flow:.0f}亿"
            elif strength >= 3:
                score += 5; signals.append("北向偏多")
                north_note = f"北向{strength}日净流入"
            else:
                score += 2; signals.append("北向小幅流入")
        elif direction == 'outflow':
            if strength >= 5:
                score -= 8; signals.append("北向持续流出")
                north_note = f"北向5日净流出{abs(recent_flow):.0f}亿"
            elif strength >= 3:
                score -= 5; signals.append("北向偏空")
            else:
                score -= 2; signals.append("北向小幅流出")
    
    return min(100, max(0, score)), signals, north_note


def calc_sentiment(df, limit_up_count=30):
    """情绪面评估 — 市场情绪、个股涨跌、换手率"""
    score, signals = 50, []
    
    if df is None or df.empty:
        return 50, ['数据不足']
    
    pct = df.iloc[0]['pct_chg']
    
    # 市场情绪
    if limit_up_count > 80:
        score += 12; signals.append("市场情绪高涨")
    elif limit_up_count > 40:
        score += 6; signals.append("市场偏多")
    elif limit_up_count < 15:
        score -= 5; signals.append("市场偏冷")
    
    # 个股涨跌幅
    if pct >= 9.9:
        score += 15; signals.append("涨停")
    elif pct > 5:
        score += 10; signals.append("大涨")
    elif pct > 2:
        score += 5; signals.append("上涨")
    elif pct < -5:
        score -= 12; signals.append("大跌")
    elif pct < -2:
        score -= 5; signals.append("下跌")
    
    # 连涨/连跌
    pct_list = df['pct_chg'].head(5).tolist()
    up = sum(1 for p in pct_list if p > 0)
    dn = sum(1 for p in pct_list if p < 0)
    if up >= 4:
        score += 10; signals.append("连涨")
    elif up >= 3:
        score += 6; signals.append("偏强")
    elif dn >= 4:
        score -= 10; signals.append("连跌")
    elif dn >= 3:
        score -= 6; signals.append("偏弱")
    
    # 换手率
    turnover = df.iloc[0].get('turnover_rate', 0)
    if turnover and not np.isnan(turnover):
        if 3 <= turnover <= 10:
            score += 8; signals.append(f"换手{turnover:.1f}%适中")
        elif 10 < turnover <= 20:
            score += 5; signals.append(f"换手{turnover:.1f}%活跃")
        elif turnover > 20:
            score -= 3; signals.append(f"换手{turnover:.1f}%过高")
    
    return min(100, max(0, score)), signals


def calc_fundamental(df, holder_data=None):
    """基本面评估 — PE/PB/市值/股价/股东户数集中度"""
    score, signals = 50, []
    
    if df is None or df.empty:
        return 50, ['数据不足']
    
    latest = df.iloc[0]
    pe = latest.get('pe', None)
    pb = latest.get('pb', None)
    
    if pe and not np.isnan(pe) and pe > 0:
        if 10 <= pe <= 30:
            score += 15; signals.append(f"PE={pe:.1f}合理")
        elif 5 <= pe < 10:
            score += 12; signals.append(f"PE={pe:.1f}偏低")
        elif 30 < pe <= 60:
            score += 3; signals.append(f"PE={pe:.1f}偏高")
        elif pe > 60:
            score -= 5; signals.append(f"PE={pe:.1f}过高")
        elif pe < 0:
            score -= 10; signals.append("PE为负")
    else:
        signals.append("PE缺失")
    
    if pb and not np.isnan(pb) and pb > 0:
        if 0.5 <= pb <= 3:
            score += 8; signals.append(f"PB={pb:.1f}合理")
        elif pb < 0.5:
            score += 5; signals.append(f"PB={pb:.1f}破净")
        elif pb > 5:
            score -= 5; signals.append(f"PB={pb:.1f}偏高")
    
    total_mv = latest.get('total_mv', 0)
    if total_mv and not np.isnan(total_mv):
        if total_mv >= 500:
            score += 8; signals.append("大盘股")
        elif total_mv >= 100:
            score += 5; signals.append("中盘股")
        elif total_mv >= 30:
            score += 3; signals.append("中小盘")
        else:
            score -= 3; signals.append("小盘股")
    
    close = latest['close']
    if 5 <= close <= 30:
        score += 8; signals.append("价格适中")
    elif 3 <= close < 5:
        score += 3; signals.append("低价股")
    elif close > 50:
        score -= 3; signals.append("高价股")
    elif close < 3:
        score -= 5; signals.append("极低价股")
    
    # 【Phase 3】股东户数集中度因子
    holder_note = None
    if holder_data is not None:
        trend = holder_data.get('trend', 'stable')
        change_pct = holder_data.get('change_pct', 0)
        holder_num = holder_data.get('latest_holder_num', 0)
        
        if trend == 'concentrating':
            if change_pct < -15:
                score += 10; signals.append(f"筹码大幅集中({change_pct:+.1f}%)")
                holder_note = f"股东户数{holder_num}户↓{abs(change_pct):.1f}%"
            else:
                score += 6; signals.append(f"筹码集中({change_pct:+.1f}%)")
                holder_note = f"股东户数{holder_num}户↓{abs(change_pct):.1f}%"
        elif trend == 'dispersing':
            if change_pct > 15:
                score -= 10; signals.append(f"筹码大幅分散({change_pct:+.1f}%)")
                holder_note = f"股东户数{holder_num}户↑{change_pct:.1f}%"
            else:
                score -= 5; signals.append(f"筹码分散({change_pct:+.1f}%)")
                holder_note = f"股东户数{holder_num}户↑{change_pct:.1f}%"
        else:
            if holder_num > 0:
                holder_note = f"股东户数{holder_num}户(稳定)"
    
    return min(100, max(0, score)), signals, holder_note


def calc_sector(stock_df, sector_df=None, market_df=None, hot_sectors=None, industry=""):
    """
    板块面评估 v2.0 — 真正对比行业指数和大盘
    
    三个对比维度：
    1. 股票 vs 行业指数 相对强弱 (权重 40%)
    2. 股票 vs 大盘 相对强弱 (权重 30%)
    3. 股票自身趋势稳定性 (权重 30%)
    4. 【新增】板块共振 — 是否属于热门板块
    """
    score, signals = 50, []
    
    if stock_df is None or len(stock_df) < 10:
        return 50, ['数据不足'], None
    
    stock_close = stock_df.iloc[0]['close']
    
    # ── 1. vs 行业指数 ──
    sector_available = sector_df is not None and not sector_df.empty and len(sector_df) >= 10
    
    if sector_available:
        # 股票5日涨幅 vs 行业指数5日涨幅
        stock_5d = stock_df['pct_chg'].head(5).sum()
        sector_5d = sector_df['pct_chg'].head(5).sum() if 'pct_chg' in sector_df.columns else 0
        
        # 股票20日涨幅 vs 行业指数20日涨幅
        stock_20d_pct = (stock_close / stock_df['close'].head(20).iloc[-1] - 1) * 100 if len(stock_df) >= 20 else 0
        
        if len(sector_df) >= 20:
            sector_20d_pct = (sector_df.iloc[0]['close'] / sector_df['close'].head(20).iloc[-1] - 1) * 100
        else:
            sector_20d_pct = 0
        
        # 相对强度 = 股票涨幅 - 行业涨幅
        rel_5d = stock_5d - sector_5d
        rel_20d = stock_20d_pct - sector_20d_pct
        
        if rel_5d > 5 and rel_20d > 5:
            score += 15; signals.append("显著强于行业")
        elif rel_5d > 2:
            score += 8; signals.append("强于行业")
        elif rel_5d < -5 and rel_20d < -5:
            score -= 12; signals.append("显著弱于行业")
        elif rel_5d < -2:
            score -= 6; signals.append("弱于行业")
        
        # 行业指数自身的趋势（水涨船高）
        if sector_5d > 5:
            score += 4; signals.append("行业上行")
        elif sector_5d < -5:
            score -= 4; signals.append("行业下行")
    else:
        signals.append("行业数据缺失")
    
    # ── 2. vs 大盘（上证综指）──
    market_available = market_df is not None and not market_df.empty and len(market_df) >= 10
    
    if market_available:
        market_5d = market_df['pct_chg'].head(5).sum() if 'pct_chg' in market_df.columns else 0
        stock_5d = stock_df['pct_chg'].head(5).sum()
        
        rel_market = stock_5d - market_5d
        if rel_market > 5:
            score += 8; signals.append("显著强于大盘")
        elif rel_market > 2:
            score += 4; signals.append("强于大盘")
        elif rel_market < -5:
            score -= 6; signals.append("显著弱于大盘")
        elif rel_market < -2:
            score -= 3; signals.append("弱于大盘")
        
        if market_5d > 3:
            score += 3; signals.append("大盘上行")
        elif market_5d < -3:
            score -= 3; signals.append("大盘下行")
    else:
        signals.append("大盘数据缺失")
    
    # ── 3. 股票自身趋势稳定性 ──
    vol20 = stock_df['pct_chg'].head(20).std()
    if vol20 < 2.0:
        score += 8; signals.append("走势稳定")
    elif vol20 < 3.0:
        score += 4; signals.append("波动正常")
    elif vol20 > 5.0:
        score -= 8; signals.append("波动剧烈")
    
    # ── 4. 【新增】板块共振评估 ──
    resonance_level = None
    if hot_sectors:
        resonance_level = calc_sector_resonance(industry, hot_sectors)
        if resonance_level == 'hot':
            score += 15; signals.append("🔥热门板块共振")
        elif resonance_level == 'rising':
            score += 8; signals.append("📈强势板块")
        # 不加分不减分的情况（neutral）不添加信号
    
    # 数据源标记
    if not sector_available and not market_available:
        signals.append("⚠板块面降级(无指数)")
    
    return min(100, max(0, score)), signals, resonance_level


def calc_sector_resonance(industry, hot_sectors):
    """
    板块共振评估 — 判断股票是否属于热门板块
    
    参数:
        industry: 股票所属行业名
        hot_sectors: 热门板块列表 [{'name': '板块名', 'level': 'hot/rising'}, ...]
    
    返回:
        'hot': 热门板块共振
        'rising': 强势板块
        None: 非热门板块
    """
    if not industry or hot_sectors is None or not hot_sectors:
        return None
    
    # 检查是否匹配热门板块
    for hs in hot_sectors:
        hs_name = hs.get('name', '')
        hs_level = hs.get('level', '')
        
        # 模糊匹配
        if hs_name and industry:
            if hs_name in industry or industry in hs_name:
                if hs_level == 'hot':
                    return 'hot'  # 热门板块共振
                elif hs_level == 'rising':
                    return 'rising'  # 强势板块
    
    return None


def get_hot_sectors(end_date=None, top_n=5):
    """
    获取热门板块 — 参考附件源码的板块筛选逻辑
    
    热门板块判定条件（简化版）：
    1. 板块内涨停家数 ≥ 3
    2. 板块温和放量（5日均量1.05~1.5倍）
    
    返回:
        list: [{'name': '板块名', 'level': 'hot/rising'}, ...]
    """
    if end_date is None:
        end_date = datetime.now().strftime('%Y%m%d')
    
    hot_sectors = []
    
    try:
        # 获取当日涨停股票
        limit_df = pro.limit_list_d(date=end_date)
        if limit_df is None or limit_df.empty:
            return hot_sectors
        
        limit_up_stocks = set(limit_df[limit_df['limit'] == 'U']['ts_code'].tolist())
        
        # 获取所有股票的行业信息
        basic_df = pro.stock_basic(exchange='', list_status='L', 
                                   fields='ts_code,industry')
        if basic_df is None or basic_df.empty:
            return hot_sectors
        
        # 统计每个行业的涨停家数
        industry_limit_count = defaultdict(int)
        industry_stocks = defaultdict(list)
        
        for _, row in basic_df.iterrows():
            ts_code = row['ts_code']
            industry = row.get('industry', '未知')
            if pd.notna(industry) and industry:
                industry_stocks[industry].append(ts_code)
                if ts_code in limit_up_stocks:
                    industry_limit_count[industry] += 1
        
        # 筛选涨停家数 >= 3 的板块
        for industry, limit_cnt in industry_limit_count.items():
            if limit_cnt >= 3:
                level = 'hot' if limit_cnt >= 5 else 'rising'
                hot_sectors.append({
                    'name': industry,
                    'level': level,
                    'limit_count': limit_cnt,
                    'total_stocks': len(industry_stocks.get(industry, []))
                })
        
        # 按涨停家数排序
        hot_sectors.sort(key=lambda x: x['limit_count'], reverse=True)
        
        # 只返回top_n
        return hot_sectors[:top_n]
        
    except Exception as e:
        print(f"    ⚠ 获取热门板块失败: {e}")
        return hot_sectors


def evaluate_stock(code, stock_data, name="", industry="",
                   sector_df=None, market_df=None,
                   limit_up_count=30,
                   weights=None,
                   hot_sectors=None,
                   limit_stocks_by_sector=None,
                   concepts=None,           # Phase 3: 动态概念
                   north_flow=None,         # Phase 3: 北向资金
                   holder_data=None,        # Phase 3: 股东户数
                   zscore_df=None,          # ZSCORE板块比价数据
                   weekly_df=None):          # 周线数据（中长期趋势）
    """
    对单只股票执行完整十二维度评估（v5.0含ZSCORE比价+反身性四象限+周线分析+筹码面+主力行为+政策催化+国家队面）
    """
    if weights is None:
        weights = {'tech': 0.25, 'cap': 0.20, 'sent': 0.10, 'fund': 0.10, 'sect': 0.08, 'hot': 0.05, 'zscore': 0.05, 'reflexivity': 0.02, 'holder': 0.05, 'mainforce': 0.05, 'policy': 0.30, 'national': 0.10}
    
    df = stock_data.get('daily', pd.DataFrame())
    mf = stock_data.get('moneyflow', pd.DataFrame())
    
    if df is None or df.empty:
        return {
            'code': code, 'name': name, 'error': '无日线数据',
            'total': 0, 'grade': 'N/A'
        }
    
    latest = df.iloc[0]
    close = float(latest['close'])
    pct = float(latest['pct_chg'])
    
    # 执行六维度
    tech_sc, tech_sig = calc_technical(df)
    cap_sc, cap_sig, north_note = calc_capital(df, mf, north_flow)
    sent_sc, sent_sig = calc_sentiment(df, limit_up_count)
    fund_sc, fund_sig, holder_note = calc_fundamental(df, holder_data)
    sect_sc, sect_sig, resonance_level = calc_sector(df, sector_df, market_df, hot_sectors, industry)
    hot_sc, hot_sig, hot_theme, matched_concepts = calc_hot_theme(
        industry, df, limit_stocks_by_sector, limit_up_count, sector_df, concepts)
    
    # ZSCORE板块比价（八维度）
    zscore_sc = 50
    zscore_sig = ['ZSCORE数据未加载']
    zscore_resonance = {}
    zscore_info = {}
    if zscore_df is not None and not zscore_df.empty:
        zscore_res = calc_zscore_resonance(industry, zscore_df, df, sector_df, hot_theme)
        zscore_sc = zscore_res['score']
        zscore_sig = zscore_res['signals']
        zscore_resonance = {
            'count': zscore_res['resonance_count'],
            'dimensions': zscore_res['dimensions'],
        }
        zscore_info = zscore_res['zscore_info']
    else:
        zscore_sig = ['ZSCORE数据未加载']
    
    # 反身性分析（第八维度）— v5.0 四象限模型
    ref_result = calc_reflexivity(df, mf, sector_df, hot_theme, holder_data)
    ref_sc = ref_result['score']
    ref_stage = ref_result['stage']
    ref_stage_name = ref_result['stage_name']
    ref_quadrant = ref_result['quadrant']
    ref_sbi = ref_result['sbi']
    ref_price_trend = ref_result['price_trend']
    ref_strength = ref_result['reflexivity_strength']
    ref_stage_signals = ref_result['stage_signals']
    ref_operation = ref_result['operation']
    ref_bubble_signals = ref_result['bubble_signals']
    ref_sbi_factors = ref_result['sbi_factors']
    ref_all_signals = ref_result['all_signals']
    
    # 周线分析（中长期趋势辅助判断，不直接参与日线综合评分）
    weekly_res = calc_weekly(weekly_df)
    weekly_sc = weekly_res['score']
    weekly_trend = weekly_res['trend']
    weekly_signals = weekly_res['signals']
    weekly_ma = weekly_res['ma_status']
    weekly_macd = weekly_res['macd_status']
    weekly_vol = weekly_res['vol_status']
    
    # 加权综合（十维度 v5.0）
    # 筹码面评分（第九维度）
    holder_dim = calc_holder_dimension(holder_data)
    holder_sc = holder_dim['score']
    
    # 主力行为面评分（第十维度）
    mf_signals = calc_main_force_signals(df, weekly_df, sector_df, market_df)
    mf_sc = 50 + mf_signals['bonus'] * 6.25  # bonus -6~+8 映射到 50-100
    mf_sc = max(0, min(100, mf_sc))
    
    # 【v5.0】政策催化维度
    policy_sc, policy_sig = calc_policy_score(load_policy_sentry())
    
    # 【v5.0】国家队面维度
    nt_data = load_national_team_data()
    nt_sc, nt_sig = calc_national_team_score(nt_data)
    
    total = (tech_sc * weights.get('tech', 0) +
             cap_sc * weights.get('cap', 0) +
             sent_sc * weights.get('sent', 0) +
             fund_sc * weights.get('fund', 0) +
             sect_sc * weights.get('sect', 0) +
             hot_sc * weights.get('hot', 0) +
             zscore_sc * weights.get('zscore', 0) +
             ref_sc * weights.get('reflexivity', 0) +
             holder_sc * weights.get('holder', 0) +
             mf_sc * weights.get('mainforce', 0) +
             policy_sc * weights.get('policy', 0) +
             nt_sc * weights.get('national', 0))
    
    # 主力行为面评分已融入权重计算（不重复附加）
    
    # 等级
    if total >= 85:     grade = 'S'
    elif total >= 70:   grade = 'A'
    elif total >= 55:   grade = 'B'
    elif total >= 40:   grade = 'C'
    else:               grade = 'D'
    
    # 预测概率（原始）
    base_up = 45
    base_up += (tech_sc - 50) * 0.20
    base_up += (cap_sc - 50) * 0.20
    base_up += (sent_sc - 50) * 0.12
    base_up += (fund_sc - 50) * 0.08
    base_up += (sect_sc - 50) * 0.10
    base_up += (zscore_sc - 50) * 0.15
    base_up += (ref_sc - 50) * 0.10
    # 【v5.0】政策催化和国家队面影响概率
    base_up += (policy_sc - 50) * 0.18
    base_up += (nt_sc - 50) * 0.10
    if pct > 5:
        base_up -= 5
    elif pct >= 9.9:
        base_up -= 10
    elif pct < -5:
        base_up += 3
    
    raw_up_prob = min(80, max(15, int(base_up)))
    down_prob = min(60, max(10, 100 - raw_up_prob - 15))
    neutral_prob = 100 - raw_up_prob - down_prob
    
    # 概率校准
    up_prob = calibrate_prob(grade, raw_up_prob)
    
    # 置信度
    all_scores = [tech_sc, cap_sc, sent_sc, fund_sc, sect_sc, hot_sc, zscore_sc]
    score_range = max(all_scores) - min(all_scores)
    confidence = "高" if score_range < 30 else "中等"
    
    # 预期收益
    if up_prob >= 60:
        expected = f"+{up_prob / 10:.0f}% ~ +{up_prob / 6:.0f}%"
    elif up_prob >= 50:
        expected = "+1% ~ +5%"
    elif down_prob >= 45:
        expected = f"-{down_prob / 10:.0f}% ~ -{down_prob / 6:.0f}%"
    else:
        expected = "-2% ~ +3%"
    
    # 趋势
    if up_prob >= 60:
        trend = "📈 看涨"
    elif down_prob >= 45:
        trend = "📉 看跌"
    else:
        trend = "➡️ 震荡"
    
    # 仓位
    if grade in ['S', 'A']:
        pos_pct = 0.15 if grade == 'A' else 0.20
        holding = "3-5日"
    elif grade == 'B':
        pos_pct = 0.10; holding = "3-5日"
    else:
        pos_pct = 0.05; holding = "观望"
    
    # 止损/目标 — T+1分层止损
    atr = compute_atr(df)
    # 默认持有天数0（当日买入），止损按T+1分层
    stop_loss_day0, stop_pct_day0 = t1_stop_loss(close, 0, atr)
    stop_loss_day1, stop_pct_day1 = t1_stop_loss(close, 1, atr)
    stop_loss_normal, stop_pct_normal = t1_stop_loss(close, 2, atr)
    
    target = close * (1 + max(0.03, up_prob / 200))
    target_pct = (target / close - 1) * 100
    rr = abs(target_pct / stop_pct_day0) if stop_pct_day0 != 0 else 0
    
    # 风险
    risks = []
    if grade in ['C', 'D']:
        risks.append("🟠 综合评分偏低")
    if pct < -5:
        risks.append("🔴 当日大跌")
    if pct >= 9.9:
        risks.append("🟡 涨停封死(无法买入)")
    if down_prob >= 45:
        risks.append("🟠 下跌概率偏高")
    if tech_sc < 40:
        risks.append("🟡 技术面弱势")
    if cap_sc < 40:
        risks.append("🟡 资金面弱势")
    if policy_sc < 30:
        risks.append("🔴 政策催化不足")
    if nt_sc < 30:
        risks.append("🔴 国家队撤离")
    if zscore_info.get('signal') == 'overheat':
        risks.append("🟡 板块ZSCORE过热")
    if not risks:
        risks.append("🟢 暂无重大风险")
    
    return {
        'code': code,
        'name': name,
        'industry': industry,
        'close': close,
        'pct_chg': pct,
        'total': round(total, 1),
        'grade': grade,
        'tech': round(tech_sc, 1),
        'cap': round(cap_sc, 1),
        'sent': round(sent_sc, 1),
        'fund': round(fund_sc, 1),
        'sect': round(sect_sc, 1),
        'hot': round(hot_sc, 1),
        'zscore': round(zscore_sc, 1),
        'tech_sig': tech_sig,
        'cap_sig': cap_sig,
        'sent_sig': sent_sig,
        'fund_sig': fund_sig,
        'sect_sig': sect_sig,
        'hot_sig': hot_sig,
        'zscore_sig': zscore_sig,
        'zscore_resonance': zscore_resonance,
        'zscore_info': zscore_info,
        'reflexivity': round(ref_sc, 1),
        'reflexivity_stage': ref_stage,
        'reflexivity_stage_name': ref_stage_name,
        'reflexivity_quadrant': ref_quadrant,
        'reflexivity_sbi': ref_sbi,
        'reflexivity_price_trend': ref_price_trend,
        'reflexivity_strength': ref_strength,
        'reflexivity_signals': ref_stage_signals,
        'reflexivity_operation': ref_operation,
        'reflexivity_bubble_signals': ref_bubble_signals,
        'reflexivity_sbi_factors': ref_sbi_factors,
        'reflexivity_all_signals': ref_all_signals,
        
        # 筹码面（第九维度）— 散户数量变化
        'holder_dimension': round(holder_sc, 1),
        'holder_trend': holder_dim['trend'],
        'holder_change_pct': holder_dim['change_pct'],
        'holder_detail': holder_dim['details'],
        
        # 主力行为面（第十维度）— 主进信号
        'mainforce_bonus': mf_signals['bonus'],
        'mainforce_daily_grade': mf_signals['daily']['grade'],
        'mainforce_weekly_grade': mf_signals['weekly']['grade'],
        'mainforce_daily_signals': mf_signals['daily']['aux_signals'],
        'mainforce_exit_signals': mf_signals['daily']['exit_signals'],
        'mainforce_details': mf_signals['details'],
        'weekly': round(weekly_sc, 1),
        'weekly_trend': weekly_trend,
        'weekly_signals': weekly_signals,
        'weekly_ma': weekly_ma,
        'weekly_macd': weekly_macd,
        'weekly_vol': weekly_vol,
        'hot_theme': hot_theme,
        'up_prob': up_prob,
        'raw_up_prob': raw_up_prob,  # 校准前原始概率
        'down_prob': down_prob,
        'neutral_prob': neutral_prob,
        'expected': expected,
        'trend': trend,
        'confidence': confidence,
        'pos_pct': pos_pct,
        'stop_loss_day0': round(stop_loss_day0, 2),
        'stop_pct_day0': stop_pct_day0,
        'stop_loss_day1': round(stop_loss_day1, 2),
        'stop_pct_day1': stop_pct_day1,
        'stop_loss': round(stop_loss_normal, 2),
        'stop_pct': stop_pct_normal,
        'atr': round(atr, 2),
        'target': round(target, 2),
        'target_pct': round(target_pct, 0),
        'rr': round(rr, 1),
        'holding': holding,
        'risks': risks,
        'resonance': resonance_level,
        'tradeable': True,  # 将在 evaluate_batch 中补充
        # Phase 3 新增
        'north_note': north_note,
        'holder_note': holder_note,
        'concepts': concepts or [],
        'matched_concepts': matched_concepts,
        # 【v5.0】新增维度
        'policy': round(policy_sc, 1),
        'policy_sig': policy_sig,
        'policy_sources': load_policy_sentry().get('policy_sources', {}),
        'national': round(nt_sc, 1),
        'national_sig': nt_sig,
        'national_team_hits': nt_data.get('action_counts', {}),
    }


def evaluate_batch(codes, data_loader=None, lookback_days=90,
                   end_date=None, verbose=True,
                   policy_data=None, nt_data=None):
    """
    批量评估多只股票
    
    【v5.0 新增】:
    - policy_data: 政策催化数据（dict）
    - nt_data: 国家队面数据（dict）
    """
    if data_loader is None:
        data_loader = DataLoader()
    
    if verbose:
        print(f"评估日期: {end_date or datetime.now().strftime('%Y%m%d')}")
        print(f"正在加载 {len(codes)} 只股票数据...")
    
    all_data = data_loader.load_all(codes, lookback_days, end_date, verbose=verbose)
    market_info = all_data.pop('_market', {})
    sector_data = all_data.pop('_sectors', {})
    
    limit_up_count = market_info.get('limit_up_count', 30)
    
    # 【新增】获取热门板块
    if verbose:
        print("正在分析热门板块...")
    hot_sectors = get_hot_sectors(end_date, top_n=5)
    if hot_sectors:
        if verbose:
            print(f"  🔥 热门板块({len(hot_sectors)}个):")
            for hs in hot_sectors:
                icon = "🔥" if hs['level'] == 'hot' else "📈"
                print(f"    {icon} {hs['name']} (涨停{hs['limit_count']}家)")
    else:
        if verbose:
            print("  ⚠ 未检测到热门板块")
    
    # 大盘数据（上证综指）
    market_df = sector_data.get('上证综指', None)
    if market_df is None:
        try:
            market_df = data_loader.load_sector_index('综合', lookback_days, end_date)
        except Exception:
            market_df = None
    
    # 【新增】统计各行业涨停家数（用于热度面评估）
    limit_stocks_by_sector = defaultdict(int)
    try:
        limit_df = pro.limit_list_d(date=end_date)
        if limit_df is not None and not limit_df.empty:
            limit_up_stocks = set(limit_df[limit_df['limit'] == 'U']['ts_code'].tolist())
            basic_df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,industry')
            if basic_df is not None and not basic_df.empty:
                for _, row in basic_df.iterrows():
                    if row['ts_code'] in limit_up_stocks and pd.notna(row.get('industry')):
                        limit_stocks_by_sector[row['industry']] += 1
    except Exception:
        pass
    
    # ═══ Phase 3: 加载付费API数据 ═══
    # 概念板块映射
    concept_map = load_concept_mapping(codes, verbose=verbose)
    
    # 北向资金流向
    if verbose:
        print("正在加载北向资金数据...")
    north_flow = load_north_flow(lookback_days=20, end_date=end_date)
    if north_flow['direction'] != 'neutral':
        direction_cn = {'inflow': '净流入', 'outflow': '净流出', 'neutral': '持平'}
        if verbose:
            print(f"  ✓ 北向资金: {direction_cn.get(north_flow['direction'], '')} "
                  f"{north_flow['recent_flow']:+.0f}亿 | 连续{north_flow['strength']}日")
    
    # 股东户数
    holder_map = load_holder_data(codes, end_date, verbose=verbose)
    
    # ═══ ZSCORE板块比价数据加载 ═══
    zscore_df, zscore_date, zscore_is_fresh = load_zscore_data(verbose=verbose)
    if not zscore_is_fresh and zscore_df is not None:
        if verbose:
            print(f"  ⚠ ZSCORE数据滞后超过2天，将回退为六维度评估")
        zscore_df = None  # 滞后>2天回退六维
    elif zscore_df is not None and zscore_is_fresh:
        if verbose:
            print(f"  ✓ ZSCORE数据新鲜，启用八维度评估")
    
    if verbose:
        print(f"\n开始{'七' if zscore_df is not None else '六'}维度评估...")
    
    results = []
    for code in codes:
        sd = all_data.get(code, {})
        if not sd:
            continue
        
        industry = sd.get('industry', '未知')
        sector_df = sector_data.get(industry, None)
        
        # 【Phase 2】可交易性检测
        daily_df = sd.get('daily', pd.DataFrame())
        tradable = check_tradeable(code, daily_df)
        if not tradable['tradeable']:
            if verbose:
                print(f"  ✗ {sd.get('name', code)} 不可交易: {tradable['reason']}")
            # 仍然加入结果但标记不可交易
            r = {
                'code': code,
                'name': sd.get('name', code),
                'industry': industry,
                'error': tradable['reason'],
                'tradeable': False,
                'total': 0, 'grade': 'N/A',
            }
            results.append(r)
            continue
        
        r = evaluate_stock(
            code=code,
            stock_data=sd,
            name=sd.get('name', code),
            industry=industry,
            sector_df=sector_df,
            market_df=market_df,
            limit_up_count=limit_up_count,
            hot_sectors=hot_sectors,
            limit_stocks_by_sector=limit_stocks_by_sector,
            concepts=concept_map.get(code, []),       # Phase 3
            north_flow=north_flow,                     # Phase 3
            holder_data=holder_map.get(code),          # Phase 3
            zscore_df=zscore_df,                       # ZSCORE板块比价
            weekly_df=sd.get('weekly', None),            # 周线数据
        )
        
        if 'error' not in r:
            r['tradeable'] = True
            results.append(r)
            if verbose:
                dims = f"技{r['tech']:.0f} 资{r['cap']:.0f} 情{r['sent']:.0f} 基{r['fund']:.0f} 板{r['sect']:.0f} 热{r['hot']:.0f} Z{r.get('zscore', 50):.0f} 反{r.get('reflexivity', 50):.0f} 周{r.get('weekly', 50):.0f}"
                resonance_icon = ""
                if r.get('resonance') == 'hot':
                    resonance_icon = " 🔥共振"
                elif r.get('resonance') == 'rising':
                    resonance_icon = " 📈强势"
                # ZSCORE共振标注
                zr_count = r.get('zscore_resonance', {}).get('count', 0)
                if zr_count >= 4:
                    resonance_icon += " ★Z四维共振"
                elif zr_count >= 3:
                    resonance_icon += " ☆Z三维共振"
                calib = f" (校准{r['up_prob']}%)" if r.get('raw_up_prob', r['up_prob']) != r['up_prob'] else ""
                print(f"  ✓ {r['name']} 综合{r['total']:.0f}分 {r['grade']}级 [{dims}] 上涨{r['up_prob']}%{calib}{resonance_icon}")
    
    results.sort(key=lambda x: x['total'], reverse=True)
    meta = {'market': market_info, 'sectors': sector_data, 'hot_sectors': hot_sectors,
            'north_flow': north_flow, 'zscore_date': zscore_date, 'zscore_df': zscore_df}
    return results, meta


# ═══════════════════════════════════════════════════
#  粗评报告生成器
# ═══════════════════════════════════════════════════

def generate_report(stock_list, report_name=None, save_dir=None):
    """
    生成粗评报告 (Markdown格式)
    
    参数:
        stock_list: 股票代码列表，如 ['601728.SH', '002268.SZ']
        report_name: 报告名称，默认自动生成（含时间戳，不覆盖旧报告）
        save_dir: 保存目录，默认当前目录
    
    注意:
        文件名包含时间戳（精确到分钟），每次生成独立存档
        例如：粗评报告_7只_20260530_1653.md
    """
    if report_name is None:
        # 文件名含时间戳，确保每次生成独立存档
        report_name = f"粗评报告_{len(stock_list)}只_{datetime.now().strftime('%Y%m%d_%H%M')}"
    
    if save_dir is None:
        # 自动分类到 reports/粗评/
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        save_dir = os.path.join(base_dir, 'reports', '粗评')
        os.makedirs(save_dir, exist_ok=True)
    
    print(f"\n{'='*60}")
    print(f"生成粗评报告: {report_name}")
    print(f"{'='*60}\n")
    
    # 执行评估
    results, meta = evaluate_batch(stock_list, lookback_days=90, verbose=True)
    
    if not results:
        print("✗ 无有效评估结果")
        return None
    
    # 分离可交易和不可交易
    tradeable_results = [r for r in results if r.get('tradeable', True) and 'error' not in r]
    non_tradeable_results = [r for r in results if not r.get('tradeable', True) or 'error' in r]
    
    if not tradeable_results:
        print("✗ 无有效评估结果（全部不可交易）")
        return None
    
    # 生成Markdown报告
    date_str = datetime.now().strftime('%Y年%m月%d日')
    
    # 不可交易警告
    non_trade_section = ""
    if non_tradeable_results:
        non_trade_section = "## ⛔ 不可交易标的\n\n"
        for nt in non_tradeable_results:
            non_trade_section += f"- **{nt.get('name', nt['code'])}** ({nt['code']}): {nt.get('error', '未知原因')}\n"
        non_trade_section += "\n---\n\n"
    
    # 【v5.0】加载政策催化和国家队面数据
    policy_data = load_policy_sentry()
    nt_data = load_national_team_data()
    
    # 政策催化概况
    policy_collect_time = policy_data.get('collect_time', '未知')
    policy_freshness = "✅ 新鲜" if policy_data.get('has_fresh_data') else "⚠️ 滞后(>24h)"
    policy_sources = policy_data.get('policy_sources', {})
    policy_coverage = f"{sum(1 for v in policy_sources.values() if v > 0)}/5 部委采集成功"
    cninfo_hits = policy_data.get('cninfo_hits', 0)
    
    # 国家队资本动向（v5.0）
    action_counts = nt_data.get('action_counts', {})
    total_hits = nt_data.get('total_hits', 0)
    
    # 按动作类型展示
    减持_count = action_counts.get('减持', 0)
    增持_count = action_counts.get('增持', 0)
    权益变动_count = action_counts.get('权益变动', 0)
    其他_count = action_counts.get('其他', 0)
    
    if total_hits > 0:
        dagang_action = f"减持{减持_count}次/增持{增持_count}次/权益变动{权益变动_count}次"
        huijin_action = "—"
        chengtong_action = "—"
        shebao_action = "—"
    else:
        dagang_action = "无数据"
        huijin_action = "—"
        chengtong_action = "—"
        shebao_action = "—"
    
    # 国家队详细命中表
    all_hits = nt_data.get('hits', [])
    national_team_hits_table = ""
    if all_hits:
        for hit in all_hits[:5]:  # 只显示前5条
            national_team_hits_table += f"| {hit.get('code', '?')} | {hit.get('name', '?')} | {hit.get('action_type', '?')} | {hit.get('title', '?')[:20]} | {hit.get('date', '?')} |\n"
    else:
        national_team_hits_table = "| — | — | — | — | — |\n"
    
    md = f"""# 📊 粗评报告

**评估日期**: {date_str}  
**标的数量**: {len(results)}只（可交易{len(tradeable_results)}只）  
**评估体系**: 十二维度独立评估 v5.0 (政策催化30% 技术面25% 资金面20% 基本面10% 情绪面10% 国家队面10% 板块面8% 热度面5% 筹码面5% 主力行为5% ZSCORE比价5% 反身性2%)

> ⚠️ 概率已校准（基于105条回测数据），A级系统偏差-10%，B级-4%，C级+12%
> 🛡️ T+1分层止损：首日-12% | 次日ATR缓冲 | 常态-8%
> 🆕 Phase 5: **政策催化**(30%权重) | **国家队面**(10%权重) | cninfo全量扫描(1500条公告)
> 🆕 ZSCORE板块比价: 四维共振(天时/地利/人和/技术) | 过热预警 | 超跌机会
> 🆕 反身性分析 v5.0: 📈Q1自我强化(趋势跟随·移动止盈) | 💎Q2萌芽/纠偏(观察·轻仓试探) | 🚫Q3恐慌/弱势(回避·等待) | ⚠️Q4背离反弹(谨慎·短差)
> 🆕 周线分析: MA排列(30%) | 趋势强度(25%) | MACD状态(25%) | 成交量确认(20%)

---

## 📊 政策催化概况 (v5.0新增)

- **采集时间**: {policy_collect_time}
- **数据新鲜度**: {policy_freshness}
- **部委覆盖**: {policy_coverage}
- **cninfo全量扫描**: {cninfo_hits}条命中

## 🏛️ 国家队资本动向 (v5.0新增)

- **大基金**: {dagang_action}
- **汇金/证金**: {huijin_action}
- **诚通/国新**: {chengtong_action}
- **社保/养老金**: {shebao_action}

**详细命中**:

| 代码 | 名称 | 动作类型 | 公告标题 | 日期 |
|------|------|---------|---------|------|
{national_team_hits_table}

---
{non_trade_section}"""

    # 北向资金概况
    north_flow = meta.get('north_flow', {})
    if north_flow and north_flow.get('direction') != 'neutral':
        direction_cn = {'inflow': '净流入', 'outflow': '净流出', 'neutral': '持平'}
        direction_icon = {'inflow': '🟢', 'outflow': '🔴', 'neutral': '⚪'}
        md += f"""## 🌊 北向资金概况

- **方向**: {direction_icon.get(north_flow['direction'], '')} {direction_cn.get(north_flow['direction'], '')}
- **5日累计**: {north_flow['recent_flow']:+.0f}亿
- **连续**: {north_flow['strength']}日

---

"""

    md += "## 🏆 最优标的\n\n"
    
    # 最优标的
    if results:
        best = results[0]
        raw_up = best.get('raw_up_prob', best['up_prob'])
        calib_note = f" (原始{raw_up}%）" if raw_up != best['up_prob'] else ""
        theme_str = f" | {best.get('hot_theme', '')}" if best.get('hot_theme') else ""
        md += f"""**{best['name']}** ({best['code']}) — {best['industry']}{theme_str}

| 指标 | 数值 | 指标 | 数值 |
|------|------|------|------|
| 现价 | ¥{best['close']:.2f} | 涨跌 | {best['pct_chg']:+.2f}% |
| 综合评分 | **{best['total']:.1f}分** | 等级 | **{best['grade']}级** |
| 上涨概率 | {best['up_prob']}% (原始{best['raw_up_prob']}%) | 下跌概率 | {best['down_prob']}% |
| 政策催化 | {best.get('policy', 50):.0f}分 | 国家队面 | {best.get('national', 50):.0f}分 |
| 技术面 | {best['tech']:.0f}分 | 资金面 | {best['cap']:.0f}分 |
| 情绪面 | {best['sent']:.0f}分 | 基本面 | {best['fund']:.0f}分 |
| 板块面 | {best['sect']:.0f}分 | 热度面 | {best['hot']:.0f}分 |
| ZSCORE比价 | {best.get('zscore', 50):.0f}分 | 反身性象限 | {best.get('reflexivity_stage_name', '—')} ({best.get('reflexivity_quadrant', '—')}) |
| 周线趋势 | {best.get('weekly_trend', '—')} ({best.get('weekly', 50):.0f}分) | 周均线 | {best.get('weekly_ma', '—')} |
| 主线 | {best.get('hot_theme', '—')} | 北向资金 | {best.get('north_note', '—')} |
| 股东户数 | {best.get('holder_note', '—')} | 筹码面 | {best.get('holder_dimension', 50):.0f}分 |
| 主力行为 | {best.get('mainforce_daily_grade') or '—'} (Bonus{best.get('mainforce_bonus', 0):+.0f}) | | """

        # 概念标签
        best_concepts = best.get('concepts', [])
        if best_concepts:
            concept_tags = '、'.join(best_concepts[:5])
            md += f"\n| 概念标签 | {concept_tags} | {' | '.join([''] * 2)} |"

        # ZSCORE四维共振
        zinfo = best.get('zscore_info', {})
        zr = best.get('zscore_resonance', {})
        if zinfo.get('matched'):
            dim_str = ' '.join(f"{'✓' if v else '✗'}{k}" for k, v in zr.get('dimensions', {}).items())
            md += f"\n| 板块ZSCORE | z={zinfo.get('z_composite', 0):.1f} ({zinfo.get('signal_desc', '—')}) | 四维共振({zr.get('count', 0)}/4) |"
            md += f"\n| 四维详情 | {dim_str} | {zinfo.get('sector_name', '')} |"

        md += f"""

**核心信号**: {'、'.join(best['tech_sig'][:2] + best['cap_sig'][:2])}

**操作建议**: {best['trend']} | 仓位{int(best['pos_pct']*100)}% | 持有{best['holding']}
**T+1止损**: 首日¥{best['stop_loss_day0']:.2f}({best['stop_pct_day0']}%) | 次日¥{best['stop_loss_day1']:.2f}({best['stop_pct_day1']}%) | 常态¥{best['stop_loss']:.2f}({best['stop_pct']}%)
**目标**: ¥{best['target']:.2f} | 盈亏比{best['rr']:.1f}:1 | ATR={best['atr']:.2f}

---

"""
    
    # 次优标的
    if len(tradeable_results) > 1:
        second = tradeable_results[1]
        # ZSCORE行
        zinfo2 = second.get('zscore_info', {})
        zscore_row = ""
        if zinfo2.get('matched'):
            zscore_row = f"\n| ZSCORE比价 | {second.get('zscore', 50):.0f}分 | 反身性象限 | {second.get('reflexivity_stage_name', '—')} ({second.get('reflexivity_quadrant', '—')}) |\n| 反身性强度 | {second.get('reflexivity_strength', 0):.0f}分 | SBI | {second.get('reflexivity_sbi', 0):+.0f} |\n| 周线趋势 | {second.get('weekly_trend', '—')} ({second.get('weekly', 50):.0f}分) | 周均线 | {second.get('weekly_ma', '—')} |"
        md += f"""## 🥈 次优标的

**{second['name']}** ({second['code']}) — {second['industry']}

| 指标 | 数值 | 指标 | 数值 |
|------|------|------|------|
| 现价 | ¥{second['close']:.2f} | 涨跌 | {second['pct_chg']:+.2f}% |
| 综合评分 | **{second['total']:.1f}分** | 等级 | **{second['grade']}级** |
| 上涨概率 | {second['up_prob']}% | 下跌概率 | {second['down_prob']}% |
| 技术面 | {second['tech']:.0f}分 | 资金面 | {second['cap']:.0f}分 |
| 板块面 | {second['sect']:.0f}分 | 热度面 | {second['hot']:.0f}分 |
| ZSCORE比价 | {second.get('zscore', 50):.0f}分 | 板块ZSCORE | z={zinfo2.get('z_composite', 0):.1f} ({zinfo2.get('signal_desc', '—')}) |
| 筹码面 | {second.get('holder_dimension', 50):.0f}分 | 主力行为 | {second.get('mainforce_daily_grade') or '—'} (Bonus{second.get('mainforce_bonus', 0):+.0f}) |

**核心信号**: {'、'.join(second['tech_sig'][:2] + second['cap_sig'][:2])}

---

"""
    
    # 全量对比表
    md += """## 📊 全量对比

| 排名 | 股票 | 评分 | 等级 | 现价 | 涨跌 | 上涨概率 | 技 | 资 | 情 | 基 | 板 | 热 | Z | 反 | 筹 | 主力 | 主线 | 概念 | 核心信号 |
|------|------|------|------|------|------|----------|----|----|----|----|----|----|---|---|---|---|------|------|------|
"""
    
    for i, r in enumerate(tradeable_results, 1):
        key_signals = (r['tech_sig'][:1] + r['cap_sig'][:1] + r['sect_sig'][:1])
        key_signals_str = '、'.join(key_signals) if key_signals else '无'
        
        # 板块共振+热度标注
        resonance_mark = ""
        if r.get('resonance') == 'hot':
            resonance_mark = " 🔥共振"
        elif r.get('resonance') == 'rising':
            resonance_mark = " 📈强势"
        # ZSCORE共振标注
        zr_count = r.get('zscore_resonance', {}).get('count', 0)
        if zr_count >= 4:
            resonance_mark += " ★Z共振"
        elif zr_count >= 3:
            resonance_mark += " ☆Z共振"
        
        theme_short = r.get('hot_theme', '').replace('🔥AI+数字经济', 'AI+数字经济').replace('⚙️新质生产力', '新质生产力').replace('✈️低空经济', '低空').replace('🔋新能源+储能', '新能源').replace('🏛️中特估+央企', '中特估').replace('🛒消费复苏', '消费').replace('💊医药健康', '医药').replace('🧪化工周期', '化工').replace('🏗️地产基建', '地产')[:8]
        
        # 概念标签
        concept_short = '、'.join(r.get('concepts', [])[:2]) if r.get('concepts') else '—'
        if len(concept_short) > 10:
            concept_short = concept_short[:10] + '…'
        
        # 反身性象限标记
        ref_quadrant = r.get('reflexivity_quadrant', 'Q0')
        quadrant_mark = {
            'Q1': '📈强化',
            'Q2': '💎萌芽',
            'Q3': '🚫弱势',
            'Q4': '⚠️背离',
        }.get(ref_quadrant, f"{r.get('reflexivity', 50):.0f}")
        mf_grade_disp = r.get('mainforce_daily_grade') or '—'
        md += f"| {i} | **{r['name']}**{resonance_mark} | {r['total']:.0f} | {r['grade']} | ¥{r['close']:.2f} | {r['pct_chg']:+.1f}% | {r['up_prob']}% | {r['tech']:.0f} | {r['cap']:.0f} | {r['sent']:.0f} | {r['fund']:.0f} | {r['sect']:.0f} | {r['hot']:.0f} | {r.get('zscore', 50):.0f} | {quadrant_mark} | {r.get('holder_dimension', 50):.0f} | {mf_grade_disp} | {theme_short} | {concept_short} | {key_signals_str} |\n"
    
    md += """
---

## 📈 趋势预测与操作建议

"""
    
    for r in tradeable_results:
        # 概念标签
        concept_str = '、'.join(r.get('concepts', [])[:3]) if r.get('concepts') else '无'
        
        # ZSCORE板块概况
        zinfo_r = r.get('zscore_info', {})
        zscore_detail = ""
        if zinfo_r.get('matched'):
            zr_r = r.get('zscore_resonance', {})
            dim_str_r = ' '.join(f"{'✓' if v else '✗'}{k}" for k, v in zr_r.get('dimensions', {}).items())
            z_price_val = zinfo_r.get('z_price', 0)
            z_vol_val = zinfo_r.get('z_vol', 0)
            z_comp_val = zinfo_r.get('z_composite', 0)
            z_sector = zinfo_r.get('sector_name', '—')
            z_sig_desc = zinfo_r.get('signal_desc', '—')
            z_res_count = zr_r.get('count', 0)
            zscore_detail = (
                f"\n- **板块ZSCORE概况**: z_price={z_price_val:.1f} | "
                f"z_vol={z_vol_val:.1f} | z_composite={z_comp_val:.1f}\n"
                f"- **四维共振信号**: {dim_str_r} ({z_res_count}/4) — {z_sector} | {z_sig_desc}\n"
            )
        else:
            zscore_detail = "\n- **板块ZSCORE**: 未匹配（数据不足或行业未覆盖）\n"
        
        # ZSCORE信号摘要
        zscore_sig_str = '、'.join(r.get('zscore_sig', [])[:4])
        
        # 构建改进版个股详情（v5.1可读性优化）
        stock_detail = f"""### {r['name']} ({r['code']})

**📊 核心参数**

| 项目 | 数值 | 项目 | 数值 |
|------|------|------|------|
| 趋势判断 | {r['trend']} | 预期收益 | {r['expected']} |
| 仓位 | {int(r['pos_pct']*100)}% | 持有周期 | {r['holding']} |
| 目标价 | ¥{r['target']:.2f} | 盈亏比 | {r['rr']:.1f}:1 |

**🛡️ T+1分层止损**

| 层级 | 止损价 | 跌幅 |
|------|--------|------|
| 首日 | ¥{r['stop_loss_day0']:.2f} | {r['stop_pct_day0']}% |
| 次日 | ¥{r['stop_loss_day1']:.2f} | {r['stop_pct_day1']}% |
| 常态 | ¥{r['stop_loss']:.2f} | {r['stop_pct']}% |

**🔎 基础信息**

- **概念板块**: {concept_str}
- **北向资金**: {r.get('north_note', '—')}
- **股东户数**: {r.get('holder_note', '—')}

**📐 ZSCORE板块比价**

- **ZSCORE评分**: {r.get('zscore', 50):.0f}分 | {zscore_sig_str}
{zscore_detail}

**🔄 反身性分析**

- **象限**: {r.get('reflexivity_stage_name', '—')} ({r.get('reflexivity_quadrant', '—')}) | {r.get('reflexivity', 50):.0f}分
- **SBI**: {r.get('reflexivity_sbi', 0):+.0f} | **价格趋势**: {r.get('reflexivity_price_trend', 0):+.2f} | **强度**: {r.get('reflexivity_strength', 0):.0f}
- **特征**: {'、'.join(r.get('reflexivity_signals', [])[:3])}
- **建议**: {r.get('reflexivity_operation', '—')}

**📈 周线趋势**

- **趋势**: {r.get('weekly_trend', '—')} ({r.get('weekly', 50):.0f}分) | 均线: {r.get('weekly_ma', '—')} | MACD: {r.get('weekly_macd', '—')} | 量能: {r.get('weekly_vol', '—')}
- **信号**: {'、'.join(r.get('weekly_signals', [])[:3])}

**🎯 主力行为 & 筹码集中度**

"""
        
        # 主力行为
        mf_grade = r.get('mainforce_daily_grade')
        mf_weekly_grade = r.get('mainforce_weekly_grade')
        mf_bonus = r.get('mainforce_bonus', 0)
        mf_aux = r.get('mainforce_daily_signals', [])
        mf_exit = r.get('mainforce_exit_signals', [])
        mf_details = r.get('mainforce_details', [])
        
        grade_icon = {'A': '🟡主进强', 'B': '🟣主进稳', 'C': '⚪主进试', 'D': '🟢主进弱'}.get(mf_grade, '—')
        wk_grade_icon = {'A': '🟡主进强', 'B': '🟣主进稳'}.get(mf_weekly_grade, '—')
        mf_bonus_str = f"+{mf_bonus}" if mf_bonus >= 0 else str(mf_bonus)
        mf_bonus_emoji = "🟢" if mf_bonus > 0 else ("🔴" if mf_bonus < 0 else "⚪")
        
        stock_detail += f"- **主力行为**: {mf_bonus_emoji} Bonus{mf_bonus_str} | 日线:{grade_icon} | 周线:{wk_grade_icon}\n"
        if mf_aux:
            stock_detail += f"  - 辅助: {'、'.join(mf_aux)}\n"
        if mf_exit:
            stock_detail += f"  - ⚠️ 退出: {'、'.join(mf_exit)}\n"
        if mf_details:
            stock_detail += f"  - 明细: {'；'.join(mf_details[:3])}\n"
        
        # 筹码集中度
        holder_sc = r.get('holder_dimension', 50)
        holder_chg = r.get('holder_change_pct', 0)
        holder_trend = r.get('holder_trend', 'unknown')
        holder_detail_txt = r.get('holder_detail', '—')
        trend_emoji = {'concentrated': '🔴高度集中', 'concentrating': '🟡趋于集中', 'stable': '⚪相对稳定', 'dispersing': '🔵分散迹象', 'dispersed': '⚠️高度分散', 'unknown': '—'}.get(holder_trend, '—')
        
        stock_detail += f"- **筹码集中**: {holder_sc:.0f}分 | {trend_emoji} | 变化{holder_chg:+.1f}%\n"
        stock_detail += f"  - {holder_detail_txt}\n\n"
        
        stock_detail += f"**⚠️ 风险提示**: {' '.join(r['risks'][:3])}\n\n"
        md += stock_detail
    
    # 板块面详细分析
    md += """---

## 🔥 板块共振分析

"""
    
    # 【新增】热门板块列表
    hot_sectors = meta.get('hot_sectors', [])
    if hot_sectors:
        md += "**当前热门板块**:\n\n"
        for hs in hot_sectors:
            icon = "🔥" if hs['level'] == 'hot' else "📈"
            md += f"- {icon} **{hs['name']}** (涨停{hs['limit_count']}家)\n"
        md += "\n"
    else:
        md += "⚠ 未检测到明显的热门板块\n\n"
    
    # 个股板块共振
    md += "**个股板块共振**:\n\n"
    for r in tradeable_results:
        # 过滤掉共振信号（单独用resonance_icon展示）
        non_resonance_sig = [s for s in r['sect_sig'] if '共振' not in s and '强势板块' not in s]
        sect_signals_str = '、'.join(non_resonance_sig) if non_resonance_sig else '无信号'
        resonance_icon = ""
        if r.get('resonance') == 'hot':
            resonance_icon = " 🔥热门板块共振"
        elif r.get('resonance') == 'rising':
            resonance_icon = " 📈强势板块"
        md += f"- **{r['name']}**: {r['sect']:.0f}分 — {sect_signals_str}{resonance_icon}\n"
    
    md += """
---

## ⚠️ 最弱标的

"""
    
    if tradeable_results:
        weakest = tradeable_results[-1]
        weakest_total = f"{weakest['total']:.1f}"
        weakest_grade = weakest['grade']
        weakest_up = weakest['up_prob']
        weakest_down = weakest['down_prob']
        weakest_tech = f"{weakest['tech']:.0f}"
        weakest_sect = f"{weakest['sect']:.0f}"
        weakest_risks = ' '.join(weakest['risks'][:3])
        md += f"""**{weakest['name']}** ({weakest['code']}) - {weakest['industry']}

| 指标 | 数值 | 指标 | 数值 |
|------|------|------|------|
| 综合评分 | **{weakest_total}分** | 等级 | **{weakest_grade}级** |
| 上涨概率 | {weakest_up}% | 下跌概率 | {weakest_down}% |
| 技术面 | {weakest_tech}分 | 板块面 | {weakest_sect}分 |

**风险提示**: {weakest_risks}

---

"""
    
    # ═══ 板块ZSCORE比价分析（新增独立区块）═══
    zscore_df_global = meta.get('zscore_df')
    zscore_date_global = meta.get('zscore_date')
    
    if zscore_df_global is not None and not zscore_df_global.empty:
        md += """## 📐 板块ZSCORE比价分析

"""
        if zscore_date_global:
            md += f"> ZSCORE数据日期: {zscore_date_global}\n\n"
        
        # 过热预警（z_composite >= 1.5）
        overheat_sectors = zscore_df_global[
            zscore_df_global['z_composite'].fillna(0) >= 1.5
        ].copy()
        if not overheat_sectors.empty:
            overheat_sectors = overheat_sectors.nlargest(10, 'z_composite')
            md += "### 🔴 过热预警\n\n"
            md += "| 板块 | z_composite | z_price | z_vol | 信号 |\n"
            md += "|------|-------------|---------|-------|------|\n"
            for _, row in overheat_sectors.iterrows():
                zc = row.get('z_composite', 0)
                sig, sig_desc = _get_zscore_signal(zc)
                md += f"| {row.get('sector_name', '')} | {zc:.2f} | {row.get('z_price', 0):.2f} | {row.get('z_vol', 0):.2f} | {sig_desc} |\n"
            md += "\n"
        else:
            md += "### 🔴 过热预警\n\n暂无过热板块（z_composite < 1.5）\n\n"
        
        # 超跌机会（z_composite <= -1.5）
        oversold_sectors = zscore_df_global[
            zscore_df_global['z_composite'].fillna(0) <= -1.5
        ].copy()
        if not oversold_sectors.empty:
            oversold_sectors = oversold_sectors.nsmallest(10, 'z_composite')
            md += "### 🟢 超跌机会\n\n"
            md += "| 板块 | z_composite | z_price | z_vol | 信号 |\n"
            md += "|------|-------------|---------|-------|------|\n"
            for _, row in oversold_sectors.iterrows():
                zc = row.get('z_composite', 0)
                sig, sig_desc = _get_zscore_signal(zc)
                md += f"| {row.get('sector_name', '')} | {zc:.2f} | {row.get('z_price', 0):.2f} | {row.get('z_vol', 0):.2f} | {sig_desc} |\n"
            md += "\n"
        else:
            md += "### 🟢 超跌机会\n\n暂无超跌板块（z_composite > -1.5）\n\n"
        
        # 评估标的中涉及的板块ZSCORE
        md += "### 📋 评估标的板块ZSCORE\n\n"
        md += "| 股票 | 行业 | 匹配板块 | z_composite | 信号 |\n"
        md += "|------|------|----------|-------------|------|\n"
        for r in tradeable_results:
            zi = r.get('zscore_info', {})
            if zi.get('matched'):
                md += f"| {r['name']} | {r['industry']} | {zi.get('sector_name', '—')} | {zi.get('z_composite', 0):.2f} | {zi.get('signal_desc', '—')} |\n"
            else:
                md += f"| {r['name']} | {r['industry']} | 未匹配 | — | — |\n"
        md += "\n---\n\n"
    else:
        md += """## 📐 板块ZSCORE比价分析

> ZSCORE数据未加载或已过期，此区块暂不可用。

---

"""
    
    # ═══ 反身性四象限分析区块 ═══
    md += """## 🔄 反身性四象限分析

"""
    
    # 按象限分组
    q1_list = [r for r in tradeable_results if r.get('reflexivity_quadrant') == 'Q1']
    q2_list = [r for r in tradeable_results if r.get('reflexivity_quadrant') == 'Q2']
    q3_list = [r for r in tradeable_results if r.get('reflexivity_quadrant') == 'Q3']
    q4_list = [r for r in tradeable_results if r.get('reflexivity_quadrant') == 'Q4']
    
    # Q1 自我强化
    if q1_list:
        md += "### 📈 Q1 自我强化（正反馈循环）— 偏见乐观+价格上涨\n\n"
        for r in q1_list:
            sigs = '、'.join(r.get('reflexivity_signals', [])[:3])
            bubbles = ' '.join(r.get('reflexivity_bubble_signals', [])[:2])
            bubble_warn = f" | ⚠️ {bubbles}" if bubbles else ""
            md += f"- **{r['name']}** ({r['code']}): SBI={r.get('reflexivity_sbi', 0):+.0f} 强度={r.get('reflexivity_strength', 0):.0f} | {sigs}{bubble_warn}\n"
        md += "\n"
    
    # Q2 萌芽/纠偏
    if q2_list:
        md += "### 💎 Q2 萌芽/纠偏（预期领先）— 偏见乐观+价格未涨\n\n"
        for r in q2_list:
            sigs = '、'.join(r.get('reflexivity_signals', [])[:3])
            md += f"- **{r['name']}** ({r['code']}): SBI={r.get('reflexivity_sbi', 0):+.0f} | {sigs} | 操作建议: {r.get('reflexivity_operation', '')}\n"
        md += "\n"
    
    # Q3 恐慌/弱势
    if q3_list:
        md += "### 🚫 Q3 恐慌/弱势（负反馈循环）— 偏见悲观+价格下跌\n\n"
        for r in q3_list:
            sigs = '、'.join(r.get('reflexivity_signals', [])[:3])
            md += f"- **{r['name']}** ({r['code']}): SBI={r.get('reflexivity_sbi', 0):+.0f} | {sigs} | 操作建议: {r.get('reflexivity_operation', '')}\n"
        md += "\n"
    
    # Q4 背离反弹
    if q4_list:
        md += "### ⚠️ Q4 背离反弹（缺乏共识）— 偏见悲观+价格上涨\n\n"
        for r in q4_list:
            sigs = '、'.join(r.get('reflexivity_signals', [])[:3])
            md += f"- **{r['name']}** ({r['code']}): SBI={r.get('reflexivity_sbi', 0):+.0f} | {sigs} | 操作建议: {r.get('reflexivity_operation', '')}\n"
        md += "\n"
    
    if not q1_list and not q2_list and not q3_list and not q4_list:
        md += "✅ 所有可交易标的暂无明确反身性象限信号\n\n"
    
    md += """**反身性分析说明**:
- **SBI（主流偏见指数）**: -100~+100，反映市场乐观(+)/悲观(-)程度
- **价格趋势**: -1~+1，反映近期价格涨跌方向
- **四象限模型**: 基于索罗斯反身性理论，价格与主流偏见相互作用形成反馈循环
- **泡沫信号**: 为风险叠加层，任何象限出现泡沫信号都需警惕

| 象限 | 名称 | 偏见方向 | 价格趋势 | 反身性特征 | 操作建议 |
|------|------|----------|----------|------------|----------|
| Q1 | 📈自我强化 | 乐观 | 上涨 | 正反馈循环，趋势延续概率高 | 趋势跟随+移动止盈 |
| Q2 | 💎萌芽/纠偏 | 乐观 | 未涨 | 预期领先价格或纠偏中 | 观察/轻仓试探 |
| Q3 | 🚫恐慌/弱势 | 悲观 | 下跌 | 负反馈循环，恐慌抛售或阴跌 | 回避/等待 |
| Q4 | ⚠️背离反弹 | 悲观 | 上涨 | 反弹缺乏共识，易受利空打压 | 谨慎/短差 |

---

"""
    
    # ═══ 周线趋势分析区块 ═══
    md += """## 📈 周线趋势分析

| 股票 | 周线评分 | 趋势判断 | 均线状态 | MACD | 量能 | 核心信号 |
|------|----------|----------|----------|------|------|----------|
"""
    for r in tradeable_results:
        sigs = '、'.join(r.get('weekly_signals', [])[:2])
        md += f"| **{r['name']}** | {r.get('weekly', 50):.0f}分 | {r.get('weekly_trend', '—')} | {r.get('weekly_ma', '—')} | {r.get('weekly_macd', '—')} | {r.get('weekly_vol', '—')} | {sigs} |\n"
    
    md += """
**周线分析说明**:
- 周线评分基于均线排列(30%) + 趋势强度(25%) + MACD状态(25%) + 成交量确认(20%)
- 周线用于判断中长期趋势方向，与日线操作形成共振或背离参考
- **日线强+周线强** = 高胜率趋势行情，建议积极参与
- **日线强+周线弱** = 短期反弹需谨慎，注意背离风险
- **日线弱+周线强** = 可能处于洗盘或回调阶段，可观察等待
- **日线弱+周线弱** = 整体弱势，建议回避

---

"""
    
    md += f"""*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}*  
*评估体系: 十维度独立评估 v5.1 (技术面15% 资金面15% 情绪面10% 基本面5% 板块面10% 热度面10% ZSCORE比价16% 反身性9% 筹码面5% 主力行为5%)*
*概率校准: 基于105条回测数据，等级偏差 S:-10% A:-10% B:-4% C:+12% D:+20%*
*Phase 3: 动态概念板块(ths_member) | 北向资金(moneyflow_hsgt) | 股东户数(stk_holdernumber)*
*ZSCORE板块比价: 四维共振(天时/地利/人和/技术) | 过热预警 | 超跌机会*
*反身性分析 v5.0: 📈Q1自我强化(趋势跟随+移动止盈) | 💎Q2萌芽/纠偏(观察+轻仓试探) | 🚫Q3恐慌/弱势(回避+等待) | ⚠️Q4背离反弹(谨慎+短差) | SBI主流偏见指数 | 泡沫风险叠加*
*周线分析: MA排列(30%)+趋势强度(25%)+MACD状态(25%)+成交量确认(20%) | 日线强+周线强=共振 | 日线强+周线弱=背离风险*
"""
    
    # 保存报告
    filepath = os.path.join(save_dir, f"{report_name}.md")
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(md)
    
    print(f"\n✓ 报告已保存: {filepath}")
    
    # 【Phase 2】自动记录信号到SignalTracker + 验证到期信号
    tracker = SignalTracker()
    tracker.track(results)
    tracker.verify_pending(verbose=True)
    
    return filepath


# ═══════════════════════════════════════════════════
#  Phase 2: SignalTracker — 自我进化闭环
# ═══════════════════════════════════════════════════

class SignalTracker:
    """
    信号跟踪器 — 记录每次评估，到期后验证，持续积累真实胜率
    
    工作流:
    1. track(): 记录今日评估结果为待验证信号
    2. verify_pending(): 检查到期信号，用真实收盘价验证
    3. stats(): 输出按等级/维度的真实胜率统计
    """
    
    def __init__(self, save_path=None):
        if save_path is None:
            save_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                                      'signal_tracker.json')
        self.save_path = save_path
        self.signals = self._load()
    
    def _load(self):
        if os.path.exists(self.save_path):
            try:
                with open(self.save_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return []
    
    def _save(self):
        with open(self.save_path, 'w', encoding='utf-8') as f:
            json.dump(self.signals, f, ensure_ascii=False, indent=2)
    
    def track(self, results, eval_date=None, hold_days=5):
        """
        记录评估结果
        
        参数:
            results: evaluate_batch 返回的评估结果列表
            eval_date: 评估日期
            hold_days: 持有天数（到期验证日）
        """
        if eval_date is None:
            eval_date = datetime.now().strftime('%Y%m%d')
        
        # 计算到期验证日：从eval_date往后推hold_days个交易日
        future_end = (datetime.strptime(eval_date, '%Y%m%d') + timedelta(days=hold_days * 2 + 5)).strftime('%Y%m%d')
        try:
            df = pro.trade_cal(exchange='SSE', start_date=eval_date, end_date=future_end, is_open='1')
            if df is not None and not df.empty:
                future_dates = sorted(df['cal_date'].tolist())
                if len(future_dates) > hold_days:
                    future_date = future_dates[hold_days]
                elif len(future_dates) > 0:
                    future_date = future_dates[-1]
                else:
                    future_date = eval_date
            else:
                future_date = eval_date
        except Exception:
            future_date = eval_date
        
        new_count = 0
        for r in results:
            if r.get('error') or not r.get('tradeable', True):
                continue
            
            signal = {
                'eval_date': eval_date,
                'future_date': future_date,
                'code': r['code'],
                'name': r['name'],
                'industry': r.get('industry', ''),
                'close': r['close'],
                'total': r['total'],
                'grade': r['grade'],
                'up_prob': r['up_prob'],
                'hot_theme': r.get('hot_theme', ''),
                'tech': r['tech'],
                'cap': r['cap'],
                'sent': r['sent'],
                'fund': r['fund'],
                'sect': r['sect'],
                'hot': r['hot'],
                'north_note': r.get('north_note', ''),      # Phase 3
                'holder_note': r.get('holder_note', ''),    # Phase 3
                'concepts': r.get('concepts', []),          # Phase 3
                'status': 'pending',
                'verified_at': None,
                'actual_return': None,
                'hit': None,
            }
            
            # 防止重复记录
            existing = [s for s in self.signals 
                        if s['code'] == r['code'] and s['eval_date'] == eval_date]
            if not existing:
                self.signals.append(signal)
                new_count += 1
        
        if new_count > 0:
            self._save()
            print(f"  📡 已记录 {new_count} 条待验证信号")
        
        return new_count
    
    def verify_pending(self, verbose=True):
        """
        验证所有到期信号
        """
        today = datetime.now().strftime('%Y%m%d')
        verified_count = 0
        
        for signal in self.signals:
            if signal['status'] != 'pending':
                continue
            if signal['future_date'] > today:
                continue
            
            # 获取到期日的真实收盘价
            try:
                future_df = pro.daily(
                    ts_code=signal['code'],
                    start_date=signal['future_date'],
                    end_date=signal['future_date']
                )
                if future_df is None or future_df.empty:
                    continue
                
                future_close = float(future_df.iloc[0]['close'])
                actual_return = round(
                    (future_close / signal['close'] - 1) * 100, 2
                )
                
                signal['actual_return'] = actual_return
                signal['hit'] = actual_return > 0
                signal['status'] = 'verified'
                signal['verified_at'] = today
                verified_count += 1
                
                if verbose:
                    hit_mark = "✅" if signal['hit'] else "❌"
                    print(f"  {hit_mark} {signal['name']} ({signal['eval_date']}→{signal['future_date']}) "
                          f"预测↑{signal['up_prob']}% | 实际{actual_return:+.1f}% | {signal['grade']}级")
                
            except Exception as e:
                if verbose:
                    print(f"  ⚠ {signal['name']} 验证失败: {e}")
        
        if verified_count > 0:
            self._save()
            print(f"  ✓ 验证完成: {verified_count} 条")
        
        return verified_count
    
    def stats(self):
        """返回按等级统计的真实胜率"""
        verified = [s for s in self.signals if s['status'] == 'verified']
        if not verified:
            return {'total_verified': 0, 'by_grade': {}, 'overall_win_rate': 0}
        
        by_grade = {}
        for grade in ['S', 'A', 'B', 'C', 'D']:
            records = [s for s in verified if s['grade'] == grade]
            if not records:
                continue
            hits = sum(1 for s in records if s['hit'])
            returns = [s['actual_return'] for s in records]
            by_grade[grade] = {
                'count': len(records),
                'hits': hits,
                'win_rate': round(hits / len(records) * 100, 1),
                'avg_return': round(sum(returns) / len(returns), 2),
                'max_return': round(max(returns), 2),
                'min_return': round(min(returns), 2),
            }
        
        all_hits = sum(1 for s in verified if s['hit'])
        
        return {
            'total_verified': len(verified),
            'total_pending': len([s for s in self.signals if s['status'] == 'pending']),
            'overall_win_rate': round(all_hits / len(verified) * 100, 1),
            'overall_avg_return': round(
                sum(s['actual_return'] for s in verified) / len(verified), 2
            ),
            'by_grade': by_grade,
        }
    
    def print_stats(self):
        st = self.stats()
        print(f"\n{'='*60}")
        print(f"  📡 SignalTracker 统计")
        print(f"{'='*60}")
        print(f"  已验证: {st.get('total_verified', 0)} 条 | 待验证: {st.get('total_pending', 0)} 条")
        if st.get('total_verified', 0) > 0:
            print(f"  整体胜率: {st.get('overall_win_rate', 0)}% | 平均收益: {st.get('overall_avg_return', 0):+.2f}%")
        
        if st.get('by_grade'):
            print(f"\n  {'等级':<6} {'样本':<6} {'胜率':<8} {'平均收益':<10} {'最大':<8} {'最小':<8}")
            print(f"  {'-'*6} {'-'*6} {'-'*8} {'-'*10} {'-'*8} {'-'*8}")
            for grade in ['S', 'A', 'B', 'C', 'D']:
                gs = st.get('by_grade', {}).get(grade)
                if gs:
                    print(f"  {grade:<6} {gs['count']:<6} {gs['win_rate']:<8.1f}% "
                          f"{gs['avg_return']:>+8.2f}%  {gs['max_return']:>+6.2f}% {gs['min_return']:>+6.2f}%")
        print(f"{'='*60}")


# ═══════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════

if __name__ == '__main__':
    # 测试股票列表
    test_codes = ['601728.SH', '002268.SZ', '601688.SH', '002823.SZ', '600834.SH', '000839.SZ', '600839.SH']
    
    print("=" * 60)
    print("粗评报告模板 v4.1 — 八维度+ZSCORE板块比价+反身性分析+风控+自我进化")
    print("Phase 1: 热度面+概率校准")
    print("Phase 2: T+1分层止损+可交易性检测+SignalTracker")
    print("Phase 3: 动态概念板块+北向资金+股东户数")
    print("Phase 4: ZSCORE板块比价+四维共振(天时/地利/人和/技术)")
    print("=" * 60)
    
    generate_report(test_codes, report_name="粗评报告_测试_v4")


def calc_main_force_signals(df_daily, df_weekly=None, sector_df=None, benchmark_df=None, end_date=None):
    """
    复现通达信"主力全景"指标的核心买入信号
    
    核心逻辑:
    - R0 = pct_chg * (vol / ma_vol_5)
    - 波动线 = EMA((close - LLV(low,10)) / (HHV(high,25) - LLV(low,10)) * 4, 4)
    - 平均线 = EMA(波动线, 3)
    - 主力进 = R0 - sum(abs(prev_R0[1:5])) - abs(prev_R0[5])/2 > 0
              AND 平均线 >= prev_平均线 AND prev_平均线 < prev2_平均线
    
    返回: {
        'daily': {'has_strong': bool, 'has_stable': bool, 'grade': str, 'aux_signals': list},
        'weekly': {'has_strong': bool, 'has_stable': bool, 'grade': str},
        'bonus': float,  # -6 ~ +8
        'details': list
    }
    """
    import numpy as np
    
    result = {
        'daily': {'has_strong': False, 'has_stable': False, 'grade': None, 'aux_signals': [], 'exit_signals': []},
        'weekly': {'has_strong': False, 'has_stable': False, 'grade': None},
        'bonus': 0,
        'details': []
    }
    
    if df_daily is None or df_daily.empty or len(df_daily) < 10:
        result['details'].append('日线数据不足，无法计算主力信号')
        return result
    
    dfc = df_daily.copy()
    # 确保按日期升序排列（从旧到新）
    if 'trade_date' in dfc.columns:
        dfc = dfc.sort_values('trade_date', ascending=True).reset_index(drop=True)
    
    close = dfc['close'].values
    high = dfc['high'].values
    low = dfc['low'].values
    vol = dfc['vol'].values
    
    # 涨跌幅（如pct_chg不存在，用close计算）
    if 'pct_chg' in dfc.columns:
        pct_chg = dfc['pct_chg'].values
    else:
        pct_chg = np.concatenate([[0], (close[1:] / close[:-1] - 1) * 100])
    
    # 1. 计算核心变量
    # VV = VOL / MA(VOL,5)
    ma_vol_5 = pd.Series(vol).rolling(5, min_periods=1).mean().values
    vv = vol / (ma_vol_5 + 1e-9)
    
    # R0 = pct_chg * VV
    r0 = pct_chg * vv
    
    # LLV(L,10) 和 HHV(H,25)
    llv_10 = pd.Series(low).rolling(10, min_periods=1).min().values
    hhv_25 = pd.Series(high).rolling(25, min_periods=1).max().values
    
    # 波动线 = EMA((C - LLV(L,10)) / (HHV(H,25) - LLV(L,10)) * 4, 4)
    range_val = hhv_25 - llv_10
    range_val = np.where(range_val == 0, 1e-9, range_val)
    raw_wave = (close - llv_10) / range_val * 4
    wave_line = pd.Series(raw_wave).ewm(span=4, adjust=False).mean().values
    
    # 平均线 = EMA(波动线, 3)
    avg_line = pd.Series(wave_line).ewm(span=3, adjust=False).mean().values
    
    # 2. 判断"主力进"
    n = len(dfc)
    main_force_in = np.zeros(n, dtype=bool)
    for i in range(6, n):
        sum_abs_r0 = abs(r0[i-1]) + abs(r0[i-2]) + abs(r0[i-3]) + abs(r0[i-4]) + abs(r0[i-5]) / 2
        cond1 = r0[i] - sum_abs_r0 > 0
        cond2 = avg_line[i] >= avg_line[i-1]
        cond3 = avg_line[i-1] < avg_line[i-2]
        main_force_in[i] = cond1 and cond2 and cond3
    
    # 3. 辅助信号检测（简化版）
    # 信息 = 平均线 >= REF(平均线,1)
    info_signal = avg_line[1:] >= avg_line[:-1]
    info_signal = np.concatenate([[False], info_signal])
    
    # 走强 = C > MA(C,20) AND C > MA(C,5)
    ma5 = pd.Series(close).rolling(5, min_periods=1).mean().values
    ma20 = pd.Series(close).rolling(20, min_periods=1).mean().values
    strong = (close > ma20) & (close > ma5)
    
    # 量 = VOL > MA(VOL,5)
    volume_up = vol > ma_vol_5
    
    # D: 极底 = 信息=1 AND REF(信息,1)=0 AND (REF(信息,2)+REF(信息,3)=0) AND 平均线<0.5
    extreme_bottom = np.zeros(n, dtype=bool)
    for i in range(4, n):
        if (info_signal[i] and not info_signal[i-1] and 
            not info_signal[i-2] and not info_signal[i-3] and avg_line[i] < 0.5):
            extreme_bottom[i] = True
    
    # S: 升 = 信息=1 AND REF(信息,1)=0 AND (REF(信息,2)+REF(信息,3)=0) AND 走强=1 AND 量=1
    rise_signal = np.zeros(n, dtype=bool)
    for i in range(4, n):
        if (info_signal[i] and not info_signal[i-1] and 
            not info_signal[i-2] and not info_signal[i-3] and strong[i] and volume_up[i]):
            rise_signal[i] = True
    
    # 资金攻击 = C/REF(C,1)>1.05 AND (C-O)/O>0.04 AND DCZ上升 AND MA20上升 AND C>MA20 AND VOL>MA(VOL,5)*1.5
    open_p = dfc['open'].values if 'open' in dfc.columns else close
    attack = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if (close[i] / close[i-1] > 1.05 and 
            (close[i] - open_p[i]) / (open_p[i] + 1e-9) > 0.04 and
            ma20[i] > ma20[i-1] and close[i] > ma20[i] and vol[i] > ma_vol_5[i] * 1.5):
            attack[i] = True
    
    # 主退 = R0 + sum_abs > 0 AND 平均线 <= REF AND REF > REF2
    main_force_out = np.zeros(n, dtype=bool)
    for i in range(6, n):
        sum_abs_r0 = abs(r0[i-1]) + abs(r0[i-2]) + abs(r0[i-3]) + abs(r0[i-4]) + abs(r0[i-5]) / 2
        cond1 = r0[i] + sum_abs_r0 < 0
        cond2 = avg_line[i] <= avg_line[i-1]
        cond3 = avg_line[i-1] > avg_line[i-2]
        main_force_out[i] = cond1 and cond2 and cond3
    
    # 4. 行业主线和大盘多头（简化，优先用已有数据）
    sector_main = False
    sector_bull = False
    sector_lead = False
    benchmark_bull = False
    
    if sector_df is not None and not sector_df.empty and len(sector_df) >= 60:
        sc = sector_df.sort_values('trade_date', ascending=True).reset_index(drop=True)
        s_close = sc['close'].values
        s_ma20 = pd.Series(s_close).rolling(20, min_periods=1).mean().values
        s_ma60 = pd.Series(s_close).rolling(60, min_periods=1).mean().values
        if len(s_close) > 0:
            sector_bull = s_close[-1] > s_ma20[-1] and s_ma20[-1] > s_ma60[-1]
            sector_main = sector_bull
        
        if benchmark_df is not None and not benchmark_df.empty and len(benchmark_df) >= 20:
            bm = benchmark_df.sort_values('trade_date', ascending=True).reset_index(drop=True)
            bm_close = bm['close'].values
            s_ma20_full = pd.Series(s_close).rolling(20, min_periods=1).mean().values
            rel = s_close / (bm_close[:len(s_close)] + 1e-9)
            rel_ma20 = pd.Series(rel).rolling(20, min_periods=1).mean().values
            if len(rel) > 0:
                sector_lead = rel[-1] > rel_ma20[-1]
    
    if benchmark_df is not None and not benchmark_df.empty and len(benchmark_df) >= 65:
        bm = benchmark_df.sort_values('trade_date', ascending=True).reset_index(drop=True)
        bm_close = bm['close'].values
        bm_ma60 = pd.Series(bm_close).rolling(60, min_periods=1).mean().values
        if len(bm_close) > 5:
            benchmark_bull = bm_close[-1] > bm_ma60[-1] and bm_ma60[-1] > bm_ma60[-6]
    
    # 5. A/B/C/D级判定
    grades = np.full(n, None, dtype=object)
    for i in range(n):
        if not main_force_in[i]:
            continue
        # A级: 主力进 + 行业主线 + 大盘多头 + 放量1.5倍 + C>MA20
        if (sector_main and benchmark_bull and 
            vol[i] > ma_vol_5[i] * 1.5 and close[i] > ma20[i]):
            grades[i] = 'A'
        # B级: 主力进 + (行业多头 OR 行业领涨) + 平均线<2.3 + 花神红(C>MA5)
        elif ((sector_bull or sector_lead) and avg_line[i] < 2.3 and close[i] > ma5[i]):
            grades[i] = 'B'
        # C级: 主力进 + 10日振幅<25%
        elif (i >= 10):
            hhv10 = high[max(0,i-9):i+1].max()
            llv10 = low[max(0,i-9):i+1].min()
            if hhv10 / (llv10 + 1e-9) < 1.25:
                grades[i] = 'C'
        else:
            grades[i] = 'D'
    
    # 取最近2个交易日
    last_idx = n - 1
    recent_range = range(max(0, last_idx - 1), last_idx + 1)
    
    for i in recent_range:
        if grades[i] == 'A':
            result['daily']['has_strong'] = True
            result['daily']['grade'] = 'A'
        elif grades[i] == 'B' and result['daily']['grade'] != 'A':
            result['daily']['has_stable'] = True
            result['daily']['grade'] = 'B'
        elif grades[i] in ('C', 'D') and result['daily']['grade'] is None:
            result['daily']['grade'] = grades[i]
    
    # 辅助信号（最近2日）
    for i in recent_range:
        if extreme_bottom[i]:
            result['daily']['aux_signals'].append('极底')
        if rise_signal[i]:
            result['daily']['aux_signals'].append('升')
        if attack[i]:
            result['daily']['aux_signals'].append('资金攻击')
        if main_force_out[i]:
            result['daily']['exit_signals'].append('主退')
    
    # 去重
    result['daily']['aux_signals'] = list(dict.fromkeys(result['daily']['aux_signals']))
    result['daily']['exit_signals'] = list(dict.fromkeys(result['daily']['exit_signals']))
    
    # 6. 周线信号
    if df_weekly is not None and not df_weekly.empty and len(df_weekly) >= 3:
        wk = df_weekly.copy()
        if 'trade_date' in wk.columns:
            wk = wk.sort_values('trade_date', ascending=True).reset_index(drop=True)
        
        w_close = wk['close'].values
        w_high = wk['high'].values
        w_low = wk['low'].values
        w_vol = wk['vol'].values
        
        if 'pct_chg' in wk.columns:
            w_pct = wk['pct_chg'].values
        else:
            w_pct = np.concatenate([[0], (w_close[1:] / w_close[:-1] - 1) * 100])
        
        w_ma_vol_5 = pd.Series(w_vol).rolling(5, min_periods=1).mean().values
        w_vv = w_vol / (w_ma_vol_5 + 1e-9)
        w_r0 = w_pct * w_vv
        
        w_llv_10 = pd.Series(w_low).rolling(10, min_periods=1).min().values
        w_hhv_25 = pd.Series(w_high).rolling(25, min_periods=1).max().values
        w_range = w_hhv_25 - w_llv_10
        w_range = np.where(w_range == 0, 1e-9, w_range)
        w_raw = (w_close - w_llv_10) / w_range * 4
        w_wave = pd.Series(w_raw).ewm(span=4, adjust=False).mean().values
        w_avg = pd.Series(w_wave).ewm(span=3, adjust=False).mean().values
        
        w_n = len(wk)
        w_mf = np.zeros(w_n, dtype=bool)
        for i in range(6, w_n):
            s = abs(w_r0[i-1]) + abs(w_r0[i-2]) + abs(w_r0[i-3]) + abs(w_r0[i-4]) + abs(w_r0[i-5]) / 2
            w_mf[i] = (w_r0[i] - s > 0 and w_avg[i] >= w_avg[i-1] and w_avg[i-1] < w_avg[i-2])
        
        # 上周 = 倒数第2根周线（最后1根是当周，可能不完整）
        if w_n >= 2:
            last_w_idx = w_n - 2  # 上周
            if w_mf[last_w_idx]:
                # 简化判定：有主力进即算B级，如有放量则A级
                if w_vol[last_w_idx] > w_ma_vol_5[last_w_idx] * 1.5:
                    result['weekly']['has_strong'] = True
                    result['weekly']['grade'] = 'A'
                else:
                    result['weekly']['has_stable'] = True
                    result['weekly']['grade'] = 'B'
    
    # 7. Bonus计算
    bonus = 0
    if result['daily']['has_strong']:
        bonus += 3
        result['details'].append('日线近2日主进强(+3)')
    elif result['daily']['has_stable']:
        bonus += 2
        result['details'].append('日线近2日主进稳(+2)')
    
    if result['weekly']['has_strong']:
        bonus += 3
        result['details'].append('周线上周主进强(+3)')
    elif result['weekly']['has_stable']:
        bonus += 2
        result['details'].append('周线上周主进稳(+2)')
    
    # 辅助信号加分（上限+2）
    aux_bonus = min(len(result['daily']['aux_signals']), 2)
    bonus += aux_bonus
    if aux_bonus > 0:
        result['details'].append(f"辅助信号{result['daily']['aux_signals']}(+{aux_bonus})")
    
    # 退出信号扣分
    exit_penalty = len(result['daily']['exit_signals']) * 2
    bonus -= exit_penalty
    if exit_penalty > 0:
        result['details'].append(f"退出信号{result['daily']['exit_signals']}(-{exit_penalty})")
    
    result['bonus'] = max(-6, min(8, bonus))
    return result


def calc_holder_dimension(holder_data):
    """
    散户数量变化评分（筹码集中度维度）
    
    评分逻辑:
    - 股东户数减少>15%: 90-100分（筹码高度集中，主力吸筹）
    - 股东户数减少5-15%: 70-90分（筹码趋于集中）
    - 股东户数变化±5%: 50-70分（筹码稳定）
    - 股东户数增加5-20%: 30-50分（筹码分散迹象）
    - 股东户数增加>20%: 0-30分（筹码高度分散，散户涌入）
    
    返回: {
        'score': 0-100,
        'trend': 'concentrated'/'stable'/'dispersed',
        'change_pct': float,
        'details': str
    }
    """
    if holder_data is None:
        return {'score': 50, 'trend': 'unknown', 'change_pct': 0, 'details': '数据缺失'}
    
    change_pct = holder_data.get('change_pct', 0)
    trend = holder_data.get('trend', 'stable')
    
    if change_pct <= -15:
        score = 95 + min(5, abs(change_pct + 15) * 0.5)
        trend_name = 'concentrated'
        detail = f'筹码高度集中({change_pct:+.1f}%)，主力吸筹'
    elif change_pct <= -5:
        score = 75 + min(15, abs(change_pct + 5) * 2)
        trend_name = 'concentrating'
        detail = f'筹码趋于集中({change_pct:+.1f}%)'
    elif change_pct <= 5:
        score = 55 + min(10, abs(change_pct) * 1)
        trend_name = 'stable'
        detail = f'筹码相对稳定({change_pct:+.1f}%)'
    elif change_pct <= 20:
        score = 40 - min(10, (change_pct - 5) * 0.7)
        trend_name = 'dispersing'
        detail = f'筹码分散迹象({change_pct:+.1f}%)'
    else:
        score = max(0, 30 - (change_pct - 20) * 0.5)
        trend_name = 'dispersed'
        detail = f'筹码高度分散({change_pct:+.1f}%)，散户涌入'
    
    return {
        'score': round(score, 1),
        'trend': trend_name,
        'change_pct': change_pct,
        'details': detail
    }


# ═══════════════════════════════════════════════════
#  v5.0: 政策催化维度 (Policy Dimension)
# ═══════════════════════════════════════════════════

def load_policy_sentry():
    """
    从 cn_tracker.py 哨兵文件读取政策数据
    返回：dict {
        'policy_keywords_hits': int,    # 部委政策关键词命中数
        'policy_sources': dict,          # 各部委HTML字节数
        'cninfo_hits': int,              # cninfo全量扫描命中数
        'scan_errors': int,              # 扫描错误数
        'has_fresh_data': bool,          # 数据是否新鲜（<=24h）
        'collect_time': str,             # 采集时间
    }
    """
    result = {
        'policy_keywords_hits': 0,
        'policy_sources': {},
        'cninfo_hits': 0,
        'scan_errors': 0,
        'has_fresh_data': False,
        'collect_time': '',
    }
    
    if not os.path.exists(CN_TRACKER_DONE):
        return result
    
    try:
        with open(CN_TRACKER_DONE, encoding='utf-8') as f:
            meta = json.load(f)
        
        result['collect_time'] = meta.get('dt', '')
        
        # 部委HTML字节数
        for key in ['ndrc_bytes', 'miit_bytes', 'nea_bytes', 'nda_bytes', 'sasac_bytes']:
            result['policy_sources'][key.replace('_bytes', '')] = meta.get(key, 0)
        
        # cninfo全量扫描命中
        result['cninfo_hits'] = meta.get('cninfo_fullscan_hits', 0)
        result['scan_errors'] = meta.get('cninfo_scan_errors', 0)
        
        # 数据新鲜度（<=24h）
        if result['collect_time']:
            try:
                dt = datetime.strptime(result['collect_time'], "%Y-%m-%d %H:%M:%S")
                hours_since = (datetime.now() - dt).total_seconds() / 3600
                result['has_fresh_data'] = hours_since <= 24
            except:
                result['has_fresh_data'] = False
        
        # 从部委HTML中统计政策关键词命中数（简化版）
        total_bytes = sum(result['policy_sources'].values())
        if total_bytes > 200000:  # 总字节数>200KB说明采集成功
            result['policy_keywords_hits'] = 100  # 默认高分
        
        return result
    
    except Exception:
        return result


def calc_policy_score(policy_data):
    """
    政策催化评分 (0-100分)
    
    评分逻辑：
    - 数据新鲜度 (20%)：采集时间<=24h
    - 部委覆盖度 (30%)：4个部委HTML采集成功
    - cninfo命中数 (30%)：全量扫描命中国家队公告数
    - 扫描错误率 (20%)：扫描错误越少分数越高
    
    返回：(score, signals)
    """
    score = 50
    signals = []
    
    if not policy_data.get('has_fresh_data'):
        score -= 20
        signals.append("⚠️ 政策数据滞后(>24h)")
        return score, signals
    
    # 部委覆盖度
    sources = policy_data.get('policy_sources', {})
    active_sources = sum(1 for v in sources.values() if v > 10000)  # 字节数>10KB算成功
    if active_sources >= 4:
        score += 25
        signals.append(f"✅ {active_sources}个部委采集成功")
    elif active_sources >= 2:
        score += 15
        signals.append(f"⚠️ {active_sources}个部委采集成功")
    else:
        score -= 10
        signals.append("❌ 部委采集失败")
    
    # cninfo全量扫描命中
    cninfo_hits = policy_data.get('cninfo_hits', 0)
    if cninfo_hits >= 50:
        score += 30
        signals.append(f"✅ cninfo扫描命中{cninfo_hits}条")
    elif cninfo_hits >= 20:
        score += 20
        signals.append(f"⚠️ cninfo扫描命中{cninfo_hits}条")
    elif cninfo_hits >= 5:
        score += 10
        signals.append(f"⚠️ cninfo扫描命中{cninfo_hits}条(偏低)")
    else:
        score -= 10
        signals.append("❌ cninfo扫描无命中")
    
    # 扫描错误率
    errors = policy_data.get('scan_errors', 0)
    if errors > 10:
        score -= 10
        signals.append(f"⚠️ 扫描错误{errors}处")
    
    return min(100, max(0, score)), signals


# ═══════════════════════════════════════════════════
#  v5.0: 国家队面维度 (National Team Dimension)
# ═══════════════════════════════════════════════════

def load_national_team_data():
    """
    从 cninfo 全量扫描结果中提取国家队资本动向
    返回：dict {
        'hits': list of {code, name, title, date, action_type},
        'action_counts': dict,  # 减持/增持/权益变动计数
        'total_hits': int,
    }
    """
    result = {
        'hits': [],
        'action_counts': {'减持': 0, '增持': 0, '权益变动': 0, '其他': 0},
        'total_hits': 0,
    }
    
    if not os.path.exists(CN_TRACKER_DONE):
        return result
    
    try:
        with open(CN_TRACKER_DONE, encoding='utf-8') as f:
            meta = json.load(f)
        
        # cninfo扫描命中详情（前20条）
        hits = meta.get('national_hits_detail', [])
        for item in hits:
            # 哨兵数据格式可能是列表或字典，统一处理
            if isinstance(item, list) and len(item) >= 5:
                code, name, title, ts, dt = item[0], item[1], item[2], item[3], item[4]
            elif isinstance(item, dict):
                code = item.get('code', '')
                name = item.get('name', '')
                title = item.get('title', '')
                dt = item.get('date', '')
            else:
                continue
        
            # 判断动作类型（扩展关键词覆盖）
            action_type = '其他'
            if '减持' in title:
                action_type = '减持'
                result['action_counts']['减持'] += 1
            elif '增持' in title:
                action_type = '增持'
                result['action_counts']['增持'] += 1
            elif '权益变动' in title or '股份变动' in title or '比例变动' in title or '持股' in title:
                action_type = '权益变动'
                result['action_counts']['权益变动'] += 1
            else:
                result['action_counts']['其他'] += 1
        
            result['hits'].append({
                'code': code,
                'name': name,
                'title': title,
                'date': dt,
                'action_type': action_type,
            })
        
        result['total_hits'] = len(result['hits'])
        
        return result
    
    except Exception:
        return result


def calc_national_team_score(nt_data):
    """
    国家队面评分 (0-100分)
    
    评分逻辑：
    - 减持信号 (负面)：大基金/汇金/证金减持 = -20~0
    - 增持信号 (正面)：大基金/汇金/证金增持 = +20~100
    - 权益变动 (中性)：需看具体方向 = 0~50
    - 公告数量 (基础分)：公告越多说明国家队活跃 = +10~30
    
    返回：(score, signals)
    """
    score = 50
    signals = []
    
    action_counts = nt_data.get('action_counts', {})
    hits = nt_data.get('hits', [])
    
    # 减持信号（负面）
    reduce_count = action_counts.get('减持', 0)
    if reduce_count > 0:
        score -= reduce_count * 15
        signals.append(f"🔴 减持{reduce_count}次(负面信号)")
    
    # 增持信号（正面）
    increase_count = action_counts.get('增持', 0)
    if increase_count > 0:
        score += increase_count * 20
        signals.append(f"🟢 增持{increase_count}次(正面信号)")
    
    # 权益变动（中性，需看方向）
    change_count = action_counts.get('权益变动', 0)
    if change_count > 0:
        score += change_count * 5
        signals.append(f"⚪ 权益变动{change_count}次(待核方向)")
    
    # 公告数量（基础分）
    total_hits = len(hits)
    if total_hits >= 20:
        score += 20
        signals.append(f"✅ 公告活跃({total_hits}条)")
    elif total_hits >= 10:
        score += 10
        signals.append(f"⚠️ 公告中等({total_hits}条)")
    elif total_hits >= 5:
        score += 5
        signals.append(f"⚠️ 公告偏低({total_hits}条)")
    else:
        score -= 10
        signals.append("❌ 公告稀少(国家队沉寂)")
    
    return min(100, max(0, score)), signals

