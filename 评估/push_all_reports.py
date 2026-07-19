#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
push_all_reports.py — 全报告推送引擎

推送内容：
1. 📊 摘要消息（TOP 10 + 权重 + 行动指南）
2. 📄 完整评估报告（.md文件）
3. 📊 因子引擎日报（.md文件）
4. 📡 追踪报告（.md文件）

用法: python push_all_reports.py
"""
import os, sys, json, datetime, re, time, urllib.request

# ── 配置 ──
TOKEN = "8572871704:AAEFYo1h5IfqUS_5Sh621Mub39Z9yKD0GOM"
CHAT_ID = "8673372605"
PROXY = "127.0.0.1:7890"

WORK_DIR = r"D:\Hermes\评估中心"
TOOLS_DIR = os.path.join(WORK_DIR, "tools")
REPORT_DIR = os.path.join(WORK_DIR, "reports", "粗评")
TRACK_DIR = os.path.join(WORK_DIR, "reports", "追踪")
sys.path.insert(0, TOOLS_DIR)

MAX_MSG = 4000  # Telegram 单条消息上限
DELAY = 1.0     # 消息间隔秒数


def tg_send(text, parse_mode="Markdown"):
    """发送文本消息（含重试）"""
    proxy = urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
    opener = urllib.request.build_opener(proxy)
    chunks = []
    for i in range(0, len(text), MAX_MSG):
        chunks.append(text[i:i+MAX_MSG])
    for i, ch in enumerate(chunks):
        for attempt in range(3):
            try:
                data = json.dumps({
                    "chat_id": CHAT_ID, "text": ch,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True
                }).encode("utf-8")
                req = urllib.request.Request(
                    f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                    data=data, headers={"Content-Type": "application/json"}
                )
                opener.open(req, timeout=20)
                print(f"  ✅ 消息 {i+1}/{len(chunks)} 发送成功 ({len(ch)} chars)")
                break
            except Exception as e:
                if attempt < 2:
                    time.sleep(2)
                else:
                    print(f"  ❌ 消息 {i+1}/{len(chunks)} 发送失败: {e}")
        time.sleep(DELAY)


def tg_send_file(filepath, caption=""):
    """发送文件（sendDocument）"""
    if not os.path.exists(filepath):
        print(f"  ⚠️ 文件不存在: {filepath}")
        return False
    import http.client
    import mimetypes
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    fname = os.path.basename(filepath)
    with open(filepath, "rb") as f:
        fdata = f.read()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{CHAT_ID}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="document"; filename="{fname}"\r\n'
        f"Content-Type: text/markdown\r\n\r\n"
    ).encode("utf-8") + fdata + f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/sendDocument",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )
    proxy = urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
    opener = urllib.request.build_opener(proxy)
    try:
        resp = opener.open(req, timeout=30)
        result = json.loads(resp.read())
        print(f"  ✅ 文件 {fname} 发送成功 ({len(fdata)} bytes)")
        return True
    except Exception as e:
        print(f"  ❌ 文件 {fname} 发送失败: {e}")
        return False


def build_summary():
    """构建摘要消息"""
    now = datetime.datetime.now().strftime("%m月%d日 %H:%M")
    # 读取因子数据
    factors_path = os.path.join(TRACK_DIR, "factors_raw.json")
    factors = {}
    if os.path.exists(factors_path):
        with open(factors_path, "r", encoding="utf-8") as f:
            factors = json.load(f)

    watch_names = {
        "600118":"中国卫星","300418":"昆仑万维","600288":"大恒科技",
        "688135":"利扬芯片","688175":"高凌信息","603296":"华勤技术",
        "603893":"瑞芯微","688802":"沐曦股份","000518":"四环生物",
        "301516":"中远通","300454":"深信服","688722":"同益中",
        "688039":"当虹科技","001395":"亚联机械","600992":"贵绳股份",
        "300649":"杭州园林","002414":"高德红外","002490":"山东墨龙",
        "000779":"甘咨询","603339":"四方科技",
    }

    weights = {"A1_big_net_ratio":15,"A3_strength":13,"A2_consecutive_days":12,
               "A4_north_flow":10,"B4_rel_strength":10,"B1_divergence":8,
               "B3_gap":8,"B5_trend":8,"B2_limit_quality":5,"B6_volatility":5}

    scores = []
    for code, f in factors.items():
        if "error" in f: continue
        total = sum(f.get(k,50)*w for k,w in weights.items()) / sum(weights.values())
        scores.append((code, round(total,1), f))
    scores.sort(key=lambda x: x[1], reverse=True)

    lines = [
        f"# 📊 因子引擎日报 — {now}",
        "",
        f"**标的**: 20只 | **因子**: 16个",
        "",
        "## 🏆 TOP 10",
        "",
        "| # | 名称 | 综合分 | 主力因子 |",
        "|---|------|:------:|----------|",
    ]
    for i, (code, total, f_dict) in enumerate(scores[:10]):
        name = watch_names.get(code, code)
        top = sorted(f_dict.items(), key=lambda x: x[1] if isinstance(x[1],(int,float)) else 0, reverse=True)[:2]
        top_str = ", ".join([f"{k}({v:.0f})" for k,v in top if isinstance(v,(int,float))])
        lines.append(f"| {i+1} | {name} | {total} | {top_str} |")

    lines += [
        "",
        "## ⚖️ 权重排名",
        "",
        "| 因子 | 权重 | 说明 |",
        "|------|:----:|------|",
        "| A1大单净流入比 | 15% | 核心指标 |",
        "| A3主力资金强度 | 13% | 质量过滤 |",
        "| A2资金持续性 | 12% | 非一日游 |",
        "| A4北向变化 | 10% | 聪明钱 |",
        "| B4相对强弱 | 10% | α收益 |",
        "| B1量价背离 | 8% | 真假突破 |",
        "| B3跳空缺口 | 8% | 缺口质量 |",
        "| B5趋势强度 | 8% | 动量 |",
        "| B6年化波动率 | 5% | 风险修正(不参与评分) |",
        "| B2涨停质量 | 5% | 封板力度 |",
        "",
        "## 🎯 行动指南",
        "",
        "**买入条件**: 评估≥95分 + 资金面≥70 + 非涨停封死",
        "**止损**: -8%硬止损 | 首日T+0关注次日 | 次日ATR缓冲",
        "**仓位(波动率修正)**: 波动>50%仓位×0.5 | 波动35-50%×0.75 | 波动<20%标准",
        "**追击涨停**: 开板+资金面>70 → 开盘追; 3日不创新高 → 剔除",
        "",
        "— 自适应权重满5天自动调权 —",
        f"📎 以下附完整评估报告 + 因子报告 + 追踪报告",
    ]
    return "\n".join(lines)


def main():
    print(f"\n{'='*60}")
    print(f"📤 全报告推送引擎 — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    # 1. 发送摘要
    print("📋 生成摘要...")
    summary = build_summary()
    print(f"  摘要长度: {len(summary)} chars")
    print("📤 发送摘要...")
    tg_send(summary)

    # 2. 发送完整评估报告
    print("\n📄 查找评估报告...")
    today = datetime.datetime.now().strftime("%Y%m%d")
    eval_files = sorted([f for f in os.listdir(REPORT_DIR)
                         if today in f and f.endswith(".md") and "核心" in f],
                        key=lambda f: os.path.getmtime(os.path.join(REPORT_DIR, f)), reverse=True)
    if eval_files:
        fp = os.path.join(REPORT_DIR, eval_files[0])
        print(f"  📄 评估报告: {eval_files[0]}")
        tg_send_file(fp, caption=f"📄 完整评估报告: {eval_files[0]}")
    else:
        print("  ⚠️ 未找到今日评估报告")

    # 3. 发送因子报告
    print("\n📊 查找因子报告...")
    factor_report = os.path.join(TRACK_DIR, "factor_report_daily.md")
    if os.path.exists(factor_report):
        tg_send_file(factor_report, caption="📊 因子引擎日报")
    else:
        print("  ⚠️ 因子报告不存在")

    # 4. 发送追踪报告
    print("\n📡 查找追踪报告...")
    track_report = os.path.join(TRACK_DIR, "track_report_latest.md")
    if os.path.exists(track_report):
        tg_send_file(track_report, caption="📡 选股池追踪报告")
    else:
        print("  ⚠️ 追踪报告不存在")

    # 5. 发送原始因子数据
    print("\n📊 发送原始因子得分...")
    factors_raw = os.path.join(TRACK_DIR, "factors_raw.json")
    if os.path.exists(factors_raw):
        tg_send_file(factors_raw, caption="📊 原始因子得分数据 (JSON)")

    print(f"\n✅ 推送完成")


if __name__ == "__main__":
    main()