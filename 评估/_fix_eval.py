#!/usr/bin/env python3
"""Fix eval_smart.py - clean patch with proper escaping"""
import shutil, ast

src = r"D:\Hermes\评估中心\versions\v5.0_20260707\eval_smart.py"
dst = r"D:\Hermes\评估中心\tools\eval_smart.py"
shutil.copy2(src, dst)

with open(dst, "r", encoding="utf-8") as f:
    lines = f.readlines()
print(f"Restored: {len(lines)} lines")

# Find insertion point
insert_at = None
for i, l in enumerate(lines):
    if l.strip().startswith("#") and "主入口" in l:
        insert_at = i
        break
if insert_at is None:
    print("ERROR: insert point not found")
    exit(1)
print(f"Insert at line {insert_at}")

# New functions (raw strings - no escaping issues)
new_funcs = '''
def _format_chip_section(results):
    md = "\\n---\\n\\n## \\U0001f4ca 筹码面分析\\n\\n"
    md += "> 股东户数变化趋势判断筹码集中度\\n\\n"
    md += "| 股票 | 股东户数 | 变化% | 趋势 | 判断 |\\n"
    md += "|------|----------|-------|------|------|\\n"
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
            md += f"| {r.get('name', '?')} | — | — | — | 无数据 |\\n"
            continue
        cnt, chg = holder["count"], holder["change_pct"]
        if chg > 8: t, j = "\\U0001f4c9分散", "筹码发散主力出货\\u26a0\\ufe0f"
        elif chg > 3: t, j = "\\u27a1\\ufe0f略分散", "筹码略发散正常波动"
        elif chg > -3: t, j = "\\u27a1\\ufe0f稳定", "筹码稳定中性"
        elif chg > -8: t, j = "\\U0001f4c8集中", "筹码集中温和吸筹\\U0001f48e"
        else: t, j = "\\U0001f4c8大幅集中", "筹码迅速集中主力扫货\\U0001f525"
        md += f"| {r.get('name', '?')} | {cnt:,} | {chg:+.1f}% | {t} | {j} |\\n"
    return md

def _format_stop_loss_section(results):
    md = "\\n---\\n\\n## \\U0001f6e1\\ufe0f T+1分层止损与盈亏比\\n\\n"
    md += "| 股票 | 现价 | 目标价 | 首日-12% | 次日ATR | 常态-8% | 盈亏比 |\\n"
    md += "|------|------|--------|----------|---------|---------|--------|\\n"
    for r in results:
        code, name = r.get("code", ""), r.get("name", "?")
        q = r.get("tencent", {})
        price = q.get("price", 0)
        if price <= 0:
            md += f"| {name} | — | — | — | — | — | — |\\n"
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
            md += f"| {name} \\U0001f6a8 | \\u00a5{price:.2f} | \\u00a5{tgt:.2f} | \\u00a5{sd1:.2f} | \\u00a5{satr:.2f} | \\u00a5{sn:.2f} | \\U0001f6ab涨停 |\\n"
            continue
        md += f"| {name} | \\u00a5{price:.2f} | \\u00a5{tgt:.2f} | \\u00a5{sd1:.2f} | \\u00a5{satr:.2f} | \\u00a5{sn:.2f} | {rr}:1 |\\n"
    return md
'''

# Split and insert
new_lines = new_funcs.splitlines(keepends=True)
lines[insert_at:insert_at] = new_lines
print(f"After insert: {len(lines)} lines")

# Fix 涨停 fallback
old_marker = 'md += "> 注意: 八维度基础评估模块因涨停封死无法给出有效分数\\\\n\\\\n"'
found = False
for i, l in enumerate(lines):
    if old_marker in l or 'md += "> 注意: 八维度基础评估模块因涨停封死' in l:
        lines[i] = '        md += "> ⚠️ 以下标的涨停封死，已纳入全维度评估并标记\\\\n\\\\n"\n'
        # Insert after this line
        table_block = [
            "        limit_names = [r.get('name', '?') for r in results if r.get('tencent', {}).get('limit_up', 0) > 0 and r.get('tencent', {}).get('price', 0) >= r.get('tencent', {}).get('limit_up', 0) * 0.995]\n",
            "        if limit_names:\n",
            "            md += f\"\\U0001f6a8 **涨停封死**: {', '.join(limit_names)}\\\\n\\\\n\"\n",
            "            md += '### \\U0001f4ca 评分速览（含涨停标的）\\\\n\\\\n'\n",
            "            md += '| 股票 | 状态 | 现价 | 涨跌% | 技术 | 资金 | 情绪 | 基础 | 板块 | 热度 |\\\\n'\n",
            "            md += '|------|------|------|-------|------|------|------|------|------|------|\\\\n'\n",
            "            for r in results:\n",
            "                lu = r.get('tencent', {}).get('limit_up', 0)\n",
            "                pct = r.get('tencent', {}).get('pct_chg', 0)\n",
            "                price = r.get('tencent', {}).get('price', 0)\n",
            "                status = '\\U0001f6a8' if (lu > 0 and price >= lu * 0.995) else '\\u2705'\n",
            "                sc = r.get('scores', {})\n",
            "                md += f\"| {r.get('name', '?')} | {status} | \\\\u00a5{price:.2f} | {pct:+.2f}% | {sc.get('tech', '\\u2014')} | {sc.get('capital', '\\u2014')} | {sc.get('sentiment', '\\u2014')} | {sc.get('fundamental', '\\u2014')} | {sc.get('sector', '\\u2014')} | {sc.get('heat', '\\u2014')} |\\\\n\"\n",
        ]
        lines[i+1:i+1] = table_block
        found = True
        print(f"Fixed 涨停 at line {i}")
        break
if not found:
    print("WARNING: 涨停 marker not found, trying alternative search...")
    for i, l in enumerate(lines):
        if '涨停封死' in l and 'md +=' in l:
            print(f"  Found at {i}: {l.rstrip()[:80]}")

# Add new section calls
for i, l in enumerate(lines):
    if "生成时间" in l and "datetime.now" in l:
        add = [
            "    if verbose: print('筹码面分析...')\n",
            "    md += _format_chip_section(results)\n",
            "    if verbose: print('T+1分层止损与盈亏比...')\n",
            "    md += _format_stop_loss_section(results)\n",
        ]
        lines[i:i] = add
        print(f"Added section calls before line {i}")
        break

# Write
with open(dst, "w", encoding="utf-8") as f:
    f.writelines(lines)

# Verify
try:
    ast.parse(open(dst, encoding="utf-8").read())
    print("SYNTAX OK!")
except SyntaxError as e:
    err_lines = open(dst, encoding="utf-8").read().splitlines()
    print(f"Line {e.lineno}: {e.msg}")
    if e.text: print(f"  {repr(e.text[:100])}")
    for j in range(max(0, e.lineno-3), min(len(err_lines), e.lineno+2)):
        print(f"  {j}: {repr(err_lines[j][:120])}")