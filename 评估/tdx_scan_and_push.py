#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tdx_scan_and_push.py — 综合评估+因子+追踪+推送 一站式入口

每日调度（cron no_agent）:
  cd D:/Hermes/评估中心 && /c/Python314/python tools/tdx_scan_and_push.py

流程:
  1. 数据保鲜检查 → 自动同步通达信最新数据
  2. 运行智能评估（20只标的）
  3. 运行因子引擎（16个扩展因子）
  4. 运行追踪模块（价格扫描）
  5. 推送至 Telegram（摘要+4份完整报告）
"""
import os, sys, datetime, subprocess

WORK_DIR = r"D:\Hermes\评估中心"
TOOLS_DIR = os.path.join(WORK_DIR, "tools")
PYTHON = r"C:\Python314\python"


def run_script(name, args=""):
    """运行tools目录下的脚本"""
    cmd = f'cd "{WORK_DIR}" && "{PYTHON}" tools/{name} {args}'
    r = subprocess.run(cmd, shell=True, capture_output=True,
                       text=True, encoding="utf-8", timeout=600)
    out = r.stdout[-300:] if r.stdout else ""
    err = r.stderr[-200:] if r.stderr else ""
    return r.returncode, out, err


def main():
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*60}")
    print(f"📡 综合报告流水线 — {now}")
    print(f"{'='*60}\n")

    # 1. 数据保鲜检查
    print("🔍 [1/4] 数据新鲜度检查...")
    rc, out, err = run_script("tdx_data_sync.py", "--check")
    print(out if out else "  (快速检查)")
    if err: print(f"  ⚠ {err}")

    # 2. 跑智能评估
    print("\n📊 [2/4] 20只标的评估...")
    rc, out, err = run_script("eval_smart.py", '--stocks "甘咨询,四方科技,杭州园林,中远通,当虹科技,高凌信息,华勤技术,深信服,大恒科技,山东墨龙,瑞芯微,沐曦股份,四环生物,昆仑万维,利扬芯片,中国卫星,同益中,亚联机械,贵绳股份,高德红外"')
    if rc != 0: print(f"  ⚠ 评估部分失败 rc={rc}")

    # 3. 跑因子引擎
    print("\n🧮 [3/4] 因子引擎计算...")
    rc, out, err = run_script("factor_engine.py")
    print(out if out else "")
    if rc == 0:
        rc2, out2, _ = run_script("factor_reporter.py")
        print(out2 if out2 else "")

    # 4. 跑追踪
    print("\n📡 [3/4] 追踪扫描...")
    rc, out, err = run_script("tdx_tracker.py")
    print(out if out else "")

    # 5. 推送全部
    print("\n📤 [4/4] 推送至 Telegram...")
    rc, out, err = run_script("push_all_reports.py")
    print(out if out else "")
    if err: print(f"  ⚠ {err}")

    print(f"\n✅ 全部完成 — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()