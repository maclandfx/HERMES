#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中国政策与资本动向日报 — 从HTML提取真实政策标题+关键词命中+巨潮公告"""
import json, re, os, sys, datetime
from pathlib import Path

TMP = Path(r"C:/Users/Admin/tmp")

PRIORITY = {
    "十五五": 9, "规划": 8, "新型电力系统": 8, "虚拟电厂": 8, "源网荷储": 8,
    "非化石": 8, "车网互动": 8, "西电东送": 8, "需求响应": 8, "分布式": 7,
    "海上风电": 7, "核电": 7, "特高压": 7, "超算": 7, "固态": 7, "储能": 7,
    "氢能": 7, "EDA": 7, "光刻": 7, "先进制程": 7, "集成电路": 7,
    "低空": 7, "商业航天": 7, "低轨星座": 7, "卫星": 6, "航天": 6, "国防": 6,
    "半导体": 6, "芯片": 6, "算力": 6, "自主可控": 6, "国产化": 6,
    "大基金": 8, "汇金": 8, "证金": 8, "诚通": 8, "国新": 8, "国家队": 8,
    "央企": 7, "减持": 5, "增持": 5, "持股": 5, "招标": 5, "试点": 5,
    "意见": 4, "办法": 4, "通知": 4, "改革": 5, "发展": 3, "能源": 4,
    "数据": 4, "产业": 3, "投资": 4, "战略": 4, "建设": 3, "标准": 4,
}

def extract_html_titles(html_path):
    if not html_path.exists():
        return []
    content = html_path.read_text(encoding='utf-8', errors='ignore')
    items = re.findall(r'<a[^>]*>([^<]{20,200})</a>', content)
    titles = []
    for it in items:
        text = it.strip()
        if any(x in text for x in ['首页', '网站地图', '联系我们', '登录', '注册', '帮助中心', '无障碍', 'English']):
            continue
        if len(text) > 20 and not text.startswith('<'):
            titles.append(text[:120])
    seen = set()
    deduped = []
    for t in titles:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped

def score_titles(titles):
    scored = []
    for t in titles:
        max_score = 0
        matched_kw = []
        for kw, score in PRIORITY.items():
            if kw in t:
                max_score = max(max_score, score)
                matched_kw.append(kw)
        if max_score >= 3:
            scored.append((t, max_score, matched_kw))
    return sorted(scored, key=lambda x: -x[1])

def extract_cninfo_hits():
    """从巨潮300750公告中提取有价值公告"""
    cninfo_file = TMP / "cn300750_d.json"
    if not cninfo_file.exists():
        return []
    try:
        data = json.loads(cninfo_file.read_text(encoding='utf-8'))
        announcements = data.get('announcements', [])
        hits = []
        for a in announcements:
            title = a.get('announcementTitle', '') or a.get('shortTitle', '')
            if not title:
                continue
            # 筛选有价值的公告
            if any(x in title for x in ['权益变动', '减持', '增持', '股权转让', '大宗交易', '评级上调', '评级调整']):
                hits.append({
                    'title': title[:80],
                    'code': a.get('secCode', ''),
                    'name': a.get('tileSecName', '') or a.get('secName', ''),
                    'date': datetime.datetime.fromtimestamp(a.get('announcementTime', 0)/1000).strftime('%Y-%m-%d') if a.get('announcementTime') else '',
                })
        return hits
    except:
        return []

def _audit_sources():
    """审计数据源文件是否存在。返回 (ok, missing_files)。
    ok=True 表示数据源齐全；缺失则记录文件名清单，供报告顶部告警。
    """
    required = ['ndrc_d.html', 'miit_d.html', 'nea_d.html']
    missing = [f for f in required if not (TMP / f).exists()]
    return len(missing) == 0, missing


def generate_report():
    now = datetime.datetime.now()
    now_str = now.strftime("%Y-%m-%d")

    # ===== P0 防护：数据源存在性审计 =====
    sources_ok, missing_files = _audit_sources()

    lines = []
    lines.append(f"# 🇨🇳 中国政策与资本动向日报")
    lines.append(f"**日期**: {now_str}  |  数据时间: {now.strftime('%H:%M')}")
    lines.append("")

    if not sources_ok:
        missing_str = ", ".join(missing_files)
        lines.append("🚨 **数据源缺失告警**")
        lines.append("")
        lines.append(f"政策采集链夜间未正常生成 HTML 文件，缺失数据源：`{missing_str}`")
        lines.append("")
        lines.append("> ⚠️ 本报告基于**不完整数据**生成，政策定调/关键词模块为空属采集失败所致，")
        lines.append("> 并非真实\"无政策更新\"。请检查采集任务后再参考本报告。")
        lines.append("")
        lines.append("---")
        lines.append("")

    # ====== 1. 政策定调 ======
    lines.append("## 1. 【政策定调】")
    lines.append("")

    sources = [
        ("ndrc_d.html", "📋 国家发改委"),
        ("miit_d.html", "📋 工业和信息化部"),
        ("nea_d.html", "📋 国家能源局"),
    ]
    
    all_policy_count = 0
    has_any_source = False
    for fname, label in sources:
        if (TMP / fname).exists():
            has_any_source = True
        titles = extract_html_titles(TMP / fname)
        scored = score_titles(titles)
        if scored:
            all_policy_count += len(scored)
            lines.append(f"### {label}")
            lines.append("")
            for title, score, kws in scored[:10]:
                kw_str = '+' .join(kws)
                lines.append(f"- **{title}**  [{kw_str}]")
            lines.append("")

    if all_policy_count == 0:
        if has_any_source:
            lines.append("📭 数据源已到位，今日无政策文件更新")
        else:
            lines.append("⚠️ 政策采集未生成数据，本模块无内容")
        lines.append("")
    
    # ====== 2. 关键词热度 ======
    lines.append("## 2. 【关键词热度】")
    lines.append("")
    
    # 从HTML全文统计关键词
    kw_count = {}
    for fname in ['ndrc_d.html', 'miit_d.html', 'nea_d.html']:
        fpath = TMP / fname
        if fpath.exists():
            content = fpath.read_text(encoding='utf-8', errors='ignore')
            for kw in PRIORITY:
                count = content.count(kw)
                if count > 0:
                    if kw not in kw_count:
                        kw_count[kw] = {'count': 0, 'sources': set()}
                    kw_count[kw]['count'] += count
                    kw_count[kw]['sources'].add(fname.replace('_d.html',''))
    
    if kw_count:
        top_kw = sorted(kw_count.items(), key=lambda x: -x[1]['count'])
        lines.append("| 关键词 | 命中次数 | 来源 | 优先级 |")
        lines.append("|--------|----------|------|--------|")
        for kw, data in top_kw[:20]:
            src = '+'.join(sorted(data['sources']))
            pri = PRIORITY.get(kw, 2)
            emoji = "🔥" if pri >= 7 else "📊" if pri >= 5 else "📌"
            lines.append(f"| {kw} | {data['count']} | {src} | {emoji} |")
    else:
        lines.append("📭 暂无关键词命中数据")
    lines.append("")
    
    # ====== 3. 布局池调整 ======
    lines.append("## 3. 【布局池调整】")
    lines.append("")
    
    cninfo_hits = extract_cninfo_hits()
    if cninfo_hits:
        stock_groups = {}
        for h in cninfo_hits:
            code = h['code']
            if code not in stock_groups:
                stock_groups[code] = {'name': h['name'], 'titles': [], 'date': h['date']}
            if len(stock_groups[code]['titles']) < 2:
                stock_groups[code]['titles'].append(h['title'])
        
        lines.append("| 股票 | 动作 | 日期 | 公告 |")
        lines.append("|------|------|------|------|")
        for code, info in list(stock_groups.items())[:15]:
            action = "💎权益变动" if "权益变动" in str(info['titles']) else "📊"
            for t in info['titles']:
                lines.append(f"| **{info['name']}**({code}) | {action} | {info['date']} | {t} |")
    else:
        lines.append("📭 暂无国家队权益变动公告")
    lines.append("")
    
    # ====== 4. 摘要 ======
    lines.append("## 4. 【摘要】")
    lines.append("")
    
    total_kw = len(kw_count)
    total_cninfo = len(cninfo_hits)
    
    if all_policy_count >= 10 and total_cninfo >= 3:
        lines.append(f"📈 今日**政策面活跃、资本面有动作**：{all_policy_count} 条政策标题，{total_kw} 类关键词命中，{total_cninfo} 条巨潮公告")
    elif all_policy_count >= 5:
        lines.append(f"📊 今日**政策面有信号**：{all_policy_count} 条政策标题，{total_kw} 类关键词命中")
    elif total_cninfo >= 1:
        lines.append(f"💰 今日**资本面有动作**：{total_cninfo} 条巨潮公告")
    else:
        lines.append("⚪ 今日**无明显信号**，维持观望")
    
    if kw_count:
        hot_kw = sorted(kw_count.items(), key=lambda x: -x[1]['count'])[:5]
        lines.append("")
        lines.append("🔥 热点关键词: " + "、".join([f"**{k}**({v['count']}次)" for k, v in hot_kw]))
    
    # 如果有关键政策，给出行动暗示
    if all_policy_count > 0:
        lines.append("")
        lines.append("💡 **行动暗示**:")
        if any('十五五' in t for t, s, k in score_titles(extract_html_titles(TMP / "ndrc_d.html"))[:5]):
            lines.append("- 发改委密集发布十五五规划 → 关注规划文本中的量化目标")
        if any('核电' in t for t, s, k in score_titles(extract_html_titles(TMP / "nea_d.html"))[:5]):
            lines.append("- 能源局核电系列政策 → 核电产业链政策窗口期")
        if any('储能' in t for t, s, k in score_titles(extract_html_titles(TMP / "nea_d.html"))[:5]):
            lines.append("- 新型储能建设大纲 → 储能电站建设需求释放")
    
    lines.append("")
    lines.append("---")
    lines.append(f"*数据来源: 发改委/工信部/能源局官网 + 巨潮资讯网*")
    lines.append(f"*报告生成: {now.strftime('%Y-%m-%d %H:%M:%S')}*")
    
    return "\n".join(lines)

if __name__ == "__main__":
    print(generate_report())
