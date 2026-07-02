# M7 学习笔记：把 Agent SDK 组装成可使用的 CLI 产品

## 1. 这一阶段解决什么问题

M6b 之前，项目已经有 Agent Loop、Provider、Tool、Policy、Workspace 等核心模块，但用户
需要自己写 Python 代码才能把它们组装起来。M7 增加应用组合根和 `run/chat` 命令，让真实
模型、工作区和受治理工具形成一个可以直接体验的闭环。

关键链路是：

```text
CLI 参数/配置
  -> Provider Factory
  -> Workspace + Tool Registry
  -> Policy + Approval
  -> AgentRuntime
  -> OpenAI-compatible API
  -> ToolCall / ToolResult
  -> 最终回答
```

## 2. 需要掌握的知识点

### 2.1 Composition Root

`application.py` 是组合根。它不实现新的 Agent 算法，只负责创建并连接已有模块：

- 根据 `AppSettings` 创建 Provider；
- 根据工作区创建文件、Git 和命令工具；
- 用 `GovernedToolExecutor` 包装有副作用的工具；
- 创建 `AgentRuntime` 并执行任务；
- 在 `finally` 中关闭 Provider HTTP Client。

这和 Spring Boot 的配置类/Bean 装配类似。区别是 Python 项目没有依赖注入容器，依赖关系
由普通函数显式构造，因此调用顺序、所有权和测试替身更加直接。

### 2.2 OpenAI-compatible API

硅基流动使用 OpenAI-compatible Chat Completions 协议。项目只需要配置：

```text
provider = openai_compatible
model = 账户中实际可用的模型 ID
base_url = https://api.siliconflow.cn/v1
```

`OpenAICompatibleProvider` 会在 base URL 后追加 `chat/completions`。模型返回的
`tool_calls` 被规范化为项目内部 `ToolCall`，工具执行结果再转换回兼容协议消息。

### 2.3 配置与密钥边界

配置优先级仍然是：

```text
默认值 < TOML < MINI_CODE_AGENT_* 环境变量 < 显式 overrides
```

`provider/model/base_url` 可以进入 TOML；API Key 只建议使用环境变量。`SecretStr` 和
`safe_dict()` 防止 `doctor`、错误日志或诊断输出直接显示密钥。

### 2.4 同步 CLI 与异步 Agent

Typer 命令是同步函数，而 Provider、Tool 和 Agent Runtime 是异步接口。CLI 使用
`asyncio.run()` 建立每次任务的 event loop。这适合普通终端进程，但不能直接复制到已经拥有
event loop 的 Jupyter、FastAPI 请求处理或异步测试中；这些场景应直接 `await run_task()`。

### 2.5 Capability 与 Approval

CLI 注册工具不代表模型自动获得执行授权：

- Read/Search/Git status/diff 是只读能力，默认允许；
- Write/Edit 默认进入 `ASK`；
- Execute 默认是 `DENY`，M7 只为 `run_command` 增加明确的 `ASK` 规则；
- `--non-interactive` 不弹审批，而是拒绝所有 `ASK` 操作。

审批器展示工具名、风险、理由、资源、argv 和 bounded diff。模型只能提出动作，不能替用户
批准动作。

### 2.6 资源所有权

Provider 内部创建的 `httpx.AsyncClient` 必须关闭。`run_task()` 在成功、Provider 错误和
Runtime 失败时都进入 `finally`。测试通过可关闭的 `ScriptedProvider` 验证这一点。

## 3. Java / Flink / Spark SQL 经验映射

| 现有经验 | M7 对应概念 | 关键差异 |
|---|---|---|
| Spring `@Configuration` | `application.py` composition root | 依赖由普通函数显式创建，没有容器生命周期 |
| Spring `@ConfigurationProperties` | Pydantic `AppSettings` | 字段校验与环境变量合并由 Pydantic Settings 完成 |
| Feign/WebClient | `OpenAICompatibleProvider` + `httpx` | 响应不仅是 DTO，还可能驱动 ToolCall 状态机 |
| Java `try/finally` / `AutoCloseable` | Provider `aclose()` in `finally` | HTTP Client 是异步资源，需要 `await` |
| RBAC/接口鉴权 | Tool Policy allow/ask/deny | 授权对象是一次具体的模型动作，不是用户页面权限 |
| Flink operator graph | Provider -> Runtime -> Tool pipeline | Agent 路径由模型响应动态决定，不是预先固定 DAG |
| SQL dry-run / execution plan | `ActionPreview` | 预览只用于人工决策，不能替代执行前重验证 |

## 4. 建议练习

1. 用 `httpx.MockTransport` 抓取请求，确认 SiliconFlow URL、Authorization 和 model 字段。
2. 让模拟 Provider 先调用 `read_file`，再返回最终答案，画出完整消息序列。
3. 让模拟 Provider 请求 `write_file`，分别验证批准、拒绝和 non-interactive 三条路径。
4. 修改模型 ID 或 base URL，观察错误发生在配置期、网络期还是协议解析期。
5. 阅读 `tests/unit/test_application.py`，解释为什么真实 API 不应进入默认 CI。

## 5. 当前边界

- `chat` 是同一工作区上的交互任务循环，每条输入是独立 Agent run，不是持久对话。
- Runtime 当前使用非流式 `complete()`，终端展示生命周期事件，但不逐 Token 输出。
- CLI 尚未组合 SQLite Trace/Checkpoint、Skills、MCP、Subagent 和 Worktree candidate。
- 真实 SiliconFlow 调用需要用户本地 API Key，并会消耗账户额度。
- 命令治理和 Workspace boundary 不是 OS sandbox。

## 6. 当前验证证据

- uv 管理的 Python 3.13.14：1201 passed、13 个 Windows 权限/平台条件 skip。
- branch-aware package coverage：88.56%，高于 85% 门槛。
- Ruff format/check：通过。
- strict Pyright：0 errors。
- `httpx.MockTransport`：验证 SiliconFlow-compatible URL 和 Bearer Header。
- 真实 SiliconFlow API：未执行，因为验证环境没有配置用户 API Key。
