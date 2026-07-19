#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美国经济软着陆监控 — cron 包装器
cron 调用此脚本，输出结果推送 Telegram
"""
import sys, os

SCRIPT = r"D:\Hermes\评估中心\tools\us_macro_monitor.py"
PYTHON = r"C:\Python314\python.exe"

# 设置环境变量（从 .env 读取）
ENV_FILE = r"D:\Hermes\评估中心\.env"
if os.path.exists(ENV_FILE):
    for line in open(ENV_FILE, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()

os.system(f'"{PYTHON}" "{SCRIPT}"')
