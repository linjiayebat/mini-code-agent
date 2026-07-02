# M8 学习笔记：把 Agent Runtime 变成可交互的本地 Web 产品

## 1. 本阶段解决的问题

M7 已经能通过命令行调用真实模型，但运行过程、工具活动、审批和 diff 都依赖终端展示。
M8 增加一个本地 Web 适配层，不重写 Agent Runtime：

```text
浏览器
  -> FastAPI REST（启动、审批、取消）
  -> WebRunManager
  -> run_task()
  -> AgentRuntime -> Provider / Tool / Policy
  -> EventSink / ApprovalHandler
  -> SSE -> 浏览器活动面板
```

产品目标是让用户看见 Agent 正在做什么，并在有副作用的动作执行前做决定。Web 层是
交互适配器，不是新的 Agent 框架。

## 2. 前置知识与本项目知识点

| 学习主题 | 先掌握什么 | 在项目中的落点 |
|---|---|---|
| Python 异步 | coroutine、Task、Future、取消传播 | 后台 Agent run、待审批 Future、取消与清理 |
| FastAPI | 路由、依赖、Middleware、StreamingResponse | REST、CSRF 校验、Origin 校验、SSE |
| Pydantic | frozen model、字段上下界、序列化 | Web 请求、运行快照、事件信封 |
| 浏览器基础 | fetch、EventSource、DOM API、响应式 CSS | 启动任务、消费事件、安全渲染、移动端抽屉 |
| Agent Harness | EventSink、ApprovalHandler、Policy | 把已有运行时能力映射到 Web，而不绕过治理 |
| Web 安全 | secret boundary、CSRF、Origin、CSP、XSS | Key 留在服务端、随机令牌、文本节点渲染 |

建议边做边补，不需要先系统学完前端或 FastAPI。

## 3. 核心实现

### 3.1 WebRunManager

`WebRunManager` 是 Web 层的运行状态机：

- 一次只允许一个活跃任务，避免多个浏览器操作争用同一工作区；
- 使用递增 `sequence` 给事件排序，并在有界 `deque` 中保留最近事件；
- 浏览器断线后通过 `after` 序号重放事件；
- 完成、失败和取消都产生明确终态；
- 生命周期事件不包含用户 prompt、Tool 参数/结果或 API Key。

这与 Flink JobManager 的相似点是都管理任务生命周期和状态；差异是这里是单进程、
单活跃任务，没有分布式容错和 Checkpoint 语义。

### 3.2 Future 驱动的人工审批

当 `GovernedToolExecutor` 请求审批时，`WebApprovalHandler`：

1. 创建 `asyncio.Future[bool]`；
2. 发布有界 `approval_required` 事件；
3. Agent 协程等待 Future，不执行工具；
4. 浏览器通过 REST 提交允许或拒绝；
5. Manager 先移除 Future，再设置结果，保证决定只能使用一次。

这类似 Java 的 `CompletableFuture<Boolean>`：生产者暂停等待外部决策，另一个请求处理器
完成 Future。取消任务时所有待审批 Future 都会被拒绝并清理。

### 3.3 SSE 为什么适合这里

浏览器到服务端只有启动、审批和取消三个低频命令，服务端到浏览器则持续发送运行事件。
SSE 提供单向事件流、浏览器原生 `EventSource` 和自动重连，不需要为双向 WebSocket
协议增加额外状态。事件带序号，重连时可以从最后位置继续。

当前不是逐 Token 流式输出。Provider 完成后才展示最终文本，SSE 传输的是 Agent
生命周期和工具活动。

### 3.4 浏览器和服务端的信任边界

- CLI 启动时固定 Workspace，浏览器不能传入任意路径；
- CLI 只允许回环 Host，不能使用 `0.0.0.0` 暴露到局域网；
- API Key 只由服务端配置读取，bootstrap 只返回布尔状态；
- 修改请求必须携带进程随机令牌，并通过 loopback Origin 检查；
- 模型文本、命令、路径和 diff 通过 `textContent` 显示；
- CSP 禁止第三方脚本和页面嵌入。

这些措施降低本地浏览器攻击面，但 Workspace/Policy 仍不是 OS Sandbox。

## 4. Java 后端经验映射

| Java / 数据开发概念 | Python / M8 对应 |
|---|---|
| Spring MVC Controller | FastAPI 路由函数 |
| HandlerInterceptor / Filter | FastAPI Middleware 和依赖 |
| CompletableFuture | `asyncio.Future` |
| ExecutorService Future.cancel | `asyncio.Task.cancel()` 和取消传播 |
| WebFlux ServerSentEvent | `StreamingResponse` + `text/event-stream` |
| DTO + Bean Validation | frozen Pydantic model + Field 约束 |
| ConcurrentHashMap 中的运行状态 | event-loop 内的 run/pending 字典 |
| Flink event-time sequence / offset | WebEvent sequence 与断线重放 |
| SQL 权限审批 | Tool Policy + 一次性 ActionPreview 审批 |

Python 的关键差异是：同一事件循环中的共享状态通常不需要线程锁，但不能在协程中执行
阻塞 I/O；取消是协作式异常传播，必须在 `finally` 中清理资源。

## 5. 建议学习练习

1. 从 `POST /api/runs` 跟到 `AgentRuntime.run()`，画出对象创建和调用顺序。
2. 跟踪一次 `run_command`：Policy ASK -> Future -> 浏览器允许 -> Tool 执行。
3. 删除 CSRF Header 或改成外部 Origin，观察接口为什么返回 403。
4. 运行中刷新页面，解释 bootstrap 的 `active_run` 与 SSE `after` 如何恢复界面。
5. 为 Manager 增加事件保留边界测试，说明慢客户端不会让内存无限增长。
6. 对比 SSE 和 WebSocket，说明本项目为什么暂时不需要双向长连接。

## 6. 当前边界

- 仅支持本地单用户、单工作区、单活跃任务；
- 运行和会话只保存在内存中，进程退出后不恢复 Web 状态；
- 最终回答不是逐 Token 流式输出；
- 当前未把 Skills、MCP、Subagent、Worktree candidate 组合进 Web composition root；
- 图像生成 API 尚未接入，后续应作为受治理 Tool，而不是让浏览器直接持有 Key；
- 自动化测试使用 Mock/Scripted Provider，不声明已完成真实 SiliconFlow smoke。
