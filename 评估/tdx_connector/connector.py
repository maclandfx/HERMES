#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通达信 (TDX) 连接器 — 读取本地数据和实时行情"""
import os
import struct
import socket
import json
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

class TDXError(Exception):
    """通达信连接器异常"""
    pass

class TDXConnector:
    """通达信本地数据 + 实时行情连接器"""
    
    def __init__(self, tdx_path: str = r"D:\TDX"):
        self.tdx_path = Path(tdx_path)
        self.vipdoc = self.tdx_path / "vipdoc"
        self.sh_path = self.vipdoc / "sh"
        self.sz_path = self.vipdoc / "sz"
        self.data_path = self.vipdoc / "sh" / "lday"  # 日线数据目录
        self.config = self._parse_connect_cfg()
        
    def _parse_connect_cfg(self) -> Dict[str, Any]:
        """解析通达信 connect.cfg 获取行情服务器"""
        cfg_path = self.tdx_path / "connect.cfg"
        if not cfg_path.exists():
            return {}
        servers = []
        lines = cfg_path.read_text(encoding="gbk", errors="ignore").split("\r\n")
        for line in lines:
            if line.startswith("IPAddress"):
                parts = line.split("=")
                if len(parts) == 2 and parts[1]:
                    servers.append({
                        "ip": parts[1],
                        "port": 7709,  # 默认端口
                        "source": line
                    })
        return {"servers": servers}
    
    def get_stock_list(self, market: str = "sh") -> List[str]:
        """获取市场所有股票代码列表"""
        market = market.lower()
        code_dir = self.sh_path / "lday" if market == "sh" else self.sz_path / "lday"
        if not code_dir.exists():
            return []
        codes = []
        for f in code_dir.iterdir():
            if f.suffix.lower() == ".lday" and f.stem not in ["000000", "000001", "399001"]:
                codes.append(f.stem)
        return sorted(codes)
    
    def read_daily_kline(self, code: str, market: str = "sh") -> List[Dict[str, Any]]:
        """读取本地日线 K 线数据 (.lday 文件)"""
        market = market.lower()
        code_dir = self.sh_path / "lday" if market == "sh" else self.sz_path / "lday"
        kfile = code_dir / f"{code}.lday"
        
        if not kfile.exists():
            raise TDXError(f"文件不存在: {kfile}")
        
        records = []
        with open(kfile, "rb") as f:
            # 每个 record = 32 bytes: date(2), open(4), high(4), low(4), close(4), volume(4), amount(4)
            while True:
                data = f.read(32)
                if len(data) < 32:
                    break
                date_part = struct.unpack("<H", data[0:2])[0]
                # 通达信日期格式：前两位是年份偏移，后五位是日期
                year = 2000 + (date_part >> 11)
                month = (date_part & 0x7FE0) >> 5
                day = date_part & 0x1F
                try:
                    dt = datetime(year, month, day)
                except:
                    continue
                
                open_price = struct.unpack("<f", data[2:6])[0]
                high_price = struct.unpack("<f", data[6:10])[0]
                low_price = struct.unpack("<f", data[10:14])[0]
                close_price = struct.unpack("<f", data[14:18])[0]
                volume = struct.unpack("<I", data[18:22])[0]
                amount = struct.unpack("<f", data[22:26])[0]
                
                records.append({
                    "date": dt.strftime("%Y-%m-%d"),
                    "open": round(open_price, 2),
                    "high": round(high_price, 2),
                    "low": round(low_price, 2),
                    "close": round(close_price, 2),
                    "volume": volume,
                    "amount": round(amount, 2)
                })
        
        return records
    
    def get_latest_kline(self, code: str, market: str = "sh") -> Optional[Dict[str, Any]]:
        """获取最新一条日线 K 线"""
        records = self.read_daily_kline(code, market)
        return records[-1] if records else None
    
    def read_weekly_kline(self, code: str, market: str = "sh") -> List[Dict[str, Any]]:
        """读取本地周线数据 (.lday 文件，需要自己聚合)"""
        daily = self.read_daily_kline(code, market)
        if not daily:
            return []
        
        # 按周聚合（周一为周期开始）
        weekly = []
        current_week = None
        
        for day in daily:
            dt = datetime.strptime(day["date"], "%Y-%m-%d")
            week_start = dt - timedelta(days=dt.weekday())
            
            if current_week != week_start:
                if current_week and weekly:
                    weekly[-1]["close"] = day["close"]  # 周五收盘
                    weekly[-1]["volume"] = sum(r["volume"] for r in daily 
                                              if datetime.strptime(r["date"], "%Y-%m-%d").isocalendar()[:2] == week_start.isocalendar()[:2])
                    weekly[-1]["amount"] = sum(r["amount"] for r in daily 
                                              if datetime.strptime(r["date"], "%Y-%m-%d").isocalendar()[:2] == week_start.isocalendar()[:2])
                
                # 新周开始
                weekly.append({
                    "date": week_start.strftime("%Y-%m-%d"),
                    "open": day["open"],
                    "high": day["high"],
                    "low": day["low"],
                    "close": 0,
                    "volume": 0,
                    "amount": 0
                })
                current_week = week_start
            else:
                weekly[-1]["high"] = max(weekly[-1]["high"], day["high"])
                weekly[-1]["low"] = min(weekly[-1]["low"], day["low"])
                weekly[-1]["volume"] += day["volume"]
                weekly[-1]["amount"] += day["amount"]
        
        return weekly
    
    def get_financial_data(self, code: str, market: str = "sh") -> Optional[Dict[str, Any]]:
        """获取财务数据 (.cw 文件)"""
        cw_dir = self.vipdoc / "cw" / market.lower()
        cwfile = cw_dir / f"{code}.cw"
        
        if not cwfile.exists():
            raise TDXError(f"财务文件不存在: {cwfile}")
        
        # 通达信财务文件格式（简化版）
        data = {}
        try:
            with open(cwfile, "rb") as f:
                raw = f.read()
            # 尝试解析常见字段
            # 这里需要根据实际文件格式调整
            return {"raw_size": len(raw), "file": str(cwfile)}
        except Exception as e:
            return {"error": str(e)}
    
    def fetch_realtime_quote(self, code: str, market: str = "sh") -> Optional[Dict[str, Any]]:
        """通过 TCP 获取实时行情 (需要通达信行情服务器)"""
        if not self.config.get("servers"):
            raise TDXError("无可用行情服务器配置")
        
        # 构造查询包
        code_bytes = code.encode("ascii") + b"-" + market.upper().encode("ascii") + b"\x01\x01\x00\x00\x00"
        
        for server in self.config["servers"][:3]:  # 尝试前3个服务器
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3)
                sock.connect((server["ip"], server["port"]))
                
                # 发送查询包
                header = struct.pack("<H", len(code_bytes) + 8)
                sock.send(header + code_bytes + b"\x00\x00\x00\x00")
                
                # 接收响应
                sock.settimeout(5)
                resp = sock.recv(1024)
                sock.close()
                
                if len(resp) > 8:
                    return self._parse_realtime_response(resp[8:], code, market)
                    
            except (socket.error, socket.timeout):
                continue
        
        return None
    
    def _parse_realtime_response(self, data: bytes, code: str, market: str) -> Dict[str, Any]:
        """解析实时行情响应"""
        if len(data) < 10:
            raise TDXError("响应数据不足")
        
        # 简化解析（通达信实时行情包格式）
        try:
            price = struct.unpack("<H", data[0:2])[0] / 100.0
            return {
                "code": code,
                "market": market,
                "price": price,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "source": "TDX real-time"
            }
        except:
            return {
                "code": code,
                "market": market,
                "error": "解析失败",
                "raw_length": len(data)
            }
    
    def get_stock_info(self, code: str, market: str = "sh") -> Optional[Dict[str, str]]:
        """获取股票基本信息（名称等）"""
        # 通达信股票信息存储在 base.dbf 或类似文件中
        # 这里先返回代码和市场
        return {
            "code": code,
            "market": market,
            "full_code": f"{market.upper()}{code}"
        }
    
    def batch_get_klines(self, codes: List[str], market: str = "sh", 
                         start_date: str = None, end_date: str = None) -> Dict[str, List[Dict[str, Any]]]:
        """批量获取多只股票的 K 线数据"""
        result = {}
        for code in codes:
            try:
                records = self.read_daily_kline(code, market)
                if start_date and end_date:
                    records = [r for r in records 
                              if start_date <= r["date"] <= end_date]
                result[code] = records
            except TDXError as e:
                result[code] = {"error": str(e)}
        return result


def main():
    """测试连接器功能"""
    tdx = TDXConnector(r"D:\TDX")
    
    print("=== 通达信连接器测试 ===")
    print(f"通达信路径: {tdx.tdx_path}")
    print(f"数据目录: {tdx.vipdoc}")
    print(f"可用行情服务器: {len(tdx.config.get('servers', []))} 个")
    
    # 测试读取上证指数日线
    try:
        print("\n=== 上证指数 (000001) 最新日线 ===")
        latest = tdx.get_latest_kline("000001", "sh")
        if latest:
            print(json.dumps(latest, ensure_ascii=False, indent=2))
    except TDXError as e:
        print(f"错误: {e}")
    
    # 测试获取股票列表
    try:
        print("\n=== 上海市场股票数量 ===")
        codes = tdx.get_stock_list("sh")
        print(f"股票数量: {len(codes)}")
        print(f"前10个: {codes[:10]}")
    except Exception as e:
        print(f"错误: {e}")


if __name__ == "__main__":
    main()
