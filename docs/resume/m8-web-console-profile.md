# Mini CodeAgent M8 简历与面试说明

## 项目介绍

Mini CodeAgent 是一个使用 Python 从零实现的 Coding Agent Harness。项目实现了
Model -> ToolCall -> ToolResult -> Model 的有界循环，并把 Workspace、文件/Git/命令工具、
Policy、人工审批、上下文预算和 Provider Adapter 拆成可测试模块。M8 在不改动核心运行时
的前提下增加本地 Web 工作台，用于提交项目任务、观察运行活动、审批副作用操作和取消任务。

## 技术栈

- Python 3.12/3.13、asyncio、强类型 Protocol
- FastAPI、Uvicorn、Pydantic
- Server-Sent Events、REST、HTML/CSS、原生 JavaScript
- OpenAI-compatible Chat Completions、SiliconFlow 配置
- Typer、httpx、Pytest、pytest-asyncio
- Ruff、Pyright、GitHub Actions

## 30 秒面试介绍

“我实现了一个 Python Mini Coding Agent，不只是调用一次大模型，而是完整实现有界
Agent Loop、Tool Calling、工作区边界和有副作用工具审批。为了让运行过程可观察，我又做了
一个只绑定本机回环地址的 Web 工作台。FastAPI 负责启动、审批和取消接口，SSE 推送模型与
工具生命周期事件；命令或写文件时，Agent 通过 asyncio Future 暂停，用户查看资源、argv
和 diff 后只能批准一次。API Key 和 Workspace 都留在服务端，前端只接收必要状态并用文本
节点渲染模型内容。测试用 Scripted Provider 和 ASGITransport，不依赖真实额度。”

## 项目亮点

### 1. 核心运行时与 Web 交互解耦

**为什么使用：** CLI 和 Web 的输入输出方式不同，但 Provider、Tool、Policy 和 Agent Loop
不应该复制两套。

**技术实现：** `run_task()` 作为 Composition Root；Web 层只实现 `EventSink` 和
`ApprovalHandler` 两个协议，再通过依赖注入调用已有 Runtime。

**实现功能：** 同一套 Agent 能从终端或浏览器运行，并共享相同工具治理语义。

**解决问题：** 避免界面层绕过 Policy，也降低新增交互入口时的重复代码和行为漂移。

**代码证据：** `src/mini_code_agent/application.py`、
`src/mini_code_agent/web/manager.py`、`src/mini_code_agent/web/app.py`。

### 2. SSE 可观察运行与有界事件重放

**为什么使用：** 运行事件主要是服务端单向推送，WebSocket 的双向协议复杂度在这里没有收益。

**技术实现：** Manager 为事件分配单调递增 sequence，使用有界 deque 保留事件；
FastAPI `StreamingResponse` 输出具名 SSE，浏览器用 `EventSource` 消费并按序号重连。

**实现功能：** 展示模型调用、Tool 开始/结束、Token 用量、完成/失败/取消状态。

**解决问题：** 终端黑盒运行变成可追踪时间线；短暂断线后可恢复最近事件，同时限制内存增长。

**代码证据：** `WebRunManager.subscribe()`、`run_events()`、`static/app.js`。

### 3. Future 驱动的一次性人工审批

**为什么使用：** 模型提出命令或写入动作不等于用户授权，Web 请求和 Agent 协程又是两个独立
控制流。

**技术实现：** 每个 ToolCall 创建一个 `asyncio.Future[bool]`；审批事件包含有界
ActionPreview；REST 决策先从 pending map 移除 Future 再完成它，重复和过期决定返回冲突。

**实现功能：** Agent 在副作用执行前暂停，用户查看工具、风险、原因、资源、argv 和 diff 后
允许一次或拒绝；取消任务会拒绝并清理全部待审批。

**解决问题：** 防止模型自授权、重复点击和过期审批触发工具，保证取消不会遗留悬挂协程。

**代码证据：** `_WebApprovalHandler`、`decide_approval()`、`cancel()` 及 Manager 单元测试。

### 4. 本地 Web 的服务端信任边界

**为什么使用：** Coding Agent 拥有本地文件和进程能力，普通“localhost 页面”仍需防止
远程绑定、跨站请求和模型内容注入。

**技术实现：** CLI 拒绝非 loopback Host；Workspace 启动时固定；修改接口校验随机请求令牌
和 loopback Origin；Key 使用服务端 `SecretStr`/环境变量；设置 CSP；动态内容只写
`textContent`。

**实现功能：** 浏览器可以操作 Agent，但不能选择任意服务器路径、读取 Key 或从外部站点静默
发起批准请求。

**解决问题：** 缩小本地管理界面的攻击面，并明确 Web 治理与 OS Sandbox 的边界。

**代码证据：** `create_web_app()` Middleware/依赖、`web()` Host 校验、静态资源契约测试。

### 5. 确定性的无凭证测试

**为什么使用：** 真实模型存在费用、网络波动和非确定性，不适合作为默认 CI 前提。

**技术实现：** Manager 注入 async runner；API 使用 `httpx.ASGITransport`；核心 Agent 使用
Scripted Provider/MockTransport；前端用静态契约和浏览器响应式检查。

**实现功能：** 覆盖运行冲突、事件顺序、密钥脱敏、审批、取消、CSRF、Origin、SSE 和 CLI。

**解决问题：** 在不消耗 Token、不上传凭证的情况下验证控制流和协议边界。

**代码证据：** `tests/unit/web/`、`tests/cli/test_cli.py`。

## 诚实边界

- 不描述为 Claude Code 的完整替代品；
- 不声称是多用户或可公网部署的 Agent 平台；
- 不把 loopback、Workspace 或 Policy 描述为 OS Sandbox；
- 不声称默认 CI 验证了真实 SiliconFlow 账户；
- 不编造效率、准确率或成本下降百分比；
- 图像生成尚未接入当前 Agent 工具链。
