# 综合调度管理中心 — 同中书门下

## 职责
A 股投资评估系统唯一代码管理根目录。所有 .py 工具脚本、配置、版本历史由此入口访问。

## 结构（符号链接，零 breakage）
```
同中书门下/
  评估/        → 评估中心/tools/        (全部 .py 工具脚本)
  产出/        → 评估中心/reports/      (评估报告/因子/追踪产物)
  config/      → 评估中心/config/       (权重/隔离配置)
  版本历史/    → 评估中心/versions/     (v5.0/v5.1 历史版本)
  eval_engine.py  → 评估中心/eval_engine.py
  tdx_scan_codes.json → 评估中心/tdx_scan_codes.json
```

## 铁律
1. **代码编辑一律在 `同中书门下/评估/` 路径下操作** — 改的是同一个文件，但工作流以此为锚
2. **产出只写入 `同中书门下/产出/`** — 与代码物理分离
3. **评估中心本体不动** — 所有内部 `__file__` 相对路径、硬编码绝对路径、cron wrapper 保持原样
4. **新增脚本**：写入 `同中书门下/评估/`，链接自动生效

## 关键脚本索引
- `评估/factor_engine.py` — 因子引擎（16因子，含北向A4）
- `评估/eval_smart.py` — 智能评估主流程
- `评估/astock_bridge.py` — 腾讯行情+东财北向数据桥接
- `评估/cn_policy_report.py` — 中国政策与资本动向日报
- `评估/us_macro_monitor.py` — 美国宏观软着陆监控
- `评估/push_all_reports.py` — 全报告推送引擎
- `评估/tdx_data_sync.py` — 通达信K线同步
- `评估/tdx_connector/` — 通达信预警连接器
