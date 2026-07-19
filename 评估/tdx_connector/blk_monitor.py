#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通达信 blk 文件监控脚本 — 只读，不修改通达信任何文件

工作流程：
1. 读取 D:\TDX\T0002\blocknew\ 下的 blk 文件
2. 解析股票代码
3. 去重检查（tracked_YYYYMMDD.json）
4. 对新代码调用评估中心
5. 推送 Telegram

轮询间隔：盘中 2 分钟，其他时段 10 分钟，非交易时间暂停
"""

import os
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# === 配置 ===
TDX_BLK_DIR = Path(r"D:\TDX\T0002\blocknew")
MONITOR_FILES = [".blk", "tjg.blk"]  # 汇总文件
TRACKED_DIR = Path(__file__).parent  # tracked_YYYYMMDD.json 存储位置
EVAL_SCRIPT = Path(r"D:\Hermes\评估中心\tools\eval_smart.py")
PYTHON_PATH = "C:\Python314\python.exe"

# === 去重文件操作 ===
def get_tracked_file() -> Path:
    """获取当天去重文件路径"""
    today = datetime.now().strftime("%Y%m%d")
    return TRACKED_DIR / f"tracked_{today}.json"

def load_tracked() -> dict:
    """加载去重记录"""
    tracked_file = get_tracked_file()
    if tracked_file.exists():
        try:
            with open(tracked_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_tracked(tracked: dict):
    """保存去重记录"""
    tracked_file = get_tracked_file()
    with open(tracked_file, "w", encoding="utf-8") as f:
        json.dump(tracked, f, ensure_ascii=False, indent=2)

def is_already_tracked(code: str, tracked: dict) -> bool:
    """检查股票是否已追踪"""
    return code in tracked

def mark_tracked(code: str, tracked: dict, condition: str):
    """标记股票为已追踪"""
    tracked[code] = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "condition": condition,
        "status": "analyzed"
    }
    save_tracked(tracked)

# === blk 文件解析 ===
def parse_blk_file(blk_path: Path) -> list:
    """解析 blk 文件，返回股票代码列表"""
    if not blk_path.exists():
        return []
    
    try:
        content = blk_path.read_text(encoding="gbk", errors="ignore").strip()
        if not content:
            return []
        codes = [line.strip() for line in content.split("\r\n") if line.strip() and len(line.strip()) == 6]
        return codes
    except Exception as e:
        print(f"[WARN] 解析 blk 文件失败 {blk_path}: {e}")
        return []

def get_all_codes() -> list:
    """获取所有 blk 文件中的股票代码（去重）"""
    all_codes = set()
    for fname in MONITOR_FILES:
        blk_path = TDX_BLK_DIR / fname
        codes = parse_blk_file(blk_path)
        all_codes.update(codes)
    return sorted(all_codes)

def get_condition_name(blk_path: Path) -> str:
    """根据 blk 文件名获取条件名称"""
    return blk_path.stem

# === 评估中心调用 ===
def run_eval(code: str) -> str:
    """调用评估中心分析股票"""
    try:
        result = subprocess.run(
            [PYTHON_PATH, str(EVAL_SCRIPT), code],
            capture_output=True,
            text=True,
            timeout=120
        )
        return result.stdout if result.returncode == 0 else result.stderr
    except Exception as e:
        return f"[ERROR] 评估失败: {e}"

# === 主监控逻辑 ===
def check_and_notify():
    """检查 blk 文件并通知新预警"""
    tracked = load_tracked()
    new_codes = []
    
    # 获取所有代码
    all_codes = get_all_codes()
    
    # 找出新代码
    for code in all_codes:
        if not is_already_tracked(code, tracked):
            new_codes.append(code)
    
    if not new_codes:
        print("[INFO] 无新预警")
        return
    
    # 处理新预警
    for code in new_codes:
        print(f"[ALERT] 新预警: {code}")
        
        # 标记为已追踪
        mark_tracked(code, tracked, "盘中预警")
        
        # 调用评估中心
        eval_result = run_eval(code)
        
        # 推送 Telegram（通过 hermes send 或直接写入推送队列）
        send_to_telegram(code, eval_result)

def send_to_telegram(code: str, eval_result: str):
    """推送评估结果到 Telegram"""
    # 方法1: 写入推送队列文件，由 cron 读取并推送
    queue_dir = Path(__file__).parent / "telegram_queue"
    queue_dir.mkdir(exist_ok=True)
    
    msg_file = queue_dir / f"{code}_{datetime.now().strftime('%H%M%S')}.txt"
    with open(msg_file, "w", encoding="utf-8") as f:
        f.write(f"# 🚨 盘中预警\n\n")
        f.write(f"**股票代码**: {code}\n")
        f.write(f"**预警时间**: {datetime.now().strftime('%H:%M:%S')}\n")
        f.write(f"\n{eval_result}\n")
    print(f"[PUSH] 已写入推送队列: {msg_file}")

# === 轮询主循环 ===
def run_monitor():
    """监控主循环"""
    print(f"[START] blk 监控开始 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[INFO] 监控目录: {TDX_BLK_DIR}")
    print(f"[INFO] 监控文件: {MONITOR_FILES}")
    
    # 检查是否在交易时间
    now = datetime.now()
    if not is_trading_time(now):
        print("[SKIP] 非交易时间，跳过监控")
        return
    
    # 执行一次检查
    check_and_notify()
    
    print("[DONE] 监控完成")

def is_trading_time(now: datetime) -> bool:
    """判断是否在交易时间"""
    hour = now.hour
    minute = now.minute
    time = hour * 60 + minute
    
    # 交易时间: 09:00-15:00
    return 9 * 60 <= time <= 15 * 60

if __name__ == "__main__":
    run_monitor()
