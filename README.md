# futures-backtest 期货回测系统

本地个人期货量化回测工作台：Vue 3 前端 + FastAPI 后端。核心流程：**在网页里编写 Python 策略 → 后端执行回测 → 前端 K 线图展示结果**，另集成 LightGBM 机器学习预测与多因子自适应评分两套量化模块。

## 功能概览

- **多数据源 K 线**：akshare（默认，新浪分钟线 + 东财日线）/ tushare / tqsdk 天勤，前端可切换
- **自定义策略回测**：米筐（RQAlpha）风格策略接口 `init(context)` + `handle_bar(ctx, bar)`，支持 buy / sell / short / cover / flip 六种动作，含手续费、保证金、合约乘数计算；也支持直接输出信号列表的模式
- **LightGBM 模块**：训练 / 预测 / 回测分离，模型存 `backend/models/*.pkl`
- **多因子模型**：7 因子分趋势 / 反转两组，ADX 判断市场状态自适应切换
- **策略文件管理**：网页端浏览、编辑、保存策略文件（CodeMirror 编辑器）

## 技术栈

| 端 | 技术 |
|----|------|
| 前端 | Vue 3.5 + Vite 7 + TypeScript + Pinia + Vue Router + View UI Plus + Highcharts + CodeMirror |
| 后端 | Python + FastAPI + uvicorn，psycopg2 / akshare / tushare / lightgbm / pandas |
| 数据库 | PostgreSQL（仅存主力合约清单表 `futures_contracts`，K 线实时拉取不落地） |

## 端口

| 端口 | 用途 |
|------|------|
| 8000 | 前端 Vite 开发服务器（`/api` 代理到 8001） |
| 8001 | 后端 FastAPI；生产模式下同时托管 `dist/` 前端静态文件 |

## 快速开始

### 后端

```bash
pip install -r backend/requirements.txt
# 数据库连接等配置在 backend/.env（已随仓库提供，含 PG_HOST / TUSHARE_TOKEN / TQSDK 账号）
cd backend && python main.py        # http://localhost:8001
```

### 前端

```bash
pnpm install
pnpm dev                            # http://localhost:8000
```

### 生产模式

```bash
pnpm build
cd backend && python main.py        # 访问 http://localhost:8001 即可
```

## 目录结构

```
├── src/                  # 前端源码
│   ├── App.vue           # 主界面（合约选择 / K线 / 回测 / ML）
│   ├── components/       # StockChart、FactorModel、MLPrediction、StrategyEditor 等
│   └── router/           # / 与 /editor 两条路由
├── backend/
│   ├── main.py           # FastAPI 主应用 + BacktestEngine 回测引擎
│   ├── ml_api.py         # LightGBM 训练 / 预测 / 回测
│   ├── factor_api.py     # 多因子自适应评分模型
│   ├── strategies/       # 内置示例策略（阶梯双K交易系统）
│   └── run_*.py          # 历史实验脚本
├── data/                 # 本地缓存（contracts.db，不入库）
└── index.html
```

## 主要 API

- `GET /api/contracts`、`POST /api/contracts/update`、`GET /api/contracts/{exchange}`
- `GET /api/kline/{code}?frequency=&start_date=&end_date=&source=`
- `POST /api/backtest` — 一键回测，返回结果 + K 线数据
- `GET/POST /api/ml/models|train|backtest`、`DELETE /api/ml/models/{file}`
- `GET /api/factors/list`、`POST /api/factors/backtest`
- `GET/POST /api/files`、`/api/file` — 策略文件读写

## 注意事项

- 策略代码通过 `exec()` 执行且 `/api/file` 可读写文件，**请勿将后端直接暴露到公网**
- `backend/.env` 含数据库密码、天勤账号、tushare token，仓库为私有，请勿转为公开
- K 线数据依赖 akshare / tushare 在线接口，需联网使用
