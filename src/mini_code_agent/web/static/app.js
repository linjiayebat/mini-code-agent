"use strict";

const state = {
  bootstrap: null,
  runId: null,
  lastSequence: 0,
  eventSource: null,
  pendingApproval: null,
  activityCount: 0,
};

const elements = {
  version: document.querySelector("#version-label"),
  providerStatus: document.querySelector("#provider-status"),
  provider: document.querySelector("#provider-label"),
  model: document.querySelector("#model-label"),
  workspace: document.querySelector("#workspace-label"),
  sessionState: document.querySelector("#session-state"),
  runState: document.querySelector("#run-state"),
  transcript: document.querySelector("#transcript"),
  emptyState: document.querySelector("#empty-state"),
  composer: document.querySelector("#composer"),
  prompt: document.querySelector("#prompt-input"),
  runButton: document.querySelector("#run-button"),
  cancelButton: document.querySelector("#cancel-button"),
  activityList: document.querySelector("#activity-list"),
  activityEmpty: document.querySelector("#activity-empty"),
  activityCount: document.querySelector("#activity-count"),
  activityTab: document.querySelector("#activity-tab"),
  activityPanel: document.querySelector("#activity-panel"),
  changesTab: document.querySelector("#changes-tab"),
  changesPanel: document.querySelector("#changes-panel"),
  approvalPanel: document.querySelector("#approval-panel"),
  approvalRisk: document.querySelector("#approval-risk"),
  approvalTitle: document.querySelector("#approval-title"),
  approvalSummary: document.querySelector("#approval-summary"),
  approvalReason: document.querySelector("#approval-reason"),
  approvalResources: document.querySelector("#approval-resources"),
  approvalCommandRow: document.querySelector("#approval-command-row"),
  approvalCommand: document.querySelector("#approval-command"),
  approveButton: document.querySelector("#approve-button"),
  rejectButton: document.querySelector("#reject-button"),
  changesEmpty: document.querySelector("#changes-empty"),
  diffViewer: document.querySelector("#diff-viewer"),
  inspector: document.querySelector("#inspector"),
  inspectorToggle: document.querySelector("#inspector-toggle"),
  inspectorClose: document.querySelector("#inspector-close"),
  toastRegion: document.querySelector("#toast-region"),
};

function setText(element, value, fallback = "") {
  element.textContent = value === null || value === undefined ? fallback : String(value);
}

function setRunState(status, label) {
  elements.runState.dataset.state = status;
  setText(elements.runState, label);
  const running = status === "running";
  elements.prompt.disabled = running;
  elements.runButton.disabled = running || !state.bootstrap?.api_key_configured;
  elements.cancelButton.disabled = !running;
  setText(elements.sessionState, label);
}

function showToast(message) {
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = message;
  elements.toastRegion.append(toast);
  window.setTimeout(() => toast.remove(), 4500);
}

function addMessage(role, text, isError = false) {
  elements.emptyState.hidden = true;
  const article = document.createElement("article");
  article.className = `message ${role}${isError ? " error" : ""}`;

  const label = document.createElement("div");
  label.className = "message-label";
  const marker = document.createElement("span");
  marker.setAttribute("aria-hidden", "true");
  const labelText = document.createElement("strong");
  labelText.textContent = role === "user" ? "你" : "Agent";
  label.append(marker, labelText);

  const body = document.createElement("pre");
  body.className = "message-body";
  body.textContent = text;
  article.append(label, body);
  elements.transcript.append(article);
  elements.transcript.scrollTop = elements.transcript.scrollHeight;
}

function addActivity(title, detail, tone = "") {
  elements.activityEmpty.hidden = true;
  const item = document.createElement("li");
  item.className = `activity-item ${tone}`.trim();

  const symbol = document.createElement("span");
  symbol.className = "activity-symbol";
  symbol.textContent = tone === "success" ? "✓" : tone === "error" ? "!" : "•";

  const copy = document.createElement("div");
  copy.className = "activity-copy";
  const heading = document.createElement("strong");
  heading.textContent = title;
  const description = document.createElement("small");
  description.textContent = detail;
  copy.append(heading, description);
  item.append(symbol, copy);
  elements.activityList.append(item);

  state.activityCount += 1;
  setText(elements.activityCount, state.activityCount);
  elements.activityPanel.scrollTop = elements.activityPanel.scrollHeight;
}

function showTab(name) {
  const activity = name === "activity";
  elements.activityTab.classList.toggle("active", activity);
  elements.activityTab.setAttribute("aria-selected", String(activity));
  elements.activityPanel.hidden = !activity;
  elements.changesTab.classList.toggle("active", !activity);
  elements.changesTab.setAttribute("aria-selected", String(!activity));
  elements.changesPanel.hidden = activity;
}

function showApproval(payload) {
  const preview = payload.preview;
  state.pendingApproval = preview.tool_call_id;
  elements.approvalPanel.hidden = false;
  setText(elements.approvalRisk, preview.risk);
  setText(elements.approvalTitle, preview.tool_name);
  setText(elements.approvalSummary, preview.summary);
  setText(elements.approvalReason, preview.reason);
  setText(elements.approvalResources, (preview.resources || []).join("\n"), "无");
  const command = preview.command || [];
  elements.approvalCommandRow.hidden = command.length === 0;
  setText(elements.approvalCommand, command.join(" "));
  elements.approveButton.disabled = false;
  elements.rejectButton.disabled = false;

  const diff = preview.diff || "";
  elements.changesEmpty.hidden = diff.length > 0;
  elements.diffViewer.hidden = diff.length === 0;
  setText(elements.diffViewer, diff);
  addActivity("等待操作审批", preview.summary, "pending");
  elements.inspector.classList.add("open");
  elements.inspectorToggle.setAttribute("aria-expanded", "true");
}

function clearApproval() {
  state.pendingApproval = null;
  elements.approvalPanel.hidden = true;
  elements.approveButton.disabled = false;
  elements.rejectButton.disabled = false;
}

function describeAgentEvent(event) {
  const type = event.type;
  if (type === "run_started") {
    return ["Agent 已启动", `最多 ${event.max_turns} 轮`];
  }
  if (type === "model_started") {
    return ["模型正在思考", `第 ${event.turn} 轮`];
  }
  if (type === "model_completed") {
    const usage = event.usage || {};
    return [
      "模型响应完成",
      `${event.finish_reason} · 输入 ${usage.input_tokens || 0} / 输出 ${usage.output_tokens || 0}`,
    ];
  }
  if (type === "tool_started") {
    return [`调用工具 ${event.tool_name}`, `${event.side_effect} · 第 ${event.turn} 轮`];
  }
  if (type === "tool_completed") {
    return [
      `工具完成 ${event.tool_name}`,
      event.is_error ? "执行返回错误" : "执行成功",
      event.is_error ? "error" : "success",
    ];
  }
  if (type === "context_compacted") {
    return ["上下文已压缩", `省略 ${event.omitted_messages} 条消息`];
  }
  if (type === "run_stopped") {
    return [
      "Agent 运行结束",
      `${event.reason} · ${event.turns} 轮 · ${event.tool_calls} 次工具调用`,
      event.error ? "error" : "success",
    ];
  }
  return [type, "Agent 生命周期事件"];
}

function stopEventStream() {
  if (state.eventSource !== null) {
    state.eventSource.close();
    state.eventSource = null;
  }
}

function handleEvent(envelope) {
  state.lastSequence = Math.max(state.lastSequence, envelope.sequence);
  if (envelope.type === "agent_event") {
    const description = describeAgentEvent(envelope.payload.event);
    addActivity(description[0], description[1], description[2] || "");
    return;
  }
  if (envelope.type === "approval_required") {
    showApproval(envelope.payload);
    return;
  }
  if (envelope.type === "approval_resolved") {
    clearApproval();
    addActivity(
      envelope.payload.approved ? "操作已允许" : "操作已拒绝",
      envelope.payload.tool_call_id,
      envelope.payload.approved ? "success" : "error",
    );
    return;
  }
  if (envelope.type === "web_run_completed") {
    clearApproval();
    const finalText = envelope.payload.final_text || envelope.payload.error || "运行已结束。";
    addMessage("assistant", finalText, Boolean(envelope.payload.error));
    addActivity(
      "任务完成",
      `${envelope.payload.turns} 轮 · ${envelope.payload.tool_calls} 次工具调用`,
      envelope.payload.error ? "error" : "success",
    );
    setRunState(envelope.payload.error ? "failed" : "completed", "已完成");
    stopEventStream();
    state.runId = null;
    return;
  }
  if (envelope.type === "web_run_failed") {
    clearApproval();
    addMessage("assistant", envelope.payload.message, true);
    addActivity("任务失败", envelope.payload.message, "error");
    setRunState("failed", "失败");
    stopEventStream();
    state.runId = null;
    return;
  }
  if (envelope.type === "web_run_cancelled") {
    clearApproval();
    addActivity("任务已停止", "运行由用户取消", "error");
    setRunState("idle", "已停止");
    stopEventStream();
    state.runId = null;
  }
}

function connectEvents(runId) {
  stopEventStream();
  const source = new EventSource(
    `/api/runs/${encodeURIComponent(runId)}/events?after=${state.lastSequence}`,
  );
  state.eventSource = source;

  const eventNames = [
    "web_run_started",
    "agent_event",
    "approval_required",
    "approval_resolved",
    "web_run_completed",
    "web_run_failed",
    "web_run_cancelled",
  ];
  for (const eventName of eventNames) {
    source.addEventListener(eventName, (event) => {
      try {
        handleEvent(JSON.parse(event.data));
      } catch {
        showToast("收到无法解析的运行事件。");
      }
    });
  }
  source.onerror = () => {
    if (state.runId !== null) {
      addActivity("连接正在恢复", "等待本地事件流重新连接", "pending");
    }
  };
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  if (options.method && options.method !== "GET") {
    headers.set("X-Mini-Code-Agent-Token", state.bootstrap.csrf_token);
  }
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    let message = `请求失败 (${response.status})`;
    try {
      const payload = await response.json();
      message = payload.detail || message;
    } catch {
      // Keep the bounded public fallback.
    }
    throw new Error(message);
  }
  return response.json();
}

async function startRun(prompt) {
  setRunState("running", "运行中");
  state.lastSequence = 0;
  state.activityCount = 0;
  elements.activityList.replaceChildren();
  elements.activityEmpty.hidden = false;
  setText(elements.activityCount, "0");
  addMessage("user", prompt);
  addActivity("任务已提交", "正在初始化本地 Agent", "pending");
  try {
    const snapshot = await api("/api/runs", {
      method: "POST",
      body: JSON.stringify({ prompt }),
    });
    state.runId = snapshot.run_id;
    connectEvents(snapshot.run_id);
  } catch (error) {
    setRunState("failed", "启动失败");
    addMessage("assistant", error.message, true);
    showToast(error.message);
  }
}

async function decideApproval(approved) {
  if (state.runId === null || state.pendingApproval === null) {
    return;
  }
  elements.approveButton.disabled = true;
  elements.rejectButton.disabled = true;
  const toolCallId = state.pendingApproval;
  try {
    await api(
      `/api/runs/${encodeURIComponent(state.runId)}/approvals/${encodeURIComponent(toolCallId)}`,
      {
        method: "POST",
        body: JSON.stringify({ approved }),
      },
    );
  } catch (error) {
    showToast(error.message);
    clearApproval();
  }
}

async function cancelRun() {
  if (state.runId === null) {
    return;
  }
  elements.cancelButton.disabled = true;
  try {
    await api(`/api/runs/${encodeURIComponent(state.runId)}/cancel`, {
      method: "POST",
    });
  } catch (error) {
    showToast(error.message);
    elements.cancelButton.disabled = false;
  }
}

async function bootstrap() {
  try {
    const response = await fetch("/api/bootstrap", { cache: "no-store" });
    if (!response.ok) {
      throw new Error("无法读取本地运行配置。");
    }
    state.bootstrap = await response.json();
    setText(elements.version, `v${state.bootstrap.version}`);
    setText(elements.provider, state.bootstrap.provider);
    setText(elements.model, state.bootstrap.model, "未配置模型");
    setText(elements.workspace, state.bootstrap.workspace);
    elements.providerStatus.classList.toggle(
      "ready",
      state.bootstrap.api_key_configured && Boolean(state.bootstrap.model),
    );
    elements.providerStatus.classList.toggle(
      "error",
      !state.bootstrap.api_key_configured || !state.bootstrap.model,
    );
    setText(
      elements.provider,
      state.bootstrap.api_key_configured ? state.bootstrap.provider : "服务端密钥未配置",
    );
    elements.runButton.disabled =
      !state.bootstrap.api_key_configured || !state.bootstrap.model;
    if (!state.bootstrap.api_key_configured || !state.bootstrap.model) {
      showToast("请在启动服务前配置模型和服务端环境变量。");
    }
    if (state.bootstrap.active_run) {
      state.runId = state.bootstrap.active_run.run_id;
      setRunState("running", "运行中");
      connectEvents(state.runId);
    }
  } catch (error) {
    elements.providerStatus.classList.add("error");
    setText(elements.provider, "本地服务不可用");
    elements.runButton.disabled = true;
    showToast(error.message);
  }
}

elements.composer.addEventListener("submit", (event) => {
  event.preventDefault();
  const prompt = elements.prompt.value.trim();
  if (prompt.length === 0 || state.runId !== null) {
    return;
  }
  elements.prompt.value = "";
  startRun(prompt);
});

elements.prompt.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && event.ctrlKey) {
    event.preventDefault();
    elements.composer.requestSubmit();
  }
});

elements.cancelButton.addEventListener("click", cancelRun);
elements.approveButton.addEventListener("click", () => decideApproval(true));
elements.rejectButton.addEventListener("click", () => decideApproval(false));
elements.activityTab.addEventListener("click", () => showTab("activity"));
elements.changesTab.addEventListener("click", () => showTab("changes"));
elements.inspectorToggle.addEventListener("click", () => {
  const opened = elements.inspector.classList.toggle("open");
  elements.inspectorToggle.setAttribute("aria-expanded", String(opened));
});
elements.inspectorClose.addEventListener("click", () => {
  elements.inspector.classList.remove("open");
  elements.inspectorToggle.setAttribute("aria-expanded", "false");
});

window.addEventListener("beforeunload", stopEventStream);
bootstrap();
