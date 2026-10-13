<p align="center">
  <img src="frontend/public/favicon.svg" width="80" height="80" alt="QoderGate Logo">
</p>

<h1 align="center">QoderGateway · Qoder CN 版专用</h1>

<p align="center">
  把多个 Qoder CN 版账号统一转换成 OpenAI 兼容接口的本地网关。<br>
  A local gateway for Qoder CN accounts with an OpenAI-compatible API.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-%3E%3D3.11-blue?logo=python&logoColor=white" alt="Python >= 3.11">
  <img src="https://img.shields.io/badge/fastapi-0.115+-green?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/license-MIT-orange" alt="License">
</p>

---

## 适用版本 / Qoder CN Only

**本仓库面向 Qoder CN（中国版）账号与 PAT，聊天、鉴权和模型目录使用 CN 端点。** CN 版与国际版的凭据、端点应配套使用；将 CN PAT 发往国际版端点可能返回 `401`。

如果需要国际版，请参考原作者的 [bzym2/QoderGateway](https://github.com/bzym2/QoderGateway)，或根据所用版本修改相关端点，并使用对应版本的账号凭据。本项目目前没有 CN / 国际版一键切换配置。

| 功能 | 本仓库使用的 CN 域名 | 国际版对应域名 | 相关文件 |
|------|---------------------|----------------|----------|
| job token / 用户状态 | `gateway.qoder.com.cn` | `center.qoder.sh` | [`src/qoder2api/auth.py`](src/qoder2api/auth.py) |
| 聊天 SSE | `gateway.qoder.com.cn` | `api3.qoder.sh` | [`src/qoder2api/bridge.py`](src/qoder2api/bridge.py) |
| 新版 Chat Completions 端点常量 | `gateway.qoder.com.cn` | `api2-v2.qoder.sh` | [`src/qoder2api/bridge.py`](src/qoder2api/bridge.py) |
| token 刷新 / 限额查询 | `openapi.qoder.com.cn` | `openapi.qoder.sh` | [`src/qoder2api/tokens.py`](src/qoder2api/tokens.py) |
| CN 模型目录 | `api.qoder.com.cn` | 按国际版实际接口配置 | [`src/qoder2api/app.py`](src/qoder2api/app.py) |

修改端点时请核对完整路径、协议和凭据类型。附带的注册 / device 授权模块（`src/qoder2api/registrar.py` 等）仍包含国际版端点，使用 CN 版时应先核对并适配这些模块；聊天接口切换到 CN 不代表注册流程也已完成适配。

## 致谢 / Acknowledgment

鸣谢 [bzym2/QoderGateway](https://github.com/bzym2/QoderGateway)，感谢原项目的开源贡献。

本项目思路来源于 [cubk1/qoder2api](https://github.com/cubk1/qoder2api/)，在此基础上用 Python 重写了后端并新增了 WebUI 管理控制台、SQLite 持久化、多账号池轮转和独立文档站。

This project is inspired by [cubk1/qoder2api](https://github.com/cubk1/qoder2api/). We rewrote the backend in Python and added a WebUI management console, SQLite persistence, multi-account pool rotation, and a standalone documentation site.

## 功能 / Features

- **OpenAI 兼容接口** — 通过 `/v1/chat/completions` 向客户端提供标准 Chat Completions API
- **多账号池** — 导入多个 Qoder 账号，按 UID 自动去重，请求失败时自动轮转
- **两层鉴权** — 管理后台密钥与外部 API Key 分开配置
- **SQLite 持久化** — 账号、API Key、全局配置全部存入本地数据库
- **WebUI 控制台** — Dashboard、账号管理、API Key 管理、Playground、服务日志
- **独立文档站** — `/documents` 提供中英文 Wiki，支持本地搜索和目录跳转
- **自动检测语言** — 根据浏览器地区自动切换中文/英文

## 快速开始 / Quickstart

### 安装 / Install

```bash
git clone https://github.com/STEVENTAN100/QoderGateway.git
cd QoderGateway
uv sync
cd frontend
npm ci
npm run build
cd ..
```

前端构建需要 Node.js 20.19+ 或 22.12+，构建产物会生成到 `src/qoder2api/static/`。

### 配置 / Configure

```bash
cp .env.example .env
```

编辑 `.env`，修改管理员密码：

```env
QODER_ADMIN_PASSWORD=your-strong-password
```

> **默认密码是 `admin`，强烈建议第一次登录后立即修改。**

### 启动 / Start

```bash
uv run qoder2api
```

服务默认运行在 `http://127.0.0.1:5050/`。

| 路径 | 说明 |
|------|------|
| `/` | Landing Page |
| `/console` | 管理控制台 |
| `/documents` | 文档站 / Wiki |
| `/v1/models` | 模型 ID 与显示名称（优先云端目录，失败时使用静态清单） |
| `/v1/chat/completions` | OpenAI 兼容 API |

### 第一次 API 调用 / First API Call

在控制台导入 CN 版账号后，使用模型目录中的 `id` 发起请求，例如：

```bash
curl http://127.0.0.1:5050/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qmodel_38max",
    "messages": [{ "role": "user", "content": "Hello" }],
    "stream": false
  }'
```

## 查询模型与更新清单 / Models

使用 **Qoder CN 版 PAT** 查询当前账号可见的云端模型 ID、显示名称及相关能力信息。下面的 `QODER_ACCESS_TOKEN` 变量应保存 CN PAT；不要把真实 Token 写进 README 或提交到 Git。它与本地网关的外部 API Key 是两种不同凭据。

### Bash / curl

```bash
# 在本地设置变量，替换为自己的 CN PAT。
export QODER_ACCESS_TOKEN='YOUR_QODER_CN_PAT'
curl -X GET "https://api.qoder.com.cn/api/v1/cloud/models" \
  -H "Authorization: Bearer $QODER_ACCESS_TOKEN"
```

响应中 `data[].id` 是聊天请求应填写的 `model` 值，`data[].display_name` 是显示名称。模型清单可能变更，请以接口实时返回为准；若响应的 `has_more` 为 `true`，需按上游接口的分页规则继续查询。

### Windows PowerShell（使用本地 `.env` 中已有的 PAT）

在项目根目录执行，读取 `.env` 的 `QODER_PAT`，无需在命令中粘贴真实 Token：

```powershell
$patLine = Get-Content -LiteralPath .env |
  Where-Object { $_ -match '^\s*QODER_PAT\s*=' } |
  Select-Object -First 1
if (-not $patLine) { throw '.env 中未配置 QODER_PAT' }
$env:QODER_ACCESS_TOKEN = ($patLine -split '=', 2)[1].Trim().Trim([char]34, [char]39)
if (-not $env:QODER_ACCESS_TOKEN) { throw 'QODER_PAT 为空' }
curl.exe -X GET "https://api.qoder.com.cn/api/v1/cloud/models" `
  -H "Authorization: Bearer $env:QODER_ACCESS_TOKEN"
```

### 当前模型代码位置

模型目录逻辑集中在 [`src/qoder2api/app.py`](src/qoder2api/app.py)：

- `fetch_cloud_models()`：从上述 CN 接口动态查询，使用环境变量 `QODER_PAT`，缓存 10 分钟，并过滤禁用模型。
- `SUPPORTED_MODELS`：云端查询失败或没有配置 PAT 时使用的静态回退清单。上游有变更时，可参照查询结果更新这里的 `id` 和 `display_name`。
- `list_models()`：提供本地 `/v1/models` 接口，优先返回动态目录，失败时返回静态清单。启用网关 API 鉴权时，访问此本地接口需携带网关 API Key。

模型请求参数的传递逻辑位于 [`src/qoder2api/bridge.py`](src/qoder2api/bridge.py) 的 `build_qoder_body()`；这里不是模型目录文件。更新静态清单后需重启网关；仅上游目录变更时，等待动态缓存到期即可重新获取。

2026-10-13 使用本地 CN PAT 查询成功（HTTP 200），返回以下 15 个模型条目，包含 `auto` / `fast` 路由选项：

| `model` / 模型 ID | 显示名称 |
|-------------------|----------|
| `auto` | Auto |
| `fast` | Fast |
| `qmodel_38max` | Qwen3.8-Max |
| `qfmodel` | Qwen3.8-Flash |
| `qmodel_latest` | Qwen3.7-Max |
| `qmodel` | Qwen3.7-Plus |
| `q37fmodel` | Qwen3.7-Flash |
| `dmodel` | DeepSeek-V4-Pro |
| `dfmodel` | DeepSeek-Flash |
| `gmodel` | GLM-5.3 |
| `gfmodel` | GLM-5.3-Flash |
| `gm51model` | GLM-5.2 |
| `kmodel_latest` | Kimi-K3 |
| `kmodel` | Kimi-K2.8-Preview |
| `mmodel` | MiniMax-M2.7 |

## 环境变量 / Environment Variables

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `QODER_HOST` | 服务绑定地址 | `127.0.0.1` |
| `QODER_PORT` | 服务端口 | `5050` |
| `QODER_ADMIN_PASSWORD` | 管理员密码（覆盖 SQLite 存储值） | `admin` |
| `QODER_PROXY` | 出站代理地址 | 空 |
| `QODER_ENABLE_DOCUMENTS` | 是否启用文档页 | `1` |
| `QODER_ENABLE_LANDING` | 是否启用 Landing Page | `1` |
| `QODER_PAT` | CN 版 PAT；用于启动导入账号及动态查询模型目录 | 空 |

## 项目结构 / Project Structure

```
├── src/qoder2api/          # Python 后端
│   ├── app.py              # FastAPI 路由、动态模型目录与静态回退清单
│   ├── accounts.py         # SQLite 账号管理
│   ├── auth.py             # Qoder 鉴权与签名
│   ├── bridge.py           # OpenAI 兼容响应转换
│   ├── config.py           # 配置读写
│   ├── database.py         # SQLite schema
│   ├── env.py              # 环境变量加载
│   └── static/             # 前端构建产物
├── frontend/               # React 前端源码
│   ├── src/App.tsx         # 管理控制台
│   ├── src/docs-main.tsx   # 文档站
│   ├── src/landing-main.tsx# Landing Page
│   └── src/docs/           # 中英文 Markdown 文档
├── .env.example            # 环境变量模板
└── pyproject.toml          # 项目配置
```

## License

MIT
