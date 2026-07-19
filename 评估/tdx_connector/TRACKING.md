# 通达信预警追踪控制

## 当前状态

- **追踪 cron job**: `949a7f97c8a8` (通达信预警监控-14:30后)
- **轮询时间**: 每 3 分钟，14:30-15:00，周一至周五
- **监控文件**: `D:\TDX\T0002\blocknew\.blk` 和 `tjg.blk`
- **状态**: ✅ 已启用

## 用户指令

| 指令 | 行为 |
|------|------|
| "开始追踪" | 启动监控（已在 cron 中配置） |
| "停止追踪" | 暂停 cron job `949a7f97c8a8` |
| "查看今日已追踪" | 显示 `tracked_YYYYMMDD.json` |
| "推送今日追踪结果" | 汇总推送 Telegram |

## 去重文件

- 路径: `D:/Hermes/评估中心/tools/tdx_connector/tracked_YYYYMMDD.json`
- 格式: `{"000001": {"time": "14:32:00", "condition": "盘中预警", "status": "analyzed"}}`

## Telegram 推送队列

- 路径: `D:/Hermes/评估中心/tools/tdx_connector/telegram_queue/`
- 格式: 每个预警生成一个 .txt 文件
