#!/usr/bin/env python3
"""Fix the 涨停 section in eval_smart.py - properly escape \\n"""
FPATH = r"D:\Hermes\评估中心\tools\eval_smart.py"

with open(FPATH, "r", encoding="utf-8") as f:
    content = f.read()

# The old block has literal newlines in md strings - WRONG
# Find the "⚠️ 以下标的涨停封死" line and fix all md += lines in this block
lines = content.split("\n")
fixed = []
in_block = False
for i, l in enumerate(lines):
    # Detect start of block
    if '⚠️ 以下标的涨停封死' in l:
        in_block = True
        # Fix the escaped newlines
        # The line currently has: md += "> ... \n\n"
        # It should have: md += "> ... \\n\\n"
        # Because the raw string \n in the python source means literal newline
        # We need \\n in the source to produce \n in the output
        fixed.append(l.replace('\\n', '\\\\n'))
        continue
    
    if in_block:
        if '追加扩展层' in l:
            in_block = False
            fixed.append(l)
            continue
        # Fix all md += lines that have literal newlines
        if 'md +=' in l and '\\n' in l:
            # Replace single \n with \\n
            # But be careful: the line may have other content
            # We want: "\\n" -> "\\\\n" in the Python source
            # Which means: '\n' -> '\\n' in the string
            fixed.append(l.replace('\\n', '\\\\n').replace('\\\\\\n', '\\\\n'))
        else:
            fixed.append(l)
    else:
        fixed.append(l)

# Also fix the new function sections (chip and stop-loss)
# Those also have escaped newlines
content_new = "\n".join(fixed)

# Now fix the new functions too - they have \n that should be \\n
# But the new functions were written by _patch_eval.py, let me check
# The chip and stop-loss functions use "\\n" for newlines - that's correct
# because they're in regular Python code, not in patch_eval.py

with open(FPATH, "w", encoding="utf-8") as f:
    f.write(content_new)

import ast
try:
    ast.parse(content_new)
    print("OK - syntax valid")
except SyntaxError as e:
    print(f"ERR line {e.lineno}: {e.msg}")
    # Show the problematic line
    err_lines = content_new.split("\n")
    if e.lineno:
        for j in range(max(0, e.lineno-2), min(len(err_lines), e.lineno+2)):
            print(f"  {j}: {repr(err_lines[j][:120])}")