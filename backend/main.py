"""
期货回测数据API v2.1
- 配置从 .env 读取（dotenv）
- 数据库连接池
- 修复变量重复、None校验等问题
"""
import os
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List
import re
import warnings
import logging

from dotenv import load_dotenv
import psycopg2
import psycopg2.extras
from psycopg2 import pool as pg_pool
from contextlib import contextmanager
from fastapi import FastAPI, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import akshare as ak
import tushare as ts
import pandas as pd
import numpy as np

class SafeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, float):
            if not np.isfinite(obj):
                return 0.0
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

# ---- 加载 .env ----
load_dotenv(Path(__file__).parent / ".env")

TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")
TQSDK_ACCOUNT = os.getenv("TQSDK_ACCOUNT", "bj153")
TQSDK_PASSWORD = os.getenv("TQSDK_PASSWORD", "")
PG_CONFIG = {
    'host': os.getenv("PG_HOST", "localhost"),
    'port': int(os.getenv("PG_PORT", "5432")),
    'database': os.getenv("PG_DATABASE", "futures_data"),
    'user': os.getenv("PG_USER", "postgres"),
    'password': os.getenv("PG_PASSWORD", "postgres"),
    'client_encoding': 'utf8'
}

os.environ['PYTHONIOENCODING'] = 'utf-8'
warnings.filterwarnings('ignore')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ---- 常量 ----
FRONTEND_DIST = Path(__file__).parent.parent / "dist"

# ---- 品种代码到中文名映射 ----
VARIETY_NAMES = {
    # 中金所
    'IF': '沪深300', 'IC': '中证500', 'IH': '上证50', 'IM': '中证1000',
    'T': '10年国债', 'TF': '5年国债', 'TS': '2年国债', 'TL': '30年国债',
    # 上期所
    'AU': '黄金', 'AG': '白银', 'CU': '铜', 'AL': '铝', 'ZN': '锌',
    'PB': '铅', 'NI': '镍', 'SN': '锡',
    'RB': '螺纹钢', 'HC': '热卷', 'SS': '不锈钢', 'WR': '线材',
    'RU': '橡胶', 'BU': '沥青', 'FU': '燃料油',
    'AO': '氧化铝', 'AD': '丁二烯', 'BR': '丁二烯橡胶', 'OP': '瓶片',
    'SP': '纸浆',
    # 大商所
    'C': '玉米', 'CS': '玉米淀粉', 'A': '豆一', 'B': '豆二',
    'M': '豆粕', 'Y': '豆油', 'P': '棕榈油',
    'JD': '鸡蛋', 'RR': '粳米', 'L': '塑料', 'V': 'PVC',
    'PP': '聚丙烯', 'EB': '苯乙烯', 'EG': '乙二醇',
    'J': '焦炭', 'JM': '焦煤', 'I': '铁矿石',
    'FB': '纤维板', 'BB': '胶合板', 'PG': 'LPG', 'BZ': '纯苯',
    'LH': '生猪',
    # 郑商所
    'SR': '白糖', 'CF': '棉花', 'TA': 'PTA', 'MA': '甲醇',
    'FG': '玻璃', 'SA': '纯碱', 'UR': '尿素',
    'RM': '菜粕', 'OI': '菜油', 'ZC': '动力煤',
    'SF': '硅铁', 'SM': '锰硅', 'CY': '棉纱',
    'AP': '苹果', 'CJ': '红枣', 'PK': '花生',
    'WH': '强麦', 'PM': '普麦', 'RI': '早籼稻', 'JR': '粳稻',
    'RS': '菜籽', 'LR': '晚籼稻',
    'SH': '烧碱', 'PF': '短纤', 'PX': '对二甲苯',
    # 能源中心
    'SC': '原油', 'NR': '20号胶', 'BC': '国际铜',
    'EC': '集运指数', 'LU': '低硫燃油',
    # 广期所
    'SI': '工业硅', 'LC': '碳酸锂', 'GD': '多晶硅',
    'PD': '氢氧化锂',
}

# 交易所映射
EXCHANGE_MAP = {
    'cffex': 'CFFEX', 'shfe': 'SHFE', 'dce': 'DCE',
    'czce': 'CZCE', 'ine': 'INE', 'gfex': 'GFEX',
    '中国金融期货交易所': 'CFFEX', '上海期货交易所': 'SHFE',
    '大连商品交易所': 'DCE', '郑州商品交易所': 'CZCE',
    '上海国际能源交易中心': 'INE', '广州期货交易所': 'GFEX',
}

# Tushare 交易所映射
TS_EXCHANGE_MAP = {
    'CFX': 'CFFEX', 'CF': 'CFFEX',
    'SHF': 'SHFE',
    'DCE': 'DCE',
    'ZCE': 'CZCE',
    'INE': 'INE',
    'GFE': 'GFEX',
}

# 合约交易所前缀匹配（用于 Tushare K线查询）
CONTRACT_EXCHANGE_MAP = {
    'p': 'DCE', 'm': 'DCE', 'y': 'DCE', 'a': 'DCE', 'c': 'DCE',
    'cs': 'DCE', 'jm': 'DCE', 'j': 'DCE', 'i': 'DCE', 'l': 'DCE',
    'v': 'DCE', 'pp': 'DCE', 'b': 'DCE', 'eg': 'DCE', 'eb': 'DCE',
    'rb': 'SHFE', 'hc': 'SHFE', 'ss': 'SHFE', 'wr': 'SHFE',
    'cu': 'SHFE', 'al': 'SHFE', 'zn': 'SHFE', 'pb': 'SHFE',
    'ni': 'SHFE', 'sn': 'SHFE', 'au': 'SHFE', 'ag': 'SHFE',
    'ru': 'SHFE', 'bu': 'SHFE', 'fu': 'SHFE', 'sp': 'SHFE',
    'if': 'CFFEX', 'ic': 'CFFEX', 'ih': 'CFFEX', 'im': 'CFFEX',
    'ts': 'CFFEX', 'tf': 'CFFEX', 't': 'CFFEX', 'tl': 'CFFEX',
    'cf': 'ZCE', 'sr': 'ZCE', 'ta': 'ZCE', 'ma': 'ZCE',
    'fg': 'ZCE', 'oi': 'ZCE', 'rm': 'ZCE', 'pm': 'ZCE',
    'wh': 'ZCE', 'ap': 'ZCE', 'cj': 'ZCE', 'ur': 'ZCE',
    'sa': 'ZCE', 'pf': 'ZCE', 'px': 'ZCE',
    'sc': 'INE', 'lu': 'INE', 'nr': 'INE', 'bc': 'INE', 'ec': 'INE',
    'si': 'GFEX', 'lc': 'GFEX', 'gd': 'GFEX',
}

# ---- 数据库连接池 ----
_db_pool: Optional[pg_pool.ThreadedConnectionPool] = None

def get_pool() -> pg_pool.ThreadedConnectionPool:
    global _db_pool
    if _db_pool is None:
        try:
            _db_pool = pg_pool.ThreadedConnectionPool(1, 10, **PG_CONFIG)
            logger.info(f"数据库连接池已创建: {PG_CONFIG['database']}")
        except Exception as e:
            logger.warning(f"创建连接池失败: {e}")
            raise
    return _db_pool

@contextmanager
def get_db():
    """从连接池获取连接"""
    pool = get_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)

def format_time(dt: datetime) -> str:
    if isinstance(dt, pd.Timestamp):
        dt = dt.to_pydatetime()
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

# ---- FastAPI 应用 ----
app = FastAPI(title="期货回测数据API", version="2.1.0")

# ---- Pydantic Models ----
class KlineData(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    hold: int = 0

class Contract(BaseModel):
    code: str
    name: str
    exchange: str
    current_price: Optional[float] = None
    is_main: Optional[str] = None

class BacktestRequest(BaseModel):
    strategy: str
    contract_code: str
    frequency: str = "1m"
    start_date: str
    end_date: str
    initial_capital: float = 10000
    commission: float = 0.0001
    margin_ratio: float = 0.1
    source: str = "akshare"
    threshold: float = 2.0  # 画折线回撤阈值
    multiplier: float = 1.0  # 合约乘数（1手=multiplier吨/克/桶等）
    ema_fast: int = 10  # EMA快线周期
    ema_slow: int = 40  # EMA慢线周期

# ---- 数据库初始化 ----
def init_db():
    try:
        conn = psycopg2.connect(**PG_CONFIG)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM futures_contracts LIMIT 1")
        cursor.close()
        conn.close()
        logger.info(f"数据库连接成功: {PG_CONFIG['database']}")
    except Exception as e:
        logger.warning(f"数据库检查失败: {e}")

def seed_default_contracts():
    """初始化默认合约列表（数据库为空时）"""
    conn = psycopg2.connect(**PG_CONFIG)
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM futures_contracts')
        count = cursor.fetchone()[0]
        if count > 0:
            return

        products = [
            ('IF', '沪深300指数', 'cffex'), ('IC', '中证500指数', 'cffex'),
            ('IH', '上证50指数', 'cffex'), ('IM', '中证1000指数', 'cffex'),
            ('jm', '焦煤', 'dce'), ('i', '铁矿石', 'dce'), ('j', '焦炭', 'dce'),
            ('rb', '螺纹钢', 'shfe'), ('hc', '热卷', 'shfe'), ('cu', '沪铜', 'shfe'),
            ('au', '沪金', 'shfe'), ('ag', '沪银', 'shfe'), ('sc', '原油', 'ine'),
            ('ru', '橡胶', 'shfe'), ('ma', '甲醇', 'czce'), ('ta', 'PTA', 'czce'),
        ]

        now = datetime.now()
        year = now.year % 100
        next_year = (now.year + 1) % 100
        main_months = [3, 5, 7, 9, 12]

        months = []
        for m in main_months:
            if m >= now.month:
                months.append(f"{year:02d}{m:02d}")
            months.append(f"{next_year:02d}{m:02d}")

        for symbol, name, exchange in products:
            for month in months:
                cursor.execute('''
                    INSERT INTO futures_contracts (code, name, exchange)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (code) DO NOTHING
                ''', (f"{symbol}{month}", f"{name}{month}", exchange))

        conn.commit()
        logger.info(f"初始化默认合约: {len(products) * len(months)} 条")
    finally:
        conn.close()

init_db()
seed_default_contracts()

# ---- 数据库操作函数 ----
def get_contracts_from_db() -> List[dict]:
    with get_db() as conn:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute('SELECT code, name, exchange FROM futures_contracts ORDER BY code')
        rows = cursor.fetchall()
        return [{'code': row['code'], 'name': row['name'], 'exchange': row['exchange'] or ''} for row in rows]

def update_contracts_from_akshare() -> dict:
    try:
        pro = ts.pro_api(TUSHARE_TOKEN)
        today = datetime.now().strftime('%Y%m%d')
        df = pro.fut_mapping(trade_date=today)

        if df.empty:
            yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
            df = pro.fut_mapping(trade_date=yesterday)

        if df.empty:
            return {'success': False, 'count': 0, 'message': 'Tushare无数据'}

        main_df = df[~df['ts_code'].str.contains('L')]

        main_contracts = []
        for _, row in main_df.iterrows():
            mapping_code = row.get('mapping_ts_code', '')
            if not mapping_code or '.' not in mapping_code:
                continue

            code_part, ts_exchange = mapping_code.split('.')
            exchange = TS_EXCHANGE_MAP.get(ts_exchange, ts_exchange)

            variety = code_part.rstrip('0123456789')
            variety_name = VARIETY_NAMES.get(variety.upper(), variety.upper())
            name = f"{variety_name} {code_part.lower()}"

            main_contracts.append({
                'code': code_part.lower(),
                'name': name,
                'exchange': exchange
            })

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM futures_contracts')
            for c in main_contracts:
                cursor.execute('''
                    INSERT INTO futures_contracts (code, name, exchange)
                    VALUES (%s, %s, %s)
                ''', (c['code'], c['name'], c['exchange']))
            conn.commit()

        logger.info(f"从Tushare更新主力合约: {len(main_contracts)} 条")
        return {'success': True, 'count': len(main_contracts), 'message': f'成功更新 {len(main_contracts)} 个主力合约'}

    except Exception as e:
        logger.error(f"更新主力合约失败: {e}")
        return {'success': False, 'count': 0, 'message': str(e)}

# ---- API 路由 ----
@app.get("/")
async def root():
    index_file = FRONTEND_DIST / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"message": "Futures Backtest API", "docs": "/docs"}

@app.get("/api/contracts", response_model=List[Contract])
async def get_contracts():
    return get_contracts_from_db()

@app.post("/api/contracts/update")
async def update_contracts():
    result = update_contracts_from_akshare()
    if not result['success']:
        raise HTTPException(status_code=500, detail=result['message'])
    return result

@app.get("/api/contracts/{exchange}")
async def get_contracts_by_exchange(exchange: str):
    all_contracts = get_contracts_from_db()
    return [c for c in all_contracts if c['exchange'] == exchange.lower()]


# ==================== 文件浏览 ====================
import os

PROJECT_ROOT = Path(__file__).parent.parent
IGNORE_DIRS = {"node_modules", ".git", "__pycache__", "dist"}
IGNORE_EXT = {".pyc", ".lock"}


@app.get("/api/files")
async def list_files(path: str = Query(".")):
    """列出项目目录文件"""
    abs_path = (PROJECT_ROOT / path).resolve()
    if not abs_path.exists() or not abs_path.is_dir():
        raise HTTPException(status_code=404, detail="目录不存在")
    try:
        children = []
        for entry in sorted(abs_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            name = entry.name
            if name.startswith("."):
                continue
            if entry.is_dir() and name in IGNORE_DIRS:
                continue
            children.append({
                "name": name,
                "path": str(entry.relative_to(PROJECT_ROOT)),
                "is_dir": entry.is_dir(),
            })
        return {"path": str(abs_path.relative_to(PROJECT_ROOT)), "children": children}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/file")
async def read_file(path: str = Query(...)):
    """读取文件内容"""
    abs_path = (PROJECT_ROOT / path).resolve()
    if not abs_path.exists() or not abs_path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    try:
        content = abs_path.read_text(encoding="utf-8")
        return {"path": path, "content": content}
    except UnicodeDecodeError:
        return {"path": path, "content": "[二进制文件，不可预览]"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/file")
async def save_file(path: str = Query(...), body: dict = {}):
    """保存文件（不存在时在已有目录内创建）"""
    abs_path = (PROJECT_ROOT / path).resolve()
    if not abs_path.is_relative_to(PROJECT_ROOT.resolve()):
        raise HTTPException(status_code=403, detail="禁止访问项目目录外的文件")
    if abs_path.is_dir():
        raise HTTPException(status_code=400, detail="路径是目录，无法写入")
    if not abs_path.exists() and not abs_path.parent.is_dir():
        raise HTTPException(status_code=404, detail="目录不存在")
    content = body.get("content", "")
    abs_path.write_text(content, encoding="utf-8")
    return {"success": True}


@app.delete("/api/file")
async def delete_file(path: str = Query(...)):
    """删除文件（仅限项目目录内）"""
    abs_path = (PROJECT_ROOT / path).resolve()
    if not abs_path.is_relative_to(PROJECT_ROOT.resolve()):
        raise HTTPException(status_code=403, detail="禁止删除项目目录外的文件")
    if not abs_path.exists() or not abs_path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    abs_path.unlink()
    return {"success": True}


# ==================== K线数据获取 ====================

@app.get("/api/kline/{contract_code}", response_model=List[KlineData])
async def get_kline(
    contract_code: str,
    frequency: str = Query(...),
    start_date: str = Query(...),
    end_date: str = Query(...),
    source: str = Query(default="akshare")
):
    contract_code = contract_code.lower()
    if source == "tushare":
        return await get_kline_from_tushare(contract_code, frequency, start_date, end_date)
    elif source == "tqsdk":
        return await get_kline_from_tqsdk(contract_code, frequency, start_date, end_date)
    else:
        return await get_kline_from_akshare(contract_code, frequency, start_date, end_date)


async def get_kline_from_tushare(contract_code: str, frequency: str, start_date: str, end_date: str) -> List[KlineData]:
    """从Tushare获取K线数据"""
    try:
        pro = ts.pro_api(TUSHARE_TOKEN)

        exchange = CONTRACT_EXCHANGE_MAP.get(contract_code.rstrip('0123456789'), 'DCE')
        ts_code = f"{contract_code.upper()}.{exchange}"

        if frequency == "1d":
            freq_map = "daily"
        elif frequency == "1h":
            freq_map = "60min"
        elif frequency == "30m":
            freq_map = "30min"
        elif frequency == "15m":
            freq_map = "15min"
        elif frequency == "5m":
            freq_map = "5min"
        elif frequency == "1m":
            freq_map = "1min"
        else:
            freq_map = "daily"

        if freq_map == "daily":
            df = pro.fut_daily(
                ts_code=ts_code,
                start_date=start_date.replace('-', ''),
                end_date=end_date.replace('-', ''),
                fields='trade_date,open,high,low,close,vol'
            )
        else:
            # Tushare新版无pro.fut_minute方法，改用pro.query('fut_wsr', ...)
            try:
                df = pro.query(
                    'fut_wsr',
                    symbol=contract_code.upper(),
                    trade_date='',
                    start_date=start_date.replace('-', ''),
                    end_date=end_date.replace('-', ''),
                    freq=freq_map
                )
            except Exception as e:
                logger.warning(f"Tushare fut_wsr查询失败: {e}，回退到旧版方法")
                df = None

        if df is None or df.empty:
            logger.warning(f"Tushare无数据: {ts_code} {freq_map}")
            return []

        results = []
        # fut_wsr 返回字段: ts_code, trade_date, trade_time, open, high, low, close, vol, amount
        time_col = 'trade_time' if freq_map != 'daily' and 'trade_time' in df.columns else 'trade_date'
        vol_col = 'vol' if 'vol' in df.columns else 'vol'

        for _, row in df.iterrows():
            time_str = str(row[time_col])
            if freq_map != "daily" and len(time_str) > 8 and '-' not in time_str:
                dt = datetime.strptime(time_str, '%Y%m%d %H:%M:%S')
            elif len(time_str) == 8:
                dt = datetime.strptime(time_str, '%Y%m%d')
            elif '-' in time_str:
                dt = datetime.strptime(time_str[:19], '%Y-%m-%d %H:%M:%S')
            else:
                continue

            results.append(KlineData(
                time=format_time(dt),
                open=float(row.get('open', 0) or 0),
                high=float(row.get('high', 0) or 0),
                low=float(row.get('low', 0) or 0),
                close=float(row.get('close', 0) or 0),
                volume=int(float(row.get(vol_col, 0) or 0))
            ))

        return results
    except Exception as e:
        logger.error(f"Tushare K线获取失败: {e}")
        return []


async def get_kline_from_tqsdk(contract_code: str, frequency: str, start_date: str, end_date: str) -> List[KlineData]:
    """从天勤获取K线数据"""
    try:
        from tqsdk import TqApi, TqAuth, TqChan

        # 交易所前缀
        exchange_prefix_map = {
            'dce': 'DCE', 'shfe': 'SHFE', 'czce': 'CZCE',
            'cffex': 'CFFEX', 'ine': 'INE', 'gfex': 'GFEX',
        }

        variety = contract_code.rstrip('0123456789')
        ex = CONTRACT_EXCHANGE_MAP.get(variety, 'DCE')

        tq_symbol = f"{ex}.{contract_code.upper()}"
        api = TqApi(auth=TqAuth(TQSDK_ACCOUNT, TQSDK_PASSWORD))

        freq_map = {
            '1m': 60, '5m': 300, '15m': 900, '30m': 1800,
            '1h': 3600, '1d': 86400
        }
        sec = freq_map.get(frequency, 60)

        klines = api.get_kline_serial(tq_symbol, sec, data_length=max(200, int((pd.to_datetime(end_date) - pd.to_datetime(start_date)).total_seconds() / sec) + 100))

        import asyncio
        for _ in range(20):
            api.update()
            await asyncio.sleep(0.1)

        df = pd.DataFrame(klines)
        if df.empty:
            api.close()
            return []

        df['datetime'] = pd.to_datetime(df['datetime'], unit='s') + pd.Timedelta(hours=8)
        mask = (df['datetime'] >= start_date) & (df['datetime'] <= end_date + ' 23:59:59')
        df = df[mask]

        results = []
        for _, row in df.iterrows():
            results.append(KlineData(
                time=format_time(row['datetime']),
                open=float(row['open']),
                high=float(row['high']),
                low=float(row['low']),
                close=float(row['close']),
                volume=int(row['volume'])
            ))

        api.close()
        return results
    except Exception as e:
        logger.error(f"天勤K线获取失败: {e}")
        return []


async def get_kline_from_akshare(contract_code: str, frequency: str, start_date: str, end_date: str) -> List[KlineData]:
    """从AKShare获取K线数据
    - 分钟级(1m/5m/15m/30m/60m): 新浪接口 futures_zh_minute_sina
    - 日线: 东方财富 futures_hist_em
    """
    try:
        symbol = contract_code.upper()
        
        # 分钟数据用新浪接口
        min_freq_map = {
            '1m': '1', '5m': '5', '10m': '10', '15m': '15', '30m': '30', '1h': '60',
        }
        
        if frequency in min_freq_map:
            period = min_freq_map[frequency]
            df = ak.futures_zh_minute_sina(symbol=symbol, period=period)
            
            if df is None or df.empty:
                logger.warning(f"新浪分钟线无数据: {symbol} {period}")
                return []
            
            # 新浪返回列: datetime, open, high, low, close, volume, hold
            results = []
            for _, row in df.iterrows():
                dt_val = row.get('datetime', '')
                if isinstance(dt_val, str):
                    dt = datetime.strptime(dt_val[:19], '%Y-%m-%d %H:%M:%S')
                elif isinstance(dt_val, datetime):
                    dt = dt_val
                elif isinstance(dt_val, pd.Timestamp):
                    dt = dt_val.to_pydatetime()
                else:
                    continue
                
                # 精确时间范围过滤
                if dt < datetime.strptime(start_date[:10], '%Y-%m-%d') or dt > datetime.strptime(end_date[:10], '%Y-%m-%d') + timedelta(days=1):
                    continue
                
                results.append(KlineData(
                    time=format_time(dt),
                    open=float(row.get('open', 0) or 0),
                    high=float(row.get('high', 0) or 0),
                    low=float(row.get('low', 0) or 0),
                    close=float(row.get('close', 0) or 0),
                    volume=int(float(row.get('volume', 0) or 0)),
                    hold=int(float(row.get('hold', 0) or 0))
                ))
            
            return results
        
        # 日线：优先东方财富，失败/无数据时回退新浪日线
        df = None
        try:
            df = ak.futures_hist_em(
                symbol=symbol,
                period='daily',
                start_date=start_date[:10].replace('-', ''),
                end_date=end_date[:10].replace('-', '')
            )
        except Exception as e:
            logger.warning(f"东方财富日线异常({symbol})，尝试新浪日线: {e}")
        
        if df is None or df.empty:
            logger.info(f"东方财富日线无数据({symbol})，回退新浪日线")
            try:
                sdf = ak.futures_zh_daily_sina(symbol=symbol)
                if sdf is not None and not sdf.empty:
                    sdf['date'] = pd.to_datetime(sdf['date'])
                    start_dt = pd.Timestamp(start_date[:10])
                    end_dt = pd.Timestamp(end_date[:10])
                    sdf = sdf[(sdf['date'] >= start_dt) & (sdf['date'] <= end_dt)]
                    results = []
                    for _, row in sdf.iterrows():
                        results.append(KlineData(
                            time=format_time(row['date'].to_pydatetime()),
                            open=float(row.get('open', 0) or 0),
                            high=float(row.get('high', 0) or 0),
                            low=float(row.get('low', 0) or 0),
                            close=float(row.get('close', 0) or 0),
                            volume=int(float(row.get('volume', 0) or 0)),
                            hold=int(float(row.get('hold', 0) or 0)),
                        ))
                    return results
            except Exception as e:
                logger.warning(f"新浪日线获取失败({symbol}): {e}")
            return []
        
        results = []
        for _, row in df.iterrows():
            dt_val = row.get('日期', row.get('date', ''))
            if isinstance(dt_val, str):
                dt = datetime.strptime(dt_val[:10], '%Y-%m-%d') if '-' in dt_val else datetime.strptime(dt_val[:8], '%Y%m%d')
            elif isinstance(dt_val, datetime):
                dt = dt_val
            elif isinstance(dt_val, pd.Timestamp):
                dt = dt_val.to_pydatetime()
            else:
                continue
            
            results.append(KlineData(
                time=format_time(dt),
                open=float(row.get('开盘', row.get('open', 0)) or 0),
                high=float(row.get('最高', row.get('high', 0)) or 0),
                low=float(row.get('最低', row.get('low', 0)) or 0),
                close=float(row.get('收盘', row.get('close', 0)) or 0),
                volume=int(float(row.get("成交量", row.get("volume", 0)) or 0)),
                hold=0,
            ))
        
        return results
    except Exception as e:
        logger.warning(f"AKShare获取失败({contract_code}): {e}")
        return []


# ==================== 回测引擎 ====================

class BacktestEngine:
    """期货回测引擎"""

    def __init__(self, data: List[dict], strategy_code: str, contract_code: str,
                 initial_capital: float = 10000, commission: float = 0.0001,
                 margin_ratio: float = 0.1, multiplier: float = 1.0,
                 ema_fast: int = 10, ema_slow: int = 40):
        self.data = data
        self.strategy_code = strategy_code
        self.contract_code = contract_code
        self.initial_capital = initial_capital
        self.commission_rate = commission
        self.margin_ratio = margin_ratio
        self.multiplier = multiplier

        self.capital = initial_capital
        self.position = 0
        self.total_commission = 0
        self.trades = []
        self.equity_curve = []
        self.entry_price = 0
        self.entry_time = None
        self.channels = None
        self._threshold_value = 5.0
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow

    def run(self) -> dict:
        if not self.data:
            return self._empty_result()

        # 米筐风格逐K线执行
        self._run_miqin_style()

        return self._calculate_metrics()

    def _run_miqin_style(self):
        """米筐风格: init() 初始化, handle_bar() 每根K线调用"""
        try:
            context = {
                'capital': self.initial_capital,
                'position': 0,
                'entry_price': 0,
                'trades': [],
                'equity_curve': [],
                'total_commission': 0,
                'bars': self.data,
                'threshold': getattr(self, '_threshold_value', 2.0),
                'ema_fast': self.ema_fast,
                'ema_slow': self.ema_slow,
            }

            # 内置函数
            builtin_funcs = {
                'sma': self._sma,
                'ema': self._ema,
                'rsi': self._rsi,
                'calc_verts': self._calc_verts_internal,
            }

            local_vars = {
                'context': context,
                'init': lambda ctx: None,
                'handle_bar': lambda ctx, bd: None,
                **builtin_funcs,
            }

            # 同一个 dict 同时作为 globals 和 locals，确保函数定义可访问
            exec_scope = {
                **local_vars,
                **builtin_funcs,
                '__builtins__': {
                    'len': len, 'range': range, 'min': min, 'max': max,
                    'abs': abs, 'sum': sum, 'int': int, 'float': float,
                    'list': list, 'dict': dict, 'all': all, 'any': any,
                    'sorted': sorted, 'round': round, 'str': str,
                    'enumerate': enumerate, 'zip': zip,
                    'Exception': Exception, 'NameError': NameError,
                },
            }
            exec(self.strategy_code, exec_scope)
            local_vars = exec_scope

            # 执行 init
            init_fn = local_vars.get('init')
            if init_fn:
                init_fn(context)

            # 逐K线执行 handle_bar
            handle_fn = local_vars.get('handle_bar')
            if not handle_fn:
                return

            for i, bar in enumerate(self.data):
                # 构建 bar_dict（当前K线）
                bar_dict = {
                    'open': bar['open'],
                    'high': bar['high'],
                    'low': bar['low'],
                    'close': bar['close'],
                    'volume': bar['volume'],
                    'time': bar['time'],
                }

                # 更新 context
                context['current_bar'] = i
                context['bar'] = bar_dict

                # 调用 handle_bar
                handle_fn(context, bar_dict)

                # 检查是否有下单信号
                action = context.get('_action')
                if action and action != 'hold':
                    self._execute_action(action, bar, context)
                    context['_action'] = None  # 清除信号

                # 记录权益
                self._record_equity(i)

            # channels 传回前端（引擎自动画折线）
            try:
                closes = [bar['close'] for bar in self.data]
                highs = [bar['high'] for bar in self.data]
                lows = [bar['low'] for bar in self.data]
                times = [bar['time'] for bar in self.data]
                verts = []
                i = 0
                n = len(closes)
                threshold = getattr(self, '_threshold_value', 2.0)
                while i < n:
                    if len(verts) == 0:
                        verts.append({'idx': 0, 'price': closes[0], 'type': 'low'})
                        i = 1
                        continue
                    if verts[-1].get('type') == 'low':
                        high_idx, high_price = i, highs[i]
                        found = False
                        for j in range(i, n):
                            if highs[j] > high_price:
                                high_price, high_idx = highs[j], j
                            if (high_price - closes[j]) >= threshold and j > high_idx:
                                verts.append({'idx': high_idx, 'price': high_price, 'type': 'high'})
                                i = high_idx + 1
                                found = True
                                break
                        if not found: break
                    else:
                        low_idx, low_price = i, lows[i]
                        found = False
                        for j in range(i, n):
                            if lows[j] < low_price:
                                low_price, low_idx = lows[j], j
                            if (closes[j] - low_price) >= threshold and j > low_idx:
                                verts.append({'idx': low_idx, 'price': low_price, 'type': 'low'})
                                i = low_idx + 1
                                found = True
                                break
                        if not found: break
                if len(verts) >= 2:
                    pts = [{'time': times[v['idx']], 'price': round(v['price'], 2)} for v in verts]
                    self.channels = [{'points': pts}]
            except Exception:
                self.channels = None

        except Exception as e:
            logger.error(f"策略执行失败: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def _execute_action(self, action: str, bar: dict, context: dict):
        """执行交易动作"""
        price = context.get('_price', bar['close'])
        reason = context.get('_reason', '')
        self.total_commission = context.get('total_commission', 0)

        m = self.multiplier
        if action == 'buy' and self.position == 0:
            self.position = 1
            self.entry_price = price
            fee = price * m * self.commission_rate
            self.capital -= fee
            self.total_commission += fee
            self.trades.append({
                'time': bar['time'], 'action': '买开', 'price': price,
                'quantity': int(m), 'equity': round(self._calc_equity(price), 2),
                'pnl': round(-fee, 2), 'reason': reason
            })

        elif action == 'sell' and self.position > 0:
            pnl = self.position * (price - self.entry_price) * m
            fee = price * m * self.commission_rate
            self.capital += pnl - fee
            self.total_commission += fee
            self.trades.append({
                'time': bar['time'], 'action': '卖平', 'price': price,
                'quantity': int(m), 'equity': round(self.capital, 2),
                'pnl': round(pnl - fee, 2), 'reason': reason
            })
            self.position = 0
            self.entry_price = 0

        elif action == 'short' and self.position == 0:
            self.position = -1
            self.entry_price = price
            fee = price * m * self.commission_rate
            self.capital -= fee
            self.total_commission += fee
            self.trades.append({
                'time': bar['time'], 'action': '卖开', 'price': price,
                'quantity': int(m), 'equity': round(self._calc_equity(price), 2),
                'pnl': round(-fee, 2), 'reason': reason
            })

        elif action == 'cover' and self.position < 0:
            pnl = (self.entry_price - price) * m  # 空单盈利 = (开仓价-平仓价)*乘数
            fee = price * m * self.commission_rate
            self.capital += pnl - fee
            self.total_commission += fee
            self.trades.append({
                'time': bar['time'], 'action': '买平', 'price': price,
                'quantity': int(m), 'equity': round(self.capital, 2),
                'pnl': round(pnl - fee, 2), 'reason': reason
            })
            self.position = 0
            self.entry_price = 0

        # 翻转操作：同一根K线平多+开空
        if action == 'flip_short':
            if self.position > 0:
                pnl = (price - self.entry_price) * m
                fee = price * m * self.commission_rate
                self.capital += pnl - fee
                self.total_commission += fee
                self.trades.append({
                    'time': bar['time'], 'action': '卖平', 'price': price,
                    'quantity': int(m), 'equity': round(self.capital, 2),
                    'pnl': round(pnl - fee, 2), 'reason': reason + '先平多'
                })
            self.position = -1
            self.entry_price = price
            fee2 = price * m * self.commission_rate
            self.capital -= fee2
            self.total_commission += fee2
            self.trades.append({
                'time': bar['time'], 'action': '卖开', 'price': price,
                'quantity': int(m), 'equity': round(self._calc_equity(price), 2),
                'pnl': round(-fee2, 2), 'reason': reason
            })
        elif action == 'flip_long':
            if self.position < 0:
                pnl = (self.entry_price - price) * m
                fee = price * m * self.commission_rate
                self.capital += pnl - fee
                self.total_commission += fee
                self.trades.append({
                    'time': bar['time'], 'action': '买平', 'price': price,
                    'quantity': int(m), 'equity': round(self.capital, 2),
                    'pnl': round(pnl - fee, 2), 'reason': reason + '先平空'
                })
            self.position = 1
            self.entry_price = price
            fee2 = price * m * self.commission_rate
            self.capital -= fee2
            self.total_commission += fee2
            self.trades.append({
                'time': bar['time'], 'action': '买开', 'price': price,
                'quantity': int(m), 'equity': round(self._calc_equity(price), 2),
                'pnl': round(-fee2, 2), 'reason': reason
            })

        context['position'] = self.position
        context['entry_price'] = self.entry_price
        context['total_commission'] = self.total_commission

    def _record_equity(self, bar_idx: int):
        if bar_idx >= len(self.data):
            return
        bar = self.data[bar_idx]
        equity = self._calc_equity(bar['close'])
        self.equity_curve.append({
            'time': bar['time'],
            'value': round(equity, 2)
        })

    def _record_equity(self, is_last: bool = False):
        bar_idx = len(self.equity_curve)
        if bar_idx >= len(self.data):
            return
        bar = self.data[bar_idx]
        equity = self._calc_equity(bar['close'])
        self.equity_curve.append({
            'time': bar['time'],
            'value': round(equity, 2)
        })

    def _calc_equity(self, current_price: float) -> float:
        if self.position != 0:
            unrealized = self.position * (current_price - self.entry_price)
        else:
            unrealized = 0
        return self.capital + unrealized

    def _process_bars(self, signals: List[dict]):
        """逐条K线处理交易信号"""
        max_bars = len(self.data)

        for i, bar in enumerate(self.data):
            if i >= len(signals):
                break

            sig = signals[i] if i < len(signals) else {'action': 'hold'}
            action = sig.get('action', 'hold')

            if action == 'hold':
                self._record_equity()
                continue

            price = float(sig.get('price', bar['close']))
            reason = sig.get('reason', '')

            if action == 'buy' and self.position == 0:
                # 开多
                self.position = 1
                self.entry_price = price
                self.entry_time = bar['time']
                fee = price * self.commission_rate
                self.capital -= fee
                self.total_commission += fee
                self.trades.append({
                    'time': bar['time'],
                    'action': '买开',
                    'price': price,
                    'quantity': 1,
                    'equity': round(self._calc_equity(price), 2),
                    'pnl': 0,
                    'reason': reason
                })

            elif action == 'sell' and self.position > 0:
                # 平多
                pnl = self.position * (price - self.entry_price)
                fee = price * self.commission_rate
                self.capital += pnl - fee
                self.total_commission += fee
                self.trades.append({
                    'time': bar['time'],
                    'action': '卖平',
                    'price': price,
                    'quantity': 1,
                    'equity': round(self.capital, 2),
                    'pnl': round(pnl - fee, 2),
                    'reason': reason
                })
                self.position = 0
                self.entry_price = 0

            elif action == 'short' and self.position == 0:
                # 开空
                self.position = -1
                self.entry_price = price
                self.entry_time = bar['time']
                fee = price * self.commission_rate
                self.capital -= fee
                self.total_commission += fee
                self.trades.append({
                    'time': bar['time'],
                    'action': '卖开',
                    'price': price,
                    'quantity': 1,
                    'equity': round(self._calc_equity(price), 2),
                    'pnl': 0,
                    'reason': reason
                })

            elif action == 'cover' and self.position < 0:
                # 平空
                pnl = self.position * (self.entry_price - price)
                fee = price * self.commission_rate
                self.capital += pnl - fee
                self.total_commission += fee
                self.trades.append({
                    'time': bar['time'],
                    'action': '买平',
                    'price': price,
                    'quantity': 1,
                    'equity': round(self.capital, 2),
                    'pnl': round(pnl - fee, 2),
                    'reason': reason
                })
                self.position = 0
                self.entry_price = 0

            self._record_equity()

    def _execute_strategy(self) -> List[dict]:
        """执行策略代码，返回信号列表"""
        try:
            closes = [bar['close'] for bar in self.data]

            if len(closes) < 10:
                return [{'action': 'hold'} for _ in self.data]

            pos = self.position
            entry_p = self.entry_price

            # 默认指标
            sma9 = self._sma(closes, 9)
            sma21 = self._sma(closes, 21)
            rsi14 = self._rsi(closes, 14)

            # 构建作用域
            local_vars = {
                'closes': closes,
                'bars': self.data,
                'position': pos,
                'entry_price': entry_p,
                'sma9': sma9,
                'sma21': sma21,
                'rsi14': rsi14,
                'sma': self._sma,
                'ema': self._ema,
                'rsi': self._rsi,
                'volume': [bar['volume'] for bar in self.data],
                'times': [bar['time'] for bar in self.data],
                'highs': [bar['high'] for bar in self.data],
                'lows': [bar['low'] for bar in self.data],
                'volumes': [bar['volume'] for bar in self.data],
            }

            exec(self.strategy_code, {"__builtins__": {"len": len, "range": range, "min": min, "max": max, "abs": abs, "sum": sum, "int": int, "float": float, "list": list, "dict": dict, "all": all, "any": any, "sorted": sorted, "round": round, "str": str, "enumerate": enumerate, "zip": zip, "Exception": Exception, "NameError": NameError}}, local_vars)
            signals = local_vars.get('signals')
            self.channels = local_vars.get('channels')
            if signals is None:
                return [{'action': 'hold'} for _ in self.data]
            return signals
        except Exception as e:
            logger.error(f"策略执行失败: {e}")
            return [{'action': 'hold'} for _ in self.data]

    @staticmethod
    def _sma(values: List[float], period: int) -> List[float]:
        result = [values[0]] * len(values)
        for i in range(1, len(values)):
            if i < period:
                result[i] = sum(values[:i+1]) / (i+1)
            else:
                result[i] = sum(values[i-period+1:i+1]) / period
        return result

    @staticmethod
    def _ema(values: List[float], period: int) -> List[float]:
        result = [values[0]] * len(values)
        k = 2 / (period + 1)
        for i in range(1, len(values)):
            result[i] = values[i] * k + result[i-1] * (1 - k)
        return result

    @staticmethod
    def _rsi(values: List[float], period: int) -> List[float]:
        deltas = [values[i] - values[i-1] for i in range(1, len(values))]
        seed = deltas[:period]
        up = sum(d for d in seed if d > 0) / period
        down = -sum(d for d in seed if d < 0) / period
        result = [50.0] * len(values)
        if down != 0:
            rs = up / down
            result[period] = 100 - 100 / (1 + rs)
        else:
            result[period] = 100
        for i in range(period+1, len(values)):
            delta = deltas[i-1]
            up = (up * (period - 1) + max(delta, 0)) / period
            down = (down * (period - 1) + max(-delta, 0)) / period
            rs = up / down if down != 0 else 999
            result[i] = 100 - 100 / (1 + rs)
        return result

    def _empty_result(self) -> dict:
        return {
            'initialEquity': self.initial_capital,
            'finalEquity': self.initial_capital,
            'pnl': 0, 'netPnl': 0, 'totalCommission': 0,
            'totalReturn': 0, 'annualizedReturn': 0,
            'winRate': 0, 'tradeCount': 0, 'maxDrawdown': 0,
            'sharpeRatio': 0, 'profitLossRatio': 0,
            'avgProfit': 0, 'avgLoss': 0,
            'peakEquity': self.initial_capital, 'peakTime': None,
            'equityCurve': [{'time': self.data[0]['time'] if self.data else '', 'value': self.initial_capital}],
            'trades': [],
            'channels': None
        }

    def _calculate_metrics(self) -> dict:
        """计算回测指标"""
        if not self.data:
            return self._empty_result()

        # 1. 基础收益
        final_equity = self.capital
        if not self.equity_curve:
            return self._empty_result()

        total_return = (final_equity - self.initial_capital) / self.initial_capital * 100

        # 交易天数估算
        days_range = (datetime.strptime(self.data[-1]['time'][:10], '%Y-%m-%d') -
                      datetime.strptime(self.data[0]['time'][:10], '%Y-%m-%d')).days
        years = max(days_range / 365, 1 / 365)
        annualized_return = ((1 + total_return / 100) ** (1 / years) - 1) * 100

        # 2. 胜率
        closed_trades = [t for t in self.trades if t['pnl'] != 0]
        if closed_trades:
            win_trades = sum(1 for t in closed_trades if t['pnl'] > 0)
            win_rate = win_trades / len(closed_trades) * 100
        else:
            win_rate = 0

        # 3. 最大回撤
        if self.equity_curve:
            peak = self.initial_capital
            max_dd = 0
            peak_equity = self.initial_capital
            peak_idx = 0
            for i, p in enumerate(self.equity_curve):
                v = p['value']
                if v > peak:
                    peak = v
                    peak_equity = v
                    peak_idx = i
                dd = (peak - v) / peak * 100 if peak > 0 else 0
                if dd > max_dd:
                    max_dd = dd

        equity_values = [e['value'] for e in self.equity_curve]

        # 4. 夏普率（简化：年化收益/年化波动）
        returns = []
        for i in range(1, len(equity_values)):
            if equity_values[i-1] > 0:
                r = (equity_values[i] - equity_values[i-1]) / equity_values[i-1]
                returns.append(r)
        if returns:
            avg_return = np.mean(returns)
            std_return = np.std(returns) if len(returns) > 1 else 0.001
            sharpe_ratio = (avg_return / std_return) * np.sqrt(252)
        else:
            sharpe_ratio = 0

        # 5. 盈亏比
        profit_trades = [t['pnl'] for t in closed_trades if t['pnl'] > 0]
        loss_trades = [abs(t['pnl']) for t in closed_trades if t['pnl'] < 0]
        avg_profit = np.mean(profit_trades) if profit_trades else 0
        avg_loss = np.mean(loss_trades) if loss_trades else 0
        profit_loss_ratio = avg_profit / avg_loss if avg_loss > 0 else 0

        return json.loads(json.dumps({
            'initialEquity': self.initial_capital,
            'finalEquity': round(final_equity, 2) if np.isfinite(final_equity) else 0,
            'pnl': round(final_equity - self.initial_capital + self.total_commission, 2) if np.isfinite(final_equity) else 0,
            'netPnl': round(final_equity - self.initial_capital, 2) if np.isfinite(final_equity) else 0,
            'totalCommission': round(self.total_commission, 2),
            'totalReturn': round(total_return, 2) if np.isfinite(total_return) else 0,
            'annualizedReturn': round(annualized_return, 2) if np.isfinite(annualized_return) else 0,
            'winRate': round(win_rate, 2) if np.isfinite(win_rate) else 0,
            'tradeCount': len(closed_trades),
            'maxDrawdown': round(max_dd, 2) if np.isfinite(max_dd) else 0,
            'sharpeRatio': round(sharpe_ratio, 2) if np.isfinite(sharpe_ratio) else 0,
            'profitLossRatio': round(profit_loss_ratio, 2) if np.isfinite(profit_loss_ratio) else 0,
            'avgProfit': round(avg_profit, 2) if np.isfinite(avg_profit) else 0,
            'avgLoss': round(avg_loss, 2) if np.isfinite(avg_loss) else 0,
            'peakEquity': round(peak_equity, 2) if np.isfinite(peak_equity) else 0,
            'peakTime': self.equity_curve[peak_idx]['time'] if self.equity_curve else None,
            'equityCurve': [{'time': e['time'], 'value': e['value'], 'max_eq': e.get('max_eq', 0)} if isinstance(e, dict) else e for e in self.equity_curve],
            'trades': [{'time': t['time'], 'action': t['action'], 'price': t['price'], 'quantity': t['quantity'], 'pnl': t['pnl'], 'equity': t['equity'], 'reason': t.get('reason', '')} if isinstance(t, dict) else t for t in self.trades],
            'channels': getattr(self, 'channels', None)
        }, cls=SafeEncoder))



    @staticmethod
    def _calc_verts_internal(highs, lows, closes, threshold_val):
        """内置顶点计算函数（阈值用绝对值）"""
        n = len(highs)
        threshold = threshold_val
        verts = []
        i = 0
        while i < n:
            if len(verts) == 0:
                verts.append({'price': closes[0], 'type': 'low'})
                i = 1
                continue
            last_type = verts[-1]['type']
            if last_type == 'low':
                high_idx, high_price = i, highs[i]
                found = False
                for j in range(i, n):
                    if highs[j] > high_price:
                        high_price, high_idx = highs[j], j
                    if (high_price - closes[j]) >= threshold and j > high_idx:
                        verts.append({'price': high_price, 'type': 'high'})
                        i = high_idx + 1
                        found = True
                        break
                if not found: break
            else:
                low_idx, low_price = i, lows[i]
                found = False
                for j in range(i, n):
                    if lows[j] < low_price:
                        low_price, low_idx = lows[j], j
                    if (closes[j] - low_price) >= threshold and j > low_idx:
                        verts.append({'price': low_price, 'type': 'low'})
                        i = low_idx + 1
                        found = True
                        break
                if not found: break
        return verts

@app.post("/api/backtest")
async def run_backtest(req: BacktestRequest):
    """一键回测"""
    try:
        kline_response = await get_kline(
            contract_code=req.contract_code,
            frequency=req.frequency,
            start_date=req.start_date,
            end_date=req.end_date,
            source=req.source
        )

        data = [{"time": item.time, "open": item.open, "high": item.high,
                 "low": item.low, "close": item.close, "volume": item.volume}
                for item in kline_response]

        if not data:
            raise HTTPException(status_code=400, detail="未获取到K线数据")

        engine = BacktestEngine(
            data=data,
            strategy_code=req.strategy,
            contract_code=req.contract_code,
            initial_capital=req.initial_capital,
            commission=req.commission,
            margin_ratio=req.margin_ratio,
            multiplier=req.multiplier,
            ema_fast=req.ema_fast,
            ema_slow=req.ema_slow,
        )
        if hasattr(engine, '_threshold_value'):
            engine._threshold_value = req.threshold
        result = engine.run()
        result["klineData"] = data

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"回测执行失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# ML 预测 API v2（训练/回测分离）
# ============================================================
from ml_api import router as ml_router
app.include_router(ml_router)

# ============================================================
# 多因子动态评分模型 API
# ============================================================
from factor_api import router as factor_router
app.include_router(factor_router)


# 挂载前端静态文件
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)