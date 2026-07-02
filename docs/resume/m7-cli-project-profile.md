# Mini CodeAgent M7 简历与面试说明

## 项目介绍

Mini CodeAgent 是一个从零实现、Framework-light、Provider-neutral 的 Python Coding Agent。
项目将大模型 Tool Calling、受限工作区、工具权限、人工审批、上下文预算、Trace/Checkpoint、
MCP、Subagent 和 Worktree candidate 拆成可测试模块。M7 在此基础上增加 Provider-backed
CLI，使用户可以通过 SiliconFlow 等 OpenAI-compatible 服务直接执行代码分析和修改任务。

## 技术栈

- Python 3.12/3.13、asyncio、强类型 Protocol
- Pydantic、Pydantic Settings
- Typer、Rich
- httpx、OpenAI-compatible Chat Completions、Anthropic Messages
- JSON Schema Draft 2020-12
- Pytest、pytest-asyncio、httpx MockTransport
- Ruff、Pyright、GitHub Actions

## 面试介绍版本

“我做了一个 Python Mini Coding Agent。核心不是简单调用一次大模型，而是实现
Model -> ToolCall -> ToolResult -> Model 的有界执行循环，并把文件、Git 和本地命令封装成
受治理工具。M7 增加了应用组合根和 Typer CLI，可以切换 OpenAI-compatible 或 Anthropic
Provider，也可以直接接硅基流动。读操作默认允许，写文件和执行命令必须先展示资源、argv 或
diff，再由用户批准；非交互模式全部 fail closed。真实密钥只从环境变量读取，测试使用
MockTransport 和 ScriptedProvider，不消耗线上额度。”

## 项目亮点

### 1. Provider-neutral 的真实模型接入

**为什么使用：** 避免 Agent 核心绑定某一家模型厂商，也便于利用不同平台的额度和模型能力。

**技术实现：** 通过统一 `ModelProvider` 协议隔离内部消息模型与厂商 wire protocol；
`build_provider()` 根据强类型配置创建 OpenAI-compatible 或 Anthropic Adapter。硅基流动只需
配置 model、base URL 和环境变量 API Key。

**实现功能：** 同一套 Agent Runtime 可以调用不同 Provider，并支持 Tool Calling。

**解决问题：** 消除业务循环中的厂商条件分支，降低更换模型服务时的修改范围。

**证据：** `src/mini_code_agent/application.py`、
`tests/unit/test_application.py::test_openai_compatible_provider_uses_siliconflow_endpoint`。

### 2. 显式 Composition Root

**为什么使用：** SDK 模块齐全不等于产品可运行；必须有一个地方明确管理依赖、资源和安全策略。

**技术实现：** `application.py` 统一创建 Provider、Workspace、Tool Registry、Policy、
Approval 和 AgentRuntime，并在 `finally` 中关闭 Provider Client。

**实现功能：** `run` 和 `chat` 不需要重复装配代码，测试可以注入 ScriptedProvider。

**解决问题：** 避免 CLI、Web 或测试各自复制装配逻辑，减少策略不一致和资源泄漏。

**证据：** `run_task()` 及成功/失败关闭资源测试。

### 3. 模型不可自授权的工具治理

**为什么使用：** Coding Agent 会修改文件和执行命令，模型输出不能直接等价为用户授权。

**技术实现：** Tool Definition 标记 side effect；Policy 产生 allow/ask/deny；写入沿用默认
ASK，命令执行从默认 DENY 提升为 CLI 明确 ASK；`TerminalApprovalHandler` 展示 ActionPreview
后才返回决定。

**实现功能：** 只读分析自动执行，写文件和 argv 命令逐次审批，non-interactive 模式自动拒绝。

**解决问题：** 阻止模型静默落盘或执行本地进程，并为用户提供可判断的资源和 diff 信息。

**证据：** `build_tool_executor()`、`TerminalApprovalHandler` 及审批测试。

### 4. 密钥安全与可测试的线上协议

**为什么使用：** API Key 泄漏和 CI 消耗真实 Token 都是 Agent 项目的常见工程风险。

**技术实现：** Key 使用 `SecretStr` 和环境变量；诊断只输出 configured 布尔值；HTTP 测试使用
`httpx.MockTransport` 验证真实 URL/Header/Response parsing，不连接公网。

**实现功能：** 能验证 SiliconFlow 接口兼容性，同时保持默认测试确定性。

**解决问题：** 防止密钥进入仓库、日志和测试报告，也避免 CI 受网络、额度和模型漂移影响。

**证据：** `AppSettings.safe_dict()`、配置测试和 SiliconFlow endpoint 测试。

### 5. 稳定的 CLI 错误与退出码

**为什么使用：** Agent 可能因配置、鉴权、限流或工具边界停止，脚本和用户需要区分失败类型。

**技术实现：** 配置/组合错误返回退出码 2；Agent 未完成返回 1；完成返回 0；终端只显示 bounded
public error 和运行摘要。

**实现功能：** 既适合人工使用，也可被 PowerShell、CI 或其他进程可靠调用。

**解决问题：** 避免所有错误都变成 Traceback 或模糊的非零状态。

**证据：** `tests/cli/test_cli.py` 中 run 成功、配置错误和 Provider 错误测试。

## 诚实边界

- 不描述为 Claude Code 的完整替代品；当前没有全屏 TUI 或 Web UI。
- 不声称 `chat` 已有跨 run 的持久对话记忆。
- 不声称默认 CI 已验证真实 SiliconFlow 服务；真实 smoke 需要本地凭证。
- 不把 Workspace/Policy 描述为 OS sandbox。
- 不编造 Token、准确率、开发效率等百分比提升；没有 benchmark 就不写量化结果。
