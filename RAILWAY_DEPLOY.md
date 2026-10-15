# FlowMap → Railway 部署说明

本分支相对上游的改动（均已验证）：

| 文件 | 改动 |
|---|---|
| `server/src/flowmap_server/railway_main.py`（新增） | 云端入口：绑 `0.0.0.0:$PORT`（上游 `__main__` 强制 loopback-only，云上无法启动）；FastAPI 同源 serve 前端 build 产物（SPA fallback）；从 `RAILWAY_PUBLIC_DOMAIN` 自动配 `FLOWMAP_WS_ALLOWED_ORIGINS` |
| `Dockerfile`（新增） | 多阶段构建：node:22 构建前端 → python:3.13-slim 跑后端，依赖按 `server/uv.lock` 锁定安装（含 `vendor/` 里的 crocodile wheel，无需外网 git） |
| `railway.json`（新增） | 指定 Dockerfile 构建 + `/api/health` 健康检查 |
| `.dockerignore`（新增） | 瘦身构建上下文 |

上游 `server/`、`client/` 源码**零修改**，后续 upstream 有更新可以直接 merge。

## 部署步骤

1. 把本目录推到你自己的 GitHub 仓库（fork 即可）。
2. Railway → New Project → Deploy from GitHub repo，选该仓库。`railway.json` 会自动选中 Dockerfile 构建。
3. Region 选 **Singapore**（Binance/Bybit 等交易所对美国出口 IP 有 geo-block，新加坡没问题）。
4. 生成公网域名：service → Settings → Networking → Generate Domain。入口会自动从 `RAILWAY_PUBLIC_DOMAIN` 配好 WS origin 白名单，无需手动设。
5. 打开域名，即看到 FlowMap，选 `SIM-DEMO` 先确认画面正常，再切 `BTCUSDT` / `ETHUSDT` 验证实时流。

## 可选环境变量

| 变量 | 说明 |
|---|---|
| `FLOWMAP_RECORDING_ENABLED=0` | 关掉 parquet 录音回放（容器盘是临时的，录了重启就丢；要保留就挂 Railway Volume 并设 `FLOWMAP_DATA_DIR`，同时把 `FLOWMAP_RECORDING_GB_CAP` 调小） |
| `FLOWMAP_WS_ALLOWED_ORIGINS` | 默认自动取公网域名；自定义域名时手动设为 `https://你的域名`（或 `*` 关掉检查，不推荐） |
| `FLOWMAP_WS_MAX_CONNECTIONS` | 默认 16，公开展示多人同时看可调大 |
| `ALPACA_API_KEY` / `ALPACA_API_SECRET` / `FINNHUB_API_KEY` | 美股 real L1 数据 key（不设则用 keyless SYNTH 档） |
| `FLOWMAP_RING_COLUMNS` | 内存环形列数（默认 32768，内存吃紧可调小） |

## 安全提醒

服务端**没有鉴权**（上游设计如此，loopback-only 就是它的安全边界）。部署到公网后任何人都能打开你的域名看实时流、调 `/api`。建议：

- 只是自己用 → Railway service 设成不生成公网域名、走 Railway 的 Private Network + 本地 `railway tunnel` 访问；
- 要公开展示 → 前面加 Cloudflare Access / Authelia 之类的鉴权层。

## 本地冒烟测试（已跑过）

```bash
# 后端依赖（需 uv）
cd server && uv sync --frozen --no-dev --no-install-project
# 前端构建
cd client && npm ci && npm run build
# 启动（模拟 Railway：PORT + 公网域名）
PORT=8720 RAILWAY_PUBLIC_DOMAIN=xxx.up.railway.app \
  FLOWMAP_CLIENT_DIST=../client/dist \
  PYTHONPATH=server/src server/.venv/bin/python -m flowmap_server.railway_main
# 验证
curl localhost:8720/api/health   # -> {"ok": true, ...}
curl localhost:8720/              # -> index.html
```
