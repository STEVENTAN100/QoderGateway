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

- **两种 API 接口** — `/v1/chat/completions` 提供 Chat Completions，`/v1/responses` 适配 Codex 常用的 Responses 文本与工具调用流程
- **Codex 工具调用** — 保留 `function` / `custom` 自由文本工具及命名空间，支持 `additional_tools` 声明与多轮工具结果回传
- **实际 token 用量与思考文本** — 传递上游 usage（含 reasoning / cached tokens），思考内容与最终答案分开返回
- **思考强度原样传递** — `max` 等显式档位不自动降档，是否支持由上游模型决定
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
| `/v1/responses` | Responses 文本、工具调用及流式事件接口 |

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

## Responses 与 Codex 接入

本仓库提供原生接入路径 `POST /v1/responses`，内部适配 Qoder CN 的聊天协议。推荐将 Codex 或中转服务的供应商协议设置为 **Responses**，Base URL 填写 `http://127.0.0.1:5050/v1`（远程部署时替换为自己的网关地址），模型使用 `gfmodel`、`gmodel` 等 Qoder 模型 ID，API Key 使用网关管理后台配置的外部 Key，不能将 CN PAT 当成网关 Key。

连接路径应保持为 `/v1/responses`，避免在网关之前再次转换为 Chat Completions；仅切换供应商名称不会改变协议。直接使用 Codex 时，可参考以下配置：

```toml
model_provider = "qoder"
model = "gfmodel"
model_reasoning_effort = "max"
web_search = "disabled"

[model_providers.qoder]
name = "QoderGateway CN"
base_url = "http://127.0.0.1:5050/v1"
wire_api = "responses"
env_key = "QODER_GATEWAY_API_KEY"
```

在启动 Codex 的环境中设置 `QODER_GATEWAY_API_KEY` 为自己的网关 Key。保持原有文件权限、审批和沙箱设置；网关只返回工具调用，本地执行权限仍由客户端控制。这里关闭内置 `web_search`，因为当前网关没有实现该工具类型。

### Responses 请求示例

```bash
curl http://127.0.0.1:5050/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $QODER_GATEWAY_API_KEY" \
  -d '{
    "model": "gfmodel",
    "input": "有3个红球、2个蓝球，至少抽几个才能保证抽到红球？",
    "reasoning": {"effort": "max"},
    "store": false,
    "stream": true
  }'
```

非流式响应的 `output` 包含消息、思考摘要及工具调用，顶层 `usage` 使用 `input_tokens`、`output_tokens`、`total_tokens`，以及 `input_tokens_details.cached_tokens`、`output_tokens_details.reasoning_tokens` 等上游提供的详情。流式响应返回 `response.created`、输出项与文本/思考增量、工具输入事件，最后以 `response.completed`、`response.incomplete` 或 `response.failed` 结束。

工具适配支持 `function`、`custom` 自由文本工具和 `namespace`：`functions.exec`、`functions.apply_patch` 等自由文本输入会恢复为 `custom_tool_call`，保留 `name`、`namespace` 和 `call_id`，后续接收 `custom_tool_call_output`。工具可在顶层 `tools` 中声明，也可由 `input` 中的 `additional_tools` 提供；重复历史声明会合并，并采用同名工具的最新定义。`configuration_update` 中的思考配置和客户端已经执行的 `tool_search_output` 中的工具声明也会处理。

支持 Codex 多代理历史中的明文 `agent_message`：保留 `author`、`recipient`、正文和消息顺序，转换为带发送者/接收者标识的 `user` 上下文消息。代理消息不会被提升为 `system` 或 `developer` 指令，也不会替代工具结果的 `call_id`。Qoder 无法解码 OpenAI 的 `encrypted_content`，含加密片段的代理消息会明确返回 `400`，需要客户端提供明文 `input_text`。

### Chat Completions 的 usage 与思考文本

原 `/v1/chat/completions` 接口继续可用。非流式回答和思考文本分别位于 `choices[0].message.content`、`choices[0].message.reasoning_content`，实际计数位于顶层 `usage`。流式思考文本位于 `choices[0].delta.reasoning_content`；如需流式 usage，在请求中添加：

```json
{
  "stream": true,
  "stream_options": {"include_usage": true}
}
```

网关会在 `[DONE]` 前发送一个 `choices: []` 的 usage chunk。`completion_tokens` 已包含思考 token，不再额外相加；累计 usage 快照不会重复累加，上游未提供计数时不伪造全零值。`reasoning_content` 是兼容扩展字段，客户端需支持它；Responses 则将上游思考文本作为 reasoning summary 返回，不伪造 OpenAI 的加密思考状态。

Chat Completions 的 `reasoning_effort` 和 Responses 的 `reasoning.effort` 会原样传递，`max` 不会自动改成 `xhigh`、`none` 或 `low`。显式请求参数优先于历史配置；没有提供该字段时沿用默认 `none`，不支持关闭思考的模型应显式选择可用档位。上游可能拒绝某档，或让不同档位产生相近的实际 token 数。Sub2API 等中转的日志标签也可能按模型名称归类，判断实际参数请核对网关入站和上游请求日志。

### 当前兼容范围

这是面向文本与工具调用的 Responses 适配，不是完整的 OpenAI 平台实现：

- 使用 `store=false` 并在 `input` 中传递完整对话历史；不支持 `previous_response_id`、服务端历史查询/删除、后台响应和服务端 compaction。
- 不支持原生 `web_search`、图像/文件输入、服务端执行的 `tool_search` 或结构化 JSON 输出；不支持的类型会明确返回 `400`。客户端已执行工具搜索后的工具声明可以读取。
- 自由文本工具的 grammar 会加入工具说明；上游没有原生语法约束采样保证。工具输入需要等 JSON 参数完整后再解码，长代码的工具调用可能延后出现。
- 客户端工具说明、模型生成代码与本地权限仍影响实际执行。模型传错参数类型或本地策略拒绝执行，与网关是否保留工具入口需要分别判断。

实际验证覆盖 Codex 0.159.2 的自由文本执行入口、`additional_tools`、流式/非流式和多轮工具结果；离线测试覆盖关键转换边界。

### 工具诊断日志

两种 API 请求都带有 `X-Qoder-Trace-Id` 响应头。默认诊断日志位于运行用户的 `~/.qoder/diagnostics/tool-trace.jsonl`，按 5 MiB 轮转并保留 3 个备份，关联客户端请求、上游请求、上游响应和客户端响应。

日志只保存工具名称/类型、声明位置、消息角色、字符长度、思考强度和响应状态；`input_agent_messages` 记录代理消息的位置、发送者/接收者标识、内容类型和字符长度。不保存提示词正文、代理消息正文、思考文本、工具参数值或认证头。排查时应将这些元数据与客户端执行结果对应；HTTP 200 和工具调用事件本身不能证明本地命令已成功执行。

### 离线回归验证

安装依赖后，在项目根目录执行：

```bash
uv run python -m unittest discover -s tests -v
```

这组测试使用模拟上游事件，不访问 Qoder，不执行模型生成的工具，也不读写账号数据库。

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
│   ├── responses_api.py    # Responses 请求、事件、工具与 usage 适配
│   ├── diagnostics.py      # 请求链路工具元数据日志
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
├── tests/                  # 无需上游凭据的转换回归测试
└── pyproject.toml          # 项目配置
```

## License

MIT
