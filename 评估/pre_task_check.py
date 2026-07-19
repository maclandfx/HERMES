#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务前检查脚本 — 从failure_case和best_solution_library中匹配相关教训和方案

用法:
    python pre_task_check.py "周线分析"
    python pre_task_check.py "研报推送"
    python pre_task_check.py "系统环境自检"

输出: 匹配到的教训/方案列表（Markdown格式）
"""

import sys, re, pathlib
from datetime import datetime

MEMORY_DIR = pathlib.Path(r"C:\Users\Admin\AppData\Local\hermes\agent-memory")
FAILED_FILE = MEMORY_DIR / "failure_case.md"
BEST_FILE = MEMORY_DIR / "best_solution_library.md"


def load_file(p):
    """读取文件内容，不存在则返回空字符串"""
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except Exception as e:
        return f"# 读取失败: {e}"


def extract_cases(content):
    """从failure_case.md中提取案例"""
    cases = []
    # 匹配 ## 案例 N: ...
    pattern = r'## 案例 (\d+)[：:] *(.+?)(?=## 案例|$)'
    for match in re.finditer(pattern, content, re.DOTALL):
        num = match.group(1)
        title = match.group(2).strip().split('\n')[0].strip()
        cases.append({"num": num, "title": title, "content": match.group(0)})
    return cases


def extract_solutions(content):
    """从best_solution_library.md中提取方案"""
    solutions = []
    pattern = r'## 方案 (\d+)[：:] (.+?)(?=## 方案|$)'
    for match in re.finditer(pattern, content, re.DOTALL):
        num = match.group(1)
        title = match.group(2).strip()
        solutions.append({"num": num, "title": title, "content": match.group(0)})
    return solutions


def match_by_keywords(task_desc, cases, solutions):
    """根据任务描述关键词匹配相关教训和方案"""
    # 预定义的关键映射：关键词 → 要搜索的英文/中文关键词列表
    keyword_map = {
        "cron": ["cron", "cronjob", "repeat", "调度"],
        "数据": ["数据", "数据源", "yfinance", "akshare", "tushare", "daily"],
        "推送": ["推送", "telegram", "tg", "report"],
        "研报": ["研报", "报告", "分析", "摘要"],
        "评估": ["评估", "评分", "因子", "权重"],
        "系统": ["系统", "环境", "脚本", "工具", "健康"],
        "错误": ["失败", "错误", "bug", "修复", "异常"],
        "审计": ["审计", "review", "评审", "检查"],
        "周线": ["周线", "weekly", "日周"],
    }
    
    matched_keywords = []
    # 提取任务描述中的每个词，检查是否包含关键词
    task_words = re.findall(r'[\u4e00-\u9fa5]+', task_desc)
    task_words.extend(re.findall(r'[a-zA-Z][a-zA-Z0-9_]+', task_desc))  # 英文词
    
    for kw_key, aliases in keyword_map.items():
        # 检查是否有任何任务词包含关键词key
        for word in task_words:
            if kw_key in word or word in kw_key:
                matched_keywords.extend(aliases)
                break
    # 如果无匹配，用任务描述本身作为关键词
    if not matched_keywords:
        matched_keywords = task_words if task_words else [task_desc]
    
    matched_cases = []
    for case in cases:
        content_lower = case["content"].lower()
        for kw in matched_keywords:
            if kw.lower() in content_lower:
                matched_cases.append(case)
                break
    
    matched_solutions = []
    for sol in solutions:
        content_lower = sol["content"].lower()
        for kw in matched_keywords:
            if kw.lower() in content_lower:
                matched_solutions.append(sol)
                break
    
    return matched_cases, matched_solutions


def format_output(task_desc, cases, solutions, matched_cases, matched_solutions):
    """格式化输出"""
    lines = []
    lines.append(f"# 📋 任务前检查报告 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"")
    lines.append(f"## 任务描述")
    lines.append(f"{task_desc}")
    lines.append(f"")
    lines.append(f"## 匹配到的教训 ({len(matched_cases)}条)")
    if matched_cases:
        for case in matched_cases:
            # 只输出案例标题和关键内容（前300字符）
            snippet = case["content"][:300]
            lines.append(f"- 📌 案例{case['num']}: {case['title']}")
            lines.append(f"  ```{snippet}...```\n")
    else:
        lines.append("  ✅ 无匹配教训")
    
    lines.append(f"## 匹配到的方案 ({len(matched_solutions)}条)")
    if matched_solutions:
        for sol in matched_solutions:
            snippet = sol["content"][:300]
            lines.append(f"- 💡 方案{sol['num']}: {sol['title']}")
            lines.append(f"  ```{snippet}...```\n")
    else:
        lines.append("  ✅ 无匹配方案")
    
    lines.append(f"---")
    lines.append(f"📊 总计: 教训{len(matched_cases)}条, 方案{len(matched_solutions)}条")
    
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        task_desc = "默认任务"
    else:
        task_desc = " ".join(sys.argv[1:])
    
    # 读取文件
    failed_content = load_file(FAILED_FILE)
    best_content = load_file(BEST_FILE)
    
    # 提取案例和方案
    cases = extract_cases(failed_content)
    solutions = extract_solutions(best_content)
    
    # 匹配
    matched_cases, matched_solutions = match_by_keywords(task_desc, cases, solutions)
    
    # 输出
    output = format_output(task_desc, cases, solutions, matched_cases, matched_solutions)
    print(output)
    
    # 如果有匹配，输出简短提醒
    if matched_cases or matched_solutions:
        print(f"\n⚠️ 请阅读上述教训/方案后再执行任务")


if __name__ == "__main__":
    main()
