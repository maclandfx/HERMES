#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美国经济软着陆监控 — us_macro_monitor.py
每周运行，读取指标数据 → 评分 → 生成报告 → 推送 Telegram

数据输入方式：
1. 首选：手动填入 latest_data.json（可靠）
2. 备选：尝试从公开页面爬取（不保证稳定）

不依赖任何 API key，所有数据源均为公开可访问页面。
"""
import json, os, sys, time, re
from datetime import datetime, timedelta
from pathlib import Path
import urllib.request, urllib.error

# ===== 路径 =====
TOOLS_DIR = Path(__file__).parent
ROOT_DIR = TOOLS_DIR.parent
DATA_FILE = ROOT_DIR / "reports" / "us_macro" / "latest_data.json"
STATE_FILE = ROOT_DIR / "reports" / "us_macro" / ".monitor_state.json"
REPORT_DIR = ROOT_DIR / "reports" / "us_macro"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# ===== 代理 =====
PROXIES = {'http': 'http://127.0.0.1:7890', 'https': 'http://127.0.0.1:7890'}

# ===== 指标定义 =====
INDICATORS = [
    {
        "id": "cpi_core", "name": "核心CPI月环比", "freq": "月度",
        "source": "BLS", "threshold_good": 0.3, "threshold_bad": 0.6,
        "unit": "%", "direction": "down",
        "description": "核心CPI月环比，软着陆目标0.2-0.3%",
    },
    {
        "id": "pce_core", "name": "核心PCE月环比", "freq": "月度",
        "source": "BEA", "threshold_good": 0.3, "threshold_bad": 0.5,
        "unit": "%", "direction": "down",
        "description": "美联储核心PCE目标2%，月环比约0.17%",
    },
    {
        "id": "supercore", "name": "超级核心服务通胀", "freq": "月度",
        "source": "BLS", "threshold_good": 0.3, "threshold_bad": 0.5,
        "unit": "%", "direction": "down",
        "description": "剔除住房的核心服务通胀，反映工资-价格螺旋",
    },
    {
        "id": "gdp_qoq", "name": "GDP季环比年化", "freq": "季度",
        "source": "BEA", "threshold_good": -0.5, "threshold_bad": -1.0,
        "unit": "%", "direction": "up",
        "description": "软着陆：0~2%温和正增长，不出现连续负增长",
    },
    {
        "id": "unrate", "name": "失业率", "freq": "月度",
        "source": "BLS", "threshold_good": 4.8, "threshold_bad": 5.2,
        "unit": "%", "direction": "down",
        "description": "软着陆：缓升4.0-4.5%并企稳，不上冲5%+",
    },
    {
        "id": "payrolls", "name": "非农新增就业", "freq": "月度",
        "source": "BLS", "threshold_good": 30000, "threshold_bad": -50000,
        "unit": "千人", "direction": "up",
        "description": "软着陆：月增5-10万，供需平衡区",
    },
    {
        "id": "claims", "name": "初请失业金人数", "freq": "每周",
        "source": "DOL", "threshold_good": 270000, "threshold_bad": 350000,
        "unit": "人", "direction": "down",
        "description": "软着陆：维持在20-25万，未趋势性飙升",
    },
    {
        "id": "fed_rate", "name": "联邦基金利率", "freq": "月/季",
        "source": "FOMC", "threshold_good": 4.0, "threshold_bad": 5.25,
        "unit": "%", "direction": "down",
        "description": "软着陆：降至3.0-3.5%中性区间",
    },
    {
        "id": "yield_10y", "name": "10年期美债收益率", "freq": "每日",
        "source": "Treasury", "threshold_good": 4.2, "threshold_bad": 5.0,
        "unit": "%", "direction": "down",
        "description": "软着陆：3.5-4.2%震荡，不因衰退恐慌破3%",
    },
    {
        "id": "spread_hy", "name": "高收益债利差", "freq": "每日",
        "source": "ICE BofA", "threshold_good": 4.0, "threshold_bad": 6.0,
        "unit": "%", "direction": "down",
        "description": "软着陆：300-400bp内，未大幅走阔",
    },
    {
        "id": "djia", "name": "道琼斯指数", "freq": "每日",
        "source": "NYSE", "threshold_good": 0, "threshold_bad": 0,
        "unit": "点", "direction": "neutral",
        "description": "美股周期/小盘相对防御走强 = 增长仍在",
    },
    {
        "id": "nasdaq", "name": "纳斯达克指数", "freq": "每日",
        "source": "NASDAQ", "threshold_good": 0, "threshold_bad": 0,
        "unit": "点", "direction": "neutral",
        "description": "AI受益科技股延续强势",
    },
    {
        "id": "usd_index", "name": "美元指数DXY", "freq": "每日",
        "source": "ICE", "threshold_good": 103, "threshold_bad": 107,
        "unit": "点", "direction": "down",
        "description": "软着陆：高位震荡或温和下行，不暴跌",
    },
    {
        "id": "gold", "name": "黄金价格", "freq": "每日",
        "source": "COMEX", "threshold_good": 0, "threshold_bad": 0,
        "unit": "美元", "direction": "neutral",
        "description": "软着陆：避险溢价收缩，涨势趋缓",
    },
    {
        "id": "oil_wti", "name": "WTI原油", "freq": "每日",
        "source": "NYMEX", "threshold_good": 0, "threshold_bad": 0,
        "unit": "美元", "direction": "neutral",
        "description": "供需博弈",
    },
    {
        "id": "copper", "name": "铜期货", "freq": "每日",
        "source": "COMEX", "threshold_good": 0, "threshold_bad": 0,
        "unit": "美元/吨", "direction": "neutral",
        "description": "软着陆+AI基建：偏强",
    },
]

# ===== 数据加载 =====
def load_latest_data():
    """从 latest_data.json 加载用户手动填入的最新数据"""
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            return data
        except:
            pass
    return {}

# 宏观爬虫重试配置
_MACRO_SRC_RETRIES = 2       # 每个源的尝试次数
_MACRO_SRC_DELAY = 3         # 秒
_MACRO_SRC_TIMEOUT = 20      # 秒

def _scrape_once(url, parser, label):
    """对单个宏观数据源爬取，返回 (value_or_None, log_lines)。"""
    import ssl
    ctx = ssl.create_default_context()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    last_exc = None
    for attempt in range(_MACRO_SRC_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=_MACRO_SRC_TIMEOUT, context=ctx) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
            val = parser(html)
            return val, None
        except Exception as e:
            last_exc = e
            if attempt < _MACRO_SRC_RETRIES:
                print(f"  ⚠ {label} 失败(第{attempt+1}次): {e}，{ _MACRO_SRC_DELAY}s 后重试...")
                time.sleep(_MACRO_SRC_DELAY)
            else:
                return None, f"{label}: 全部{ _MACRO_SRC_RETRIES+1}次尝试失败 — {e}"
    return None, None


def try_scrape_us_economic_data():
    """尝试从公开页面爬取美国宏观经济数据（备选，带重试+失败日志）"""
    data = {}
    failures = []

    # 1. 初请失业金 — DOL
    def _parse_claims(html):
        m = re.search(r'Initial\s+Claims[:\s]*([0-9,]+)', html, re.IGNORECASE)
        return int(m.group(1).replace(",", "")) if m else None
    val, fail = _scrape_once(
        "https://www.dol.gov/agencies/eta/claims/Unemployment-Claims-Data",
        _parse_claims, "失业金(DOL)")
    if val is not None:
        data["claims"] = val
    elif fail:
        failures.append(fail)

    # 2. 10年期美债收益率 — Treasury
    def _parse_yield(html):
        m = re.search(r'10[- ]Year[^0-9]*([0-9]+\.[0-9]{2})', html, re.IGNORECASE)
        return float(m.group(1)) if m else None
    val, fail = _scrape_once(
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates",
        _parse_yield, "10年美债(Treasury)")
    if val is not None:
        data["yield_10y"] = val
    elif fail:
        failures.append(fail)

    # 汇总日志
    got = list(data.keys())
    if got:
        print(f"  📡 成功爬取: {', '.join(got)}")
    if failures:
        for f in failures:
            print(f"  ❌ {f}")
        # 写失败日志到状态目录，供人工排查
        try:
            log_path = REPORT_DIR / ".scrape_failures.log"
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(f"[{now}] " + " | ".join(failures) + "\n")
        except Exception:
            pass

    return data

# ===== 评分系统 =====
def score_indicator(ind, value):
    """
    对单个指标评分 0-100
    direction: 'down' = 值越低越好, 'up' = 越高越好, 'neutral' = 中性
    threshold_good: 软着陆理想阈值
    threshold_bad: 硬着陆/衰退阈值
    """
    if value is None:
        return 50, "无数据"
    
    try:
        value = float(value)
    except:
        return 50, "数据格式异常"
    
    if ind["direction"] == "neutral":
        return 50, "中性指标（观察用）"
    
    good = float(ind["threshold_good"])
    bad = float(ind["threshold_bad"])
    
    if ind["direction"] == "down":
        # 值越低越好（通胀、利率等）
        if value <= good:
            return 80, f"优秀 ({value}{ind['unit']} ≤ {good}{ind['unit']})"
        elif value <= (good + bad) / 2:
            return 60, f"中性 ({value}{ind['unit']} 在目标附近)"
        elif value <= bad:
            return 40, f"关注 ({value}{ind['unit']} 偏高)"
        else:
            return 20, f"警戒 ({value}{ind['unit']} 超过衰退阈值 {bad}{ind['unit']})"
    else:  # up
        # 值越高越好（就业等）
        if value >= good:
            return 80, f"优秀 ({value}{ind['unit']} ≥ {good}{ind['unit']})"
        elif value >= (good + bad) / 2:
            return 60, f"中性 ({value}{ind['unit']} 在目标附近)"
        elif value >= bad:
            return 40, f"关注 ({value}{ind['unit']} 偏低)"
        else:
            return 20, f"警戒 ({value}{ind['unit']} 低于衰退阈值 {bad}{ind['unit']})"

def calculate_landing_score(data, indicators):
    """
    计算软着陆综合评分
    各指标权重不同：
    - 通胀（CPI/PCE/超级核心）：权重35%
    - 增长（GDP/就业）：权重30%
    - 货币政策（利率/收益率）：权重15%
    - 金融市场（信用利差）：权重10%
    - 价格数据（失业金/失业率/非农）：权重10%
    """
    # 权重分类
    weights = {
        "inflation": 0.35,    # cpi_core, pce_core, supercore
        "growth": 0.30,       # gdp_qoq, payrolls
        "policy": 0.15,       # fed_rate, yield_10y
        "credit": 0.10,       # spread_hy
        "labor": 0.10,        # claims, unrate
    }
    
    category_scores = {"inflation": [], "growth": [], "policy": [], "credit": [], "labor": []}
    category_map = {
        "cpi_core": "inflation", "pce_core": "inflation", "supercore": "inflation",
        "gdp_qoq": "growth", "payrolls": "growth",
        "fed_rate": "policy", "yield_10y": "policy",
        "spread_hy": "credit",
        "claims": "labor", "unrate": "labor",
    }
    
    results = []
    for ind in indicators:
        iid = ind["id"]
        val = data.get(iid)
        score, reason = score_indicator(ind, val)
        cat = category_map.get(iid, "labor")
        category_scores[cat].append(score)
        
        results.append({
            "id": iid,
            "name": ind["name"],
            "value": val,
            "score": score,
            "reason": reason,
            "unit": ind["unit"],
            "direction": ind["direction"],
            "threshold_good": ind["threshold_good"],
            "threshold_bad": ind["threshold_bad"],
        })
    
    # 加权综合
    composite = 0
    for cat, scores in category_scores.items():
        if scores:
            avg = sum(scores) / len(scores)
            composite += weights[cat] * avg
    
    # 情景判断
    if composite >= 70:
        landing_type = "软着陆"
        color = "🟢"
        description = "通胀回落+增长维持+就业未崩，金发姑娘交易"
    elif composite >= 50:
        landing_type = "中性偏软"
        color = "🟡"
        description = "经济韧性仍在，但通胀/关税尾部风险未出清"
    elif composite >= 30:
        landing_type = "浅衰退"
        color = "🟠"
        description = "增长放缓+就业转弱，警惕类滞胀"
    else:
        landing_type = "硬着陆/衰退"
        color = "🔴"
        description = "通胀反弹或GDP连续负增长，衰退交易启动"
    
    return {
        "composite": round(composite, 1),
        "landing_type": landing_type,
        "color": color,
        "description": description,
        "results": results,
        "category_scores": {k: round(sum(v)/len(v), 1) if v else None 
                           for k, v in category_scores.items()},
    }

# ===== 报告生成 =====
def generate_report(score_result, now_str):
    """生成 Markdown 报告"""
    md = []
    md.append(f"# 🇺🇸 美国经济软着陆监控周报")
    md.append("")
    md.append(f"**报告日期**: {now_str}")
    md.append("")
    
    # 综合判断
    md.append("## 🎯 综合判断")
    md.append("")
    md.append(f"**软着陆评分**: **{score_result['composite']}**/100")
    md.append("")
    md.append(f"**情景判断**: {score_result['color']} {score_result['landing_type']}")
    md.append("")
    md.append(f"> {score_result['description']}")
    md.append("")
    
    # 分类得分
    md.append("### 各维度得分")
    md.append("")
    md.append("| 维度 | 得分 | 状态 |")
    md.append("|------|------|------|")
    for cat, label in [("inflation", "🔥 通胀"), ("growth", "📈 增长"), 
                       ("policy", "🏛️ 货币政策"), ("credit", "💰 信用"), 
                       ("labor", "👷 劳动力")]:
        s = score_result["category_scores"].get(cat, None)
        if s is not None:
            if s >= 70: status = "🟢"
            elif s >= 50: status = "🟡"
            elif s >= 30: status = "🟠"
            else: status = "🔴"
            md.append(f"| {label} | {s} | {status} |")
        else:
            md.append(f"| {label} | 无数据 | ⚪ |")
    md.append("")
    
    # 关键指标表
    md.append("## 📊 关键指标一览")
    md.append("")
    md.append("| 指标 | 最新值 | 软着陆目标 | 得分 | 状态 |")
    md.append("|------|--------|-----------|------|------|")
    for r in score_result["results"]:
        if r["direction"] == "neutral":
            md.append(f"| {r['name']} | {r['value']}{r['unit']} | 观察 | — | ⚪ |")
        else:
            good = r["threshold_good"]
            bad = r["threshold_bad"]
            val_str = f"{r['value']}{r['unit']}" if r['value'] is not None else "无"
            target = f"≤{good}{r['unit']}" if r["direction"] == "down" else f"≥{good}{r['unit']}"
            if r["score"] >= 70: status = "🟢"
            elif r["score"] >= 50: status = "🟡"
            elif r["score"] >= 30: status = "🟠"
            else: status = "🔴"
            md.append(f"| {r['name']} | {val_str} | {target} | {r['score']} | {status} |")
    md.append("")
    
    # 详细解读
    md.append("## 📋 详细解读")
    md.append("")
    for r in score_result["results"]:
        if r["score"] < 50 and r["direction"] != "neutral":
            md.append(f"- 🔴 **{r['name']}**: {r['reason']}")
        elif r["score"] >= 70 and r["direction"] != "neutral":
            md.append(f"- 🟢 **{r['name']}**: {r['reason']}")
    md.append("")
    
    # 资产配置暗示
    md.append("## 💡 资产配置暗示")
    md.append("")
    if score_result["landing_type"] == "软着陆":
        md.append("**情景**: 金发姑娘交易（经济稳+通胀降）")
        md.append("")
        md.append("| 资产 | 排序 | 逻辑 |")
        md.append("|------|------|------|")
        md.append("| 📈 股票 | #1 | Risk On，美股盈利企稳，科技股延续强势 |")
        md.append("| 🥇 商品 | #2 | 工业金属（铜）偏强，原油看供需博弈 |")
        md.append("| 🏦 短债 | #3 | 受益于已落地的降息 |")
        md.append("| 🏦 长债 | #4 | 长端收益率下行空间受限 |")
        md.append("| 💵 美元 | #5 | 温和走弱但不暴跌 |")
        md.append("")
        md.append("> **风格**: 周期股、小盘股、REITs 相对防御股走强")
        md.append("> **黄金**: 避险溢价收缩，涨势趋缓")
    elif score_result["landing_type"] == "硬着陆/衰退":
        md.append("**情景**: 衰退交易（赌降息）")
        md.append("")
        md.append("| 资产 | 排序 | 逻辑 |")
        md.append("|------|------|------|")
        md.append("| 🏦 长债 | #1 | 利率暴跌，长久期资本利得 |")
        md.append("| 🥇 黄金 | #2 | 避险+降息双驱动 |")
        md.append("| 🛡️ 防御股 | #3 | 公用事业、消费必需品 |")
        md.append("| 💵 美元 | #4 | 短期避险流入，中长期走弱 |")
        md.append("| 📉 股票 | #5 | 美股面临盈利下修压力 |")
        md.append("")
        md.append("> **黄金**: 避险溢价重新定价")
        md.append("> **小盘股**: 利率敏感，跌幅更大")
    else:
        md.append("**情景**: 过渡期，保持灵活配置")
        md.append("")
        md.append("> 观察通胀/就业数据变化，等待方向明确")
    md.append("")
    
    md.append("---")
    md.append("")
    md.append(f"*报告生成时间: {now_str}*")
    md.append("*数据源: 用户手动输入 / 公开页面爬取*")
    
    return "\n".join(md)

# ===== Telegram 推送 =====
def push_to_telegram(md_content):
    """推送报告到 Telegram"""
    bot_token = os.environ.get("TG_BOT_TOKEN", "")
    chat_id = os.environ.get("TG_CHAT_ID", "")
    
    if not bot_token or not chat_id:
        print("⚠️ 未设置 TG_BOT_TOKEN / TG_CHAT_ID，跳过推送")
        return False
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    # 分块推送（每块 ≤ 4000 字符）
    chunks = []
    lines = md_content.split("\n")
    current_chunk = []
    current_len = 0
    
    for line in lines:
        if current_len + len(line) > 3500 and current_chunk:
            chunks.append("\n".join(current_chunk))
            current_chunk = [line]
            current_len = len(line)
        else:
            current_chunk.append(line)
            current_len += len(line)
    if current_chunk:
        chunks.append("\n".join(current_chunk))
    
    proxies = urllib.request.ProxyHandler({
        "http": "http://127.0.0.1:7890",
        "https": "http://127.0.0.1:7890",
    })
    opener = urllib.request.build_opener(proxies)
    urllib.request.install_opener(opener)
    
    success = True
    for i, chunk in enumerate(chunks):
        data = json.dumps({
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            result = json.loads(resp.read())
            if not result.get("ok", False):
                print(f"❌ 第{i+1}块推送失败: {result}")
                success = False
        except Exception as e:
            print(f"❌ 第{i+1}块推送失败: {e}")
            success = False
        time.sleep(1)
    
    return success

# ===== 主流程 =====
def main():
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M")
    
    print(f"🇺🇸 美国经济软着陆监控 — {now_str}")
    print("=" * 50)
    
    # 1. 加载数据
    print("\n[1] 加载数据...")
    data = load_latest_data()
    
    # 2. 尝试爬取（补充缺失数据）
    print("[2] 尝试爬取最新数据...")
    scraped = try_scrape_us_economic_data()
    # 仅补充用户未填的数据
    for k, v in scraped.items():
        if k not in data or data.get(k) is None:
            data[k] = v
            print(f"  📡 爬取到: {k} = {v}")
    
    filled_count = sum(1 for ind in INDICATORS if data.get(ind["id"]) is not None)
    print(f"  数据完整度: {filled_count}/{len(INDICATORS)}")
    
    # 3. 计算评分
    print("\n[3] 计算软着陆评分...")
    result = calculate_landing_score(data, INDICATORS)
    
    print(f"  综合评分: {result['composite']}")
    print(f"  情景判断: {result['color']} {result['landing_type']}")
    
    # 4. 生成报告
    print("\n[4] 生成报告...")
    md_content = generate_report(result, now_str)
    
    # 保存报告
    report_file = REPORT_DIR / f"us_macro_report_{now.strftime('%Y%m%d_%H%M')}.md"
    report_file.write_text(md_content, encoding="utf-8")
    print(f"  报告已保存: {report_file}")
    
    # 5. 推送
    print("\n[5] 推送 Telegram...")
    push_to_telegram(md_content)
    
    # 6. 更新状态
    state = {
        "last_run": now.isoformat(),
        "last_score": result["composite"],
        "last_landing_type": result["landing_type"],
        "last_composite": result["composite"],
        "filled_count": filled_count,
        "total_count": len(INDICATORS),
    }
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    
    print(f"\n✅ 监控完成")
    print(f"  软着陆评分: {result['composite']}")
    print(f"  情景: {result['color']} {result['landing_type']}")
    print(f"  报告: {report_file}")

if __name__ == "__main__":
    main()
