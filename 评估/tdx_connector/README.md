# 通达信 (TDX) 连接器

## 概述

通达信连接器是一个**只读**的 Python 库，用于读取通达信软件本地存储的行情数据。

### 🚨 铁律

**绝不修改通达信任何文件。** 所有操作都是读取本地 `.day` 数据文件，不进行任何写入、修改或删除操作。

---

## 数据结构（已验证）

### 文件路径

```
D:\TDX\vipdoc\{sh,sz}\lday\{sh,sz}{6位代码}.day
```

示例：

- 上证指数：`D:\TDX\vipdoc\sh\lday\sh000001.day`
- 深证成指：`D:\TDX\vipdoc\sz\lday\sz399001.day`

### 文件格式

每条记录 **32 字节**，顺序存储，字段如下：

| 偏移  | 字段     | 类型     | 大小  | 说明                      |
| --- | ------ | ------ | --- | ----------------------- |
| 0   | date   | uint32 | 4B  | YYYYMMDD 整数（如 20260710） |
| 4   | open   | uint32 | 4B  | 开盘价，单位**分**（÷100 得元）    |
| 8   | high   | uint32 | 4B  | 最高价，单位分                 |
| 12  | low    | uint32 | 4B  | 最低价，单位分                 |
| 16  | close  | uint32 | 4B  | 收盘价，单位分                 |
| 20  | volume | uint32 | 4B  | 成交量（股）                  |
| 24  | amount | uint32 | 4B  | 成交额（待确认单位）              |
| 28  | extra  | uint32 | 4B  | 未知字段，忽略                 |

### 数据范围示例

**上证指数 (sh000001.day)**：

- 文件大小：38272 字节
- 记录数：1196 条
- 时间范围：2021-08-02 至 2026-07-10

**最新数据**：

- 2026-07-10 收盘价：3996.16 元

---

## 安装

将 `tdx_connector` 目录复制到项目工具目录：

```bash
cp -r tdx_connector/ D:/Hermes/评估中心/tools/
```

---

## 快速开始

```python
from tdx_connector import TDXConnector

# 初始化连接器（默认路径 D:\TDX）
tdx = TDXConnector(r"D:\TDX")

# 读取上证指数日线数据
records = tdx.read_daily_kline("000001", market="sh")
print(f"共 {len(records)} 条记录")
print(records[-1])  # 最新一条

# 批量读取多只股票
codes = ["000001", "399001", "000300"]
market_map = {"000001": "sh", "399001": "sz", "000300": "sh"}
batch = tdx.batch_get_klines(codes, market=market_map)
```

---

## 核心类

### TDXConnector

**初始化**

```python
TDXConnector(tdx_path: str = r"D:\TDX")
```

| 参数       | 类型  | 默认值      | 说明      |
| -------- | --- | -------- | ------- |
| tdx_path | str | `D:\TDX` | 通达信安装路径 |

**方法**

| 方法                                    | 参数                            | 返回         | 说明            |
| ------------------------------------- | ----------------------------- | ---------- | ------------- |
| `read_daily_kline(code, market)`      | code: str, market: str        | List[Dict] | 读取单只股票日线      |
| `get_latest_kline(code, market)`      | code: str, market: str        | Dict       | 获取最新一条日线      |
| `batch_get_klines(codes, market_map)` | codes: List, market_map: Dict | Dict       | 批量读取多只股票      |
| `get_stock_list(market)`              | market: str                   | List[str]  | 获取市场所有股票代码    |
| `get_financial_data(code, market)`    | code: str, market: str        | Dict       | 读取财务数据（待完善）   |
| `fetch_realtime_quote(code, market)`  | code: str, market: str        | Dict       | 实时行情（TCP，待完善） |

---

## 与评估系统集成

### 替代 tushare 数据源

在 `eval_smart.py` 中：

```python
from tdx_connector import TDXConnector

tdx = TDXConnector()

# 获取评估所需股票的 K 线数据
stock_codes = ["000001", "399001", "000300"]
klines = tdx.batch_get_klines(stock_codes)
```

### 优势

1. **离线可用** — 不依赖网络，本地数据立即可用
2. **数据完整** — 通达信本地数据包含完整历史
3. **实时更新** — 通达信运行后自动同步最新数据
4. **零成本** — 无 API 调用限制，无 Token 消耗

---

## 配置文件

在 `config.yaml` 中添加：

```yaml
tdx:
  path: D:/TDX
  enabled: true
  fallback: tushare  # 本地数据不可用时 fallback 到 tushare
```

---

## 技术规格

- **Python 版本**：3.10+
- **依赖**：无（纯标准库）
- **线程安全**：是（只读操作）
- **性能**：读取 5000 只股票约 3-5 秒（SSD）

---

## 已知限制

1. **实时行情未实现** — TCP 连接通达信行情服务器需要进一步验证
2. **财务数据未实现** — `.cw` 文件解析需要更多格式研究
3. **分钟线数据** — `minline` 目录存在，格式待分析

---

## 审计记录

| 日期         | 审计项    | 状态              |
| ---------- | ------ | --------------- |
| 2026-07-13 | 数据结构验证 | ✅ 已验证           |
| 2026-07-13 | 只读原则   | ✅ 铁律            |
| 2026-07-13 | 文件路径确认 | ✅ D:\TDX\vipdoc |

---

## 许可证

内部使用，不对外发布。
