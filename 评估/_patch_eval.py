#!/usr/bin/env python3
"""Modify eval_smart.py: add 涨停 marking, chip section, stop-loss section"""

FPATH = r"D:\Hermes\评估中心\tools\eval_smart.py"

with open(FPATH, "r", encoding="utf-8") as f:
    lines = f.readlines()

print(f"Read {len(lines)} lines")

# 1. Find the main entry marker
insert_at = None
for i, l in enumerate(lines):
    if "主入口" in l and l.strip().startswith("#"):
        insert_at = i
        print(f"Found main entry at line {i}")
        break

if insert_at is None:
    print("ERROR: Main entry not found!")
    exit(1)

# 2. New functions to add (as raw strings to avoid escaping hell)
chip_fn_code = """\n
def _format_chip_section(results):
    \"\"\"筹码面分析：股东户数变化趋势\"\"\"
    md = \"\\n---\\n\\n## \\U0001f4ca 筹码面分析\\n\\n\"
    md += \"> 股东户数变化趋势判断筹码集中度\\n\\n\"
    md += \"| 股票 | 股东户数 | 变化% | 趋势 | 判断 |\\n\"
    md += \"|------|----------|-------|------|------|\\n\"
    for r in results:
        code = r.get('code', '')
        if not code:
            continue
        holder = r.get('holder_data', {})
        if not holder:
            try:
                h = pro.stk_holdernumber(ts_code=code, start_date='20250101', end_date=datetime.now().strftime('%Y%m%d'))
                if h is not None and not h.empty:
                    h = h.sort_values('ann_date', ascending=False)
                    holder = {'count': int(h.iloc[0].get('holder_num', 0)),
                              'change_pct': float(h.iloc[0].get('change_pct', 0)) if len(h) > 1 else 0}
                    r['holder_data'] = holder
            except:
                pass
        if not holder:
            md += f\"| {r.get('name', '?')} | — | — | — | 无数据 |\\n\"
            continue
        cnt = holder.get('count', 0)
        chg = holder.get('change_pct', 0)
        if chg > 8:
            trend = \"\\U0001f4c9分散\"; judge = \"筹码发散，主力出货\\u26a0\\ufe0f\"
        elif chg > 3:
            trend = \"\\u27a1\\ufe0f略分散\"; judge = \"筹码略发散，正常波动\"
        elif chg > -3:
            trend = \"\\u27a1\\ufe0f稳定\"; judge = \"筹码稳定，中性\"
        elif chg > -8:
            trend = \"\\U0001f4c8集中\"; judge = \"筹码集中，温和吸筹\\U0001f48e\"
        else:
            trend = \"\\U0001f4c8大幅集中\"; judge = \"筹码迅速集中，主力扫货\\U0001f525\"
        md += f\"| {r.get('name', '?')} | {cnt:,} | {chg:+.1f}% | {trend} | {judge} |\\n\"
    return md


def _format_stop_loss_section(results):
    \"\"\"T+1分层止损 + 盈亏比/目标价\"\"\"
    md = \"\\n---\\n\\n## \\U0001f6e1\\ufe0f T+1分层止损与盈亏比\\n\\n\"
    md += \"| 股票 | 现价 | 目标价 | 首日-12% | 次日ATR | 常态-8% | 盈亏比 |\\n\"
    md += \"|------|------|--------|----------|---------|---------|--------|\\n\"
    for r in results:
        code = r.get('code', '')
        name = r.get('name', '?')
        q = r.get('tencent', {})
        price = q.get('price', 0)
        if price <= 0:
            md += f\"| {name} | — | — | — | — | — | — |\\n\"
            continue
        atr = price * 0.05
        try:
            d = pro.daily(ts_code=code, start_date='20240601', end_date=datetime.now().strftime('%Y%m%d'))
            if d is not None and not d.empty:
                d = d.sort_values('trade_date').reset_index(drop=True)
                d['tr'] = np.maximum(d['high'] - d['low'], np.maximum(abs(d['high'] - d['close'].shift(1)), abs(d['low'] - d['close'].shift(1))))
                atr = float(d['tr'].tail(20).mean())
        except:
            pass
        if atr <= 0: atr = price * 0.05
        stop_d1 = round(price * 0.88, 2)
        stop_atr = round(price - atr * 1.5, 2)
        stop_normal = round(price * 0.92, 2)
        target = round(price + atr * 2.5, 2)
        rr = round((target - price) / (price - stop_normal), 1) if price > stop_normal else 0
        lu = q.get('limit_up', 0)
        if lu > 0 and price >= lu * 0.995:
            md += f\"| {name} \\U0001f6a8 | \\u00a5{price:.2f} | \\u00a5{target:.2f} | \\u00a5{stop_d1:.2f} | \\u00a5{stop_atr:.2f} | \\u00a5{stop_normal:.2f} | \\U0001f6ab涨停 |\\n\"
            continue
        md += f\"| {name} | \\u00a5{price:.2f} | \\u00a5{target:.2f} | \\u00a5{stop_d1:.2f} | \\u00a5{stop_atr:.2f} | \\u00a5{stop_normal:.2f} | {rr}:1 |\\n\"
    return md
"""

new_fn_lines = chip_fn_code.split("\n")
lines[insert_at:insert_at] = [l + "\n" for l in new_fn_lines]
print(f"After insert: {len(lines)} lines")

# 3. Modify 涨停 fallback
target_old = 'md += "> 注意: 八维度基础评估模块因涨停封死无法给出有效分数\\\\n\\\\n"'
for i, l in enumerate(lines):
    if 'md += "> 注意: 八维度基础评估模块因涨停封死无法给出有效分数' in l:
        lines[i] = '        md += "> ⚠️ 以下标的涨停封死，已纳入全维度评估并标记\\\\n\\\\n"\n'
        limit_table = """        # 涨停识别速览表
        limit_names = [r.get("name", "?") for r in results if r.get("tencent", {}).get("limit_up", 0) > 0 and r.get("tencent", {}).get("price", 0) >= r.get("tencent", {}).get("limit_up", 0) * 0.995]
        if limit_names:
            md += f"🚨 **涨停封死**: {\\", \\".join(limit_names)}\\\\n\\\\n"
        md += "### 📊 评分速览（含涨停标的）\\\\n\\\\n"
        md += "| 股票 | 状态 | 现价 | 涨跌% | 技术 | 资金 | 情绪 | 基础 | 板块 | 热度 |\\\\n"
        md += "|------|------|------|-------|------|------|------|------|------|------|\\\\n"
        for r in results:
            q = r.get("tencent", {})
            lu = q.get("limit_up", 0)
            pct, price = q.get("pct_chg", 0), q.get("price", 0)
            status = "🚨" if (lu > 0 and price >= lu * 0.995) else "✅"
            sc = r.get("scores", {})
            md += f"| {r.get("name", "?")} | {status} | ¥{price:.2f} | {pct:+.2f}% | {sc.get("tech", "—")} | {sc.get("capital", "—")} | {sc.get("sentiment", "—")} | {sc.get("fundamental", "—")} | {sc.get("sector", "—")} | {sc.get("heat", "—")} |\\\\n"
"""
        limit_lines = limit_table.split("\n")
        lines[i+1:i+1] = [l + "\n" for l in limit_lines]
        print(f"Modified 涨停 at line {i}")
        break

# 4. Add calls to new sections before save
for i, l in enumerate(lines):
    if "生成时间" in l and "datetime.now" in l:
        adds = [
            '    # 新增：筹码面 + T+1止损\n',
            '    if verbose: print("筹码面分析...")\n',
            '    md += _format_chip_section(results)\n',
            '    if verbose: print("T+1分层止损与盈亏比...")\n',
            '    md += _format_stop_loss_section(results)\n',
        ]
        lines[i:i] = adds
        print(f"Added sections before line {i}")
        break

# Write back
with open(FPATH, "w", encoding="utf-8") as f:
    f.writelines(lines)
print(f"Done! {len(lines)} lines")