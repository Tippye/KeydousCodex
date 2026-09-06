"use strict";

const $ = (id) => document.getElementById(id);
const stateNames = {
  idle: "空闲", thinking: "正在思考", working: "正在工作",
  waiting: "等待输入", success: "回合结束", error: "出现错误", unknown: "未知"
};

const ui = {
  token: "",
  config: null,
  status: null,
  pets: [],
  models: [],
  sessions: [],
  dirty: new Set(),
  revisions: {},
  configBusy: false,
  polling: false,
  stopped: false,
  previewKey: "",
  previewTimer: 0,
  hookBusy: "",
  hookReview: null,
  hookFeedback: "",
  activeTab: "display",
  appearance: "system",
  mapping: null,
  mappingBank: "normal",
  mappingSlot: null,
  mappingBusy: false,
  mappingFeedback: ""
};

const APPEARANCE_KEY = "keyphore-keydous-appearance";

function setText(id, value) {
  const node = $(id);
  if (node) node.textContent = value == null || value === "" ? "未知" : String(value);
}

function toast(message, isError = false) {
  const item = document.createElement("div");
  item.className = `toast${isError ? " error" : ""}`;
  item.textContent = message;
  $("toast-stack").appendChild(item);
  window.setTimeout(() => item.remove(), 4200);
}

function showNotice(message, isError = false) {
  const notice = $("notice");
  notice.textContent = message || "";
  notice.classList.toggle("error", isError);
  notice.hidden = !message;
}

function savedAppearance() {
  try {
    const value = window.localStorage.getItem(APPEARANCE_KEY);
    return ["system", "light", "dark"].includes(value) ? value : "system";
  } catch (_) {
    return "system";
  }
}

function setAppearance(value, persist = true) {
  const appearance = ["system", "light", "dark"].includes(value) ? value : "system";
  ui.appearance = appearance;
  document.documentElement.dataset.appearance = appearance;
  document.querySelectorAll("#appearance-picker button").forEach((button) => {
    button.classList.toggle("active", button.dataset.appearance === appearance);
    button.setAttribute("aria-pressed", String(button.dataset.appearance === appearance));
  });
  if (persist) {
    try { window.localStorage.setItem(APPEARANCE_KEY, appearance); } catch (_) {}
  }
}

function showHome() {
  $("settings-view").hidden = true;
  $("home-view").hidden = false;
  $("settings-button").focus();
}

function openSettings(tab = "display") {
  $("home-view").hidden = true;
  $("settings-view").hidden = false;
  setSettingsTab(tab);
  $("settings-close-button").focus();
}

function setSettingsTab(tab) {
  const allowed = ["display", "device", "integration", "mapping", "general"];
  ui.activeTab = allowed.includes(tab) ? tab : "display";
  document.querySelectorAll("#settings-tabs button").forEach((button) => {
    const selected = button.dataset.tab === ui.activeTab;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-selected", String(selected));
  });
  document.querySelectorAll(".settings-page").forEach((page) => {
    const selected = page.dataset.page === ui.activeTab;
    page.classList.toggle("active", selected);
    page.hidden = !selected;
  });
  if (ui.activeTab === "mapping" && !ui.mappingBusy) readMapping();
}

async function api(path, options = {}) {
  const init = { ...options, headers: { ...(options.headers || {}) } };
  if (ui.token && options.method && options.method !== "GET") {
    init.headers["X-Bridge-Token"] = ui.token;
  }
  if (options.body && typeof options.body !== "string") {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, init);
  let payload = null;
  const type = response.headers.get("content-type") || "";
  if (type.includes("application/json")) payload = await response.json();
  if (!response.ok) throw new Error(payload?.error || `请求失败（${response.status}）`);
  return payload ?? {};
}

function option(value, label) {
  const node = document.createElement("option");
  node.value = value == null ? "" : String(value);
  node.textContent = label == null ? "" : String(label);
  return node;
}

function fillSelect(select, items, selected, placeholder, toValue, toLabel) {
  const current = select.value;
  select.replaceChildren();
  if (placeholder) select.appendChild(option("", placeholder));
  items.forEach((item) => select.appendChild(option(toValue(item), toLabel(item))));
  const desired = selected == null ? current : String(selected);
  if ([...select.options].some((item) => item.value === desired)) select.value = desired;
}

function markDirty(field) {
  ui.revisions[field] = (ui.revisions[field] || 0) + 1;
  ui.dirty.add(field);
  $("dirty-badge").hidden = false;
  schedulePreview();
}

function clearDirty() {
  ui.dirty.clear();
  $("dirty-badge").hidden = true;
}

function clearSavedFields(fields, revisions) {
  fields.forEach(field => {
    if ((ui.revisions[field] || 0) === (revisions[field] || 0)) ui.dirty.delete(field);
  });
  $("dirty-badge").hidden = !ui.dirty.size;
}

function currentDraft() {
  return {
    device_key: $("device-select").value,
    source: document.querySelector("#source-selector button.active")?.dataset.source || "manual",
    session_path: currentSessionPath(),
    pet_id: $("pet-select").value,
    layout: $("layout-select").value,
    background: $("background-text").value.toUpperCase(),
    rgb_enabled: $("rgb-toggle").checked
  };
}

function currentSessionPath() {
  const source = document.querySelector("#source-selector button.active")?.dataset.source;
  return source === "desktop" ? $("session-select").value : (source === "jsonl" ? $("jsonl-path").value.trim() : "");
}

function setSource(source, dirty = true) {
  document.querySelectorAll("#source-selector button").forEach((button) => {
    button.classList.toggle("active", button.dataset.source === source);
  });
  $("desktop-settings").classList.toggle("active", source === "desktop");
  $("jsonl-settings").classList.toggle("active", source === "jsonl");
  $("hooks-settings").classList.toggle("active", source === "hooks");
  document.querySelectorAll("#state-buttons button").forEach((button) => { button.disabled = source !== "manual"; });
  setText("manual-help", source === "manual" ? "点击任一状态检查宠物动画；只有点击上传才会写入键盘。" :
    (source === "hooks" ? "Hooks 只提供本地生命周期摘要；屏幕仍仅在点击上传时写入。" : "当前由所选来源只读跟随。切换到“手动”后才能测试状态。"));
  if (dirty) markDirty("source");
}

function applyBootstrap(data) {
  ui.token = data.token || "";
  ui.config = data.config || {};
  ui.status = data.status || {};
  ui.pets = Array.isArray(data.pets) ? data.pets : [];
  ui.models = Array.isArray(data.models) ? data.models : [];

  fillSelect($("pet-select"), ui.pets, ui.config.pet_id, "请选择宠物", (pet) => pet.id, (pet) => pet.name);
  $("layout-select").value = ui.config.layout === "dashboard" ? "dashboard" : "pet";
  const background = /^#[0-9a-f]{6}$/i.test(ui.config.background || "") ? ui.config.background : "#101820";
  $("background-color").value = background;
  $("background-text").value = background.toUpperCase();
  $("jsonl-path").value = ui.config.source === "jsonl" ? (ui.config.session_path || "") : "";
  $("rgb-toggle").checked = Boolean(ui.config.rgb_enabled);
  setSource(ui.config.source || "manual", false);
  refreshPetDescription();
  renderStatus(ui.status);
  clearDirty();
  schedulePreview(true);
}

function renderDevices(status) {
  const devices = Array.isArray(status.devices) ? status.devices : [];
  const selected = ui.dirty.has("device_key") ? $("device-select").value : (ui.config?.device_key || status.device?.key || "");
  fillSelect($("device-select"), devices, selected, devices.length ? "请选择设备" : "没有发现设备", (device) => device.key, (device) => device.name || device.key || "未命名设备");
  if (selected && !devices.some(device => String(device.key) === String(selected))) {
    $("device-select").appendChild(option(selected, `${selected}（当前不可用）`));
    $("device-select").value = selected;
  }
  if (status.device && !devices.some((device) => String(device.key) === String(status.device.key))) {
    $("device-select").appendChild(option(status.device.key || "", status.device.name || status.device.key || "当前设备"));
    if (!ui.dirty.has("device_key")) $("device-select").value = status.device.key || "";
  }
}

function triState(iconId, textId, value, yesText, noText, unknownText = "能力未知") {
  const icon = $(iconId);
  icon.classList.remove("yes", "no");
  if (value === true) { icon.textContent = "✓"; icon.classList.add("yes"); setText(textId, yesText); }
  else if (value === false) { icon.textContent = "×"; icon.classList.add("no"); setText(textId, noText); }
  else { icon.textContent = "?"; setText(textId, unknownText); }
}

function renderStatus(status) {
  ui.status = status || {};
  const device = ui.status.device;
  const connected = Boolean(device?.online && ui.status.iot?.connected);
  $("bridge-dot").className = `status-dot${ui.status.iot?.connected ? " online" : (ui.status.iot?.error ? " error" : "")}`;
  setText("bridge-label", ui.status.iot?.connected ? "本地桥接已就绪" : (ui.status.iot?.error || "等待本地 IoT 服务"));
  renderDevices(ui.status);

  setText("device-name", device?.name || "等待设备");
  setText("device-connection", device ? `${device.connection || "连接类型未知"} · ${device.online ? "在线" : "离线"}` : "尚未连接");
  setLockBadge("num-badge", "Num Lock", ui.status.locks?.num);
  setLockBadge("caps-badge", "Caps Lock", ui.status.locks?.caps);
  setText("battery-badge", Number.isInteger(device?.battery) ? `${device.battery}%` : "未知");

  const state = ui.status.state || "unknown";
  setText("state-label", stateNames[state] || "未知");
  setText("settings-state-label", stateNames[state] || "未知");
  setText("state-source", ui.status.source === "hooks" && ui.status.validity === "observed"
    ? "正在跟随 Codex 任务" : (ui.status.source_detail || sourceName(ui.status.source)));
  $("state-orb").dataset.state = state;
  document.querySelectorAll("#state-buttons button").forEach((button) => button.classList.toggle("active", button.dataset.state === state));

  const caps = device?.capabilities || {};
  triState("cap-upload-icon", "cap-upload-text", caps.upload, "支持写入用户动画槽", "此型号或当前连接尚未验证上传");
  triState("cap-overlay-icon", "cap-overlay-text", caps.native_overlay, "保留固件状态信息", "原生状态层尚未验证或未启用");
  triState("cap-dynamic-icon", "cap-dynamic-text", caps.dynamic_screen, "可实时刷新屏幕", "程序目前只提供手动屏幕上传");
  triState("cap-rgb-icon", "cap-rgb-text", caps.rgb, "支持状态灯光联动", "此型号或当前连接尚未验证 RGB");

  const staticScreen = caps.dynamic_screen === false;
  $("static-warning").hidden = !device || !staticScreen;
  $("upload-button").disabled = !connected || caps.upload !== true || Boolean(ui.status.upload?.active);
  $("slot-select").disabled = caps.upload !== true || Boolean(ui.status.upload?.active);
  $("connect-button").disabled = Boolean(ui.status.upload?.active);

  const rgbSupported = caps.rgb === true;
  $("rgb-toggle").disabled = !rgbSupported;
  $("rgb-toggle").closest("label").classList.toggle("disabled", !rgbSupported);
  if (!ui.dirty.has("rgb_enabled")) $("rgb-toggle").checked = Boolean(ui.status.rgb?.enabled ?? ui.config?.rgb_enabled);
  setText("rgb-detail", ui.status.rgb?.error || (ui.dirty.has("rgb_enabled") ? ($("rgb-toggle").checked ? "待保存：启用联动" : "待保存：关闭联动") : (rgbSupported ? (ui.status.rgb?.enabled ? "已启用" : "已关闭") : "此型号或连接尚未验证／未启用")));
  $("save-rgb-button").disabled = !rgbSupported || !ui.dirty.has("rgb_enabled") || Boolean(ui.status.upload?.active);
  $("restore-rgb-button").disabled = !device || caps.rgb !== true || !ui.status.rgb?.pending_restore || Boolean(ui.status.upload?.active);
  setText("restore-rgb-button", ui.status.rgb?.pending_restore ? "恢复原 RGB（已有记录）" : "无需恢复 RGB");

  renderUpload(ui.status.upload || {});
  renderIntegration(ui.status.integration || {});
  renderMacFn(ui.status.macos_fn || {});
  if (ui.status.notice) showNotice(ui.status.notice, false);
  schedulePreview();
}

function setLockBadge(id, label, value) {
  const badge = $(id);
  badge.textContent = value == null ? "未知" : (value ? "开启" : "关闭");
  badge.classList.toggle("active", value === true);
  badge.setAttribute("aria-label", `${label}：${badge.textContent}`);
}

function sourceName(source) {
  return { manual: "手动测试", hooks: "Keyphore Codex Hooks", desktop: "Codex 桌面任务", jsonl: "JSONL 文件" }[source] || "来源未知";
}

function formatVerifiedAt(value) {
  const date = new Date(Number(value) * 1000);
  return Number.isFinite(date.getTime()) ? date.toLocaleString("zh-CN", { hour12: false }) : "尚未校验";
}

function renderIntegration(integration) {
  const pill = $("hook-status-pill");
  pill.className = "hook-status-pill";
  let label = "未安装";
  let detail = integration.prepared ? "审阅文件已准备，尚未启用" : "尚未生成审阅文件";
  if (integration.installed && integration.trusted) {
    label = "上次验证已启用";
    detail = `上次核对为已安装且受信任 · ${formatVerifiedAt(integration.verified_at)}`;
    pill.classList.add("ready");
  } else if (integration.installed) {
    label = "待信任";
    detail = "插件已安装，但 Hooks 尚未全部启用并受信任";
    pill.classList.add("warning");
  } else if (integration.prepared) {
    label = "待启用";
    pill.classList.add("warning");
  }
  if (integration.last_error) pill.classList.add("error");
  pill.textContent = label;
  setText("hook-install-detail", detail);

  const observed = ui.status?.source === "hooks" && ui.status?.validity === "observed";
  const summary = observed && ui.status.summary && typeof ui.status.summary === "object" ? ui.status.summary : {};
  setText("hook-attention", observed ? Number(summary.attention || 0) : "—");
  setText("hook-execution", observed ? Number(summary.execution || 0) : "—");
  setText("hook-completion", observed ? Number(summary.completion || 0) : "—");
  $("hook-attention").closest(".hook-summary").classList.toggle("observed", observed);
  setText("hook-validity", observed ? "已观察到有效的本地 Hook 状态。计数按当前有效会话汇总。" : "尚未观察到有效 Hook 状态，注意力、执行和完成摘要不可用。");

  const feedback = integration.last_error || ui.hookFeedback;
  const feedbackNode = $("hook-feedback");
  feedbackNode.textContent = feedback || "";
  feedbackNode.hidden = !feedback;
  const busy = Boolean(ui.hookBusy);
  $("hook-review-button").disabled = busy;
  $("hook-refresh-button").disabled = busy;
  $("hook-disable-button").disabled = busy || !integration.installed;
  $("hook-remove-button").disabled = busy || !integration.installed;
  setText("hook-review-button", ui.hookBusy === "review" ? "正在准备审阅…" : (integration.installed ? "重新审阅并启用 Hooks" : "审阅并启用 Hooks"));
  setText("hook-refresh-button", ui.hookBusy === "refresh" ? "正在刷新…" : "刷新状态");
  setText("hook-disable-button", ui.hookBusy === "disable" ? "正在禁用…" : "禁用");
  setText("hook-remove-button", ui.hookBusy === "remove" ? "正在移除…" : "移除插件");
}

function appendTextElement(parent, tag, text, className = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = text == null ? "" : String(text);
  parent.appendChild(node);
  return node;
}

function renderHookReview(review) {
  const definitions = Array.isArray(review?.definitions) ? review.definitions : [];
  if (definitions.length !== 8) throw new Error("审阅结果必须包含恰好八条 Hook 定义");
  const validDefinitions = definitions.every((item) => item && typeof item.event === "string" &&
    typeof item.handler_type === "string" && typeof item.execution_mode === "string" &&
    Number.isFinite(Number(item.timeout_seconds)) && typeof item.command_plaintext === "string" &&
    (typeof item.command === "string" || typeof item.command_windows === "string"));
  const integrity = review?.runtime?.integrity;
  if (typeof review?.digest !== "string" || !review.digest || !validDefinitions ||
      typeof review?.runtime?.executable !== "string" || !Array.isArray(review?.runtime?.arguments) ||
      !integrity || typeof integrity !== "object" || !Object.keys(integrity).length ||
      !Array.isArray(review.privacy_fields)) throw new Error("Hook 审阅信息不完整，不能启用");
  ui.hookReview = review;
  setText("hook-review-digest", review.digest);
  setText("hook-runtime-executable", review.runtime.executable);
  setText("hook-runtime-arguments", JSON.stringify(review.runtime.arguments || []));

  const list = $("hook-definitions");
  list.replaceChildren();
  definitions.forEach((definition, index) => {
    const article = document.createElement("article");
    article.className = "hook-definition";
    const header = document.createElement("header");
    appendTextElement(header, "strong", `${String(index + 1).padStart(2, "0")} · ${definition.event || "未知事件"}`);
    appendTextElement(header, "span", `${definition.handler_type || "未知类型"} · ${definition.execution_mode || "未知模式"} · ${definition.timeout_seconds ?? "?"} 秒超时`);
    article.appendChild(header);
    appendTextElement(article, "label", "可读的完整命令");
    appendTextElement(article, "pre", definition.command_plaintext || "");
    appendTextElement(article, "label", "Codex 实际执行命令");
    appendTextElement(article, "pre", definition.command || definition.command_windows || "");
    list.appendChild(article);
  });

  const hashes = $("hook-runtime-hashes");
  hashes.replaceChildren();
  Object.entries(integrity).forEach(([path, digest]) => {
    const row = document.createElement("div");
    row.className = "hash-entry";
    appendTextElement(row, "span", path);
    appendTextElement(row, "code", digest);
    hashes.appendChild(row);
  });
  if (!hashes.children.length) appendTextElement(hashes, "p", "未返回运行文件哈希");

  const fields = $("hook-privacy-fields");
  fields.replaceChildren();
  review.privacy_fields.forEach((field) => appendTextElement(fields, "li", field));
  $("hook-consent").checked = false;
  $("hook-install-button").disabled = true;
  $("hook-dialog-feedback").hidden = true;
}

async function hookAction(kind, path, body, successMessage) {
  ui.hookBusy = kind;
  ui.hookFeedback = "";
  renderIntegration(ui.status?.integration || {});
  try {
    const result = await api(path, { method: "POST", body: body || {} });
    if (result && typeof result === "object") {
      ui.status.integration = result;
      renderIntegration(result);
    }
    if (successMessage) toast(successMessage);
    await pollStatus();
    return result;
  } catch (error) {
    ui.hookFeedback = error.message;
    toast(error.message, true);
    renderIntegration(ui.status?.integration || {});
    return null;
  } finally {
    ui.hookBusy = "";
    renderIntegration(ui.status?.integration || {});
  }
}

async function reviewHooks() {
  ui.hookBusy = "review";
  ui.hookFeedback = "";
  renderIntegration(ui.status?.integration || {});
  try {
    const review = await api("/api/hooks/review", { method: "POST", body: {} });
    renderHookReview(review);
    $("hook-review-dialog").showModal();
    await pollStatus();
  } catch (error) {
    ui.hookFeedback = error.message;
    toast(error.message, true);
  } finally {
    ui.hookBusy = "";
    renderIntegration(ui.status?.integration || {});
  }
}

function renderUpload(upload) {
  const active = Boolean(upload.active);
  $("progress-card").hidden = !active && !upload.message;
  $("cancel-upload-button").hidden = !active;
  const progress = Math.max(0, Math.min(1, Number(upload.progress) || 0));
  $("upload-progress").value = progress;
  setText("progress-percent", `${Math.round(progress * 100)}%`);
  setText("progress-message", upload.message || "正在传输，请保持有线连接…");
}

function validMappingSnapshot(snapshot) {
  if (!snapshot || typeof snapshot !== "object" || Array.isArray(snapshot)) return false;
  if (typeof snapshot.device_key !== "string" || snapshot.device_key === "") return false;
  if (!["string", "number"].includes(typeof snapshot.revision)) return false;
  if (![snapshot.normal, snapshot.fn, snapshot.normal_labels, snapshot.fn_labels]
      .every((bank) => Array.isArray(bank) && bank.length === 128)) return false;
  if (![snapshot.normal, snapshot.fn].every((bank) =>
      bank.every((entry) => Array.isArray(entry) && entry.length === 4))) return false;
  if (!Array.isArray(snapshot.controls) || !snapshot.controls.every((item) =>
      item && typeof item.label === "string" && Number.isInteger(item.slot) && item.slot >= 0 && item.slot < 128)) return false;
  if (!Array.isArray(snapshot.actions) || !snapshot.actions.every((item) =>
      item && typeof item.id === "string" && item.id && typeof item.label === "string")) return false;
  return typeof snapshot.recovery === "boolean" && typeof snapshot.pending === "boolean";
}

function setMappingFeedback(message, isError = false) {
  ui.mappingFeedback = message || "";
  const node = $("mapping-feedback");
  node.textContent = ui.mappingFeedback;
  node.classList.toggle("error", isError);
  node.hidden = !ui.mappingFeedback;
}

function invalidateMapping(message) {
  ui.mapping = null;
  ui.mappingSlot = null;
  setText("mapping-device", "映射不可用");
  setText("mapping-revision", "请重新读取后再编辑");
  setText("mapping-selected-control", "尚未选择");
  setText("mapping-current-action", "读取后选择一个键位。");
  $("mapping-controls").replaceChildren(Object.assign(document.createElement("p"), {
    className: "empty-state", textContent: "请先读取键位映射。"
  }));
  $("mapping-action-select").replaceChildren(option("", "请选择操作"));
  $("mapping-action-select").disabled = true;
  $("mapping-apply-button").disabled = true;
  $("mapping-restore-button").disabled = true;
  if (message) setMappingFeedback(message, true);
}

function mappingLabel(slot) {
  const labels = ui.mapping?.[ui.mappingBank === "fn" ? "fn_labels" : "normal_labels"];
  const label = labels?.[slot];
  return typeof label === "string" && label.trim() ? label : "未知操作";
}

function renderMapping(snapshot) {
  if (!validMappingSnapshot(snapshot)) throw new Error("键位映射数据不完整，已停止编辑");
  ui.mapping = snapshot;
  const controls = snapshot.controls;
  if (!controls.some((item) => item.slot === ui.mappingSlot)) ui.mappingSlot = null;
  setText("mapping-device", snapshot.device_key);
  setText("mapping-revision", `已读取 · 修订 ${snapshot.revision}${snapshot.pending ? " · 待恢复" : ""}`);
  $("mapping-restore-button").disabled = ui.mappingBusy || !snapshot.recovery;

  const list = $("mapping-controls");
  list.replaceChildren();
  controls.forEach((control) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `mapping-control${control.slot === ui.mappingSlot ? " active" : ""}`;
    button.dataset.slot = String(control.slot);
    appendTextElement(button, "strong", control.label);
    appendTextElement(button, "small", mappingLabel(control.slot));
    button.addEventListener("click", () => selectMappingControl(control.slot));
    list.appendChild(button);
  });
  if (!controls.length) {
    appendTextElement(list, "p", "当前设备没有可编辑的已知控制项", "empty-state");
  }

  const select = $("mapping-action-select");
  fillSelect(select, snapshot.actions, "", "请选择操作", (action) => action.id, (action) => action.label);
  select.disabled = ui.mappingBusy || ui.mappingSlot == null || snapshot.pending;
  $("mapping-apply-button").disabled = true;
  if (ui.mappingSlot == null) {
    setText("mapping-selected-control", "尚未选择");
    setText("mapping-current-action", snapshot.pending
      ? "检测到未完成的写入记录。请先恢复原始键位映射。"
      : "选择一个已知控制项，然后选择操作并明确应用。");
  } else {
    selectMappingControl(ui.mappingSlot);
  }
}

function selectMappingControl(slot) {
  if (!ui.mapping || ui.mappingBusy) return;
  const control = ui.mapping.controls.find((item) => item.slot === Number(slot));
  if (!control) return;
  ui.mappingSlot = control.slot;
  document.querySelectorAll(".mapping-control").forEach((button) => {
    button.classList.toggle("active", Number(button.dataset.slot) === control.slot);
  });
  setText("mapping-selected-control", `${control.label} · 槽位 ${control.slot}`);
  setText("mapping-current-action", ui.mapping.pending
    ? `当前：${mappingLabel(control.slot)}。存在未完成的写入记录，请先恢复。`
    : `当前：${mappingLabel(control.slot)}。选择新操作后点击应用。`);
  $("mapping-action-select").value = "";
  $("mapping-action-select").disabled = ui.mapping.pending;
  $("mapping-apply-button").disabled = true;
}

async function readMapping() {
  if (ui.mappingBusy) return null;
  ui.mappingBusy = true;
  setMappingFeedback("");
  $("mapping-read-button").disabled = true;
  setText("mapping-read-button", "正在读取…");
  try {
    const snapshot = await api("/api/mapping/read", { method: "POST", body: {} });
    renderMapping(snapshot);
    setMappingFeedback(snapshot.pending
      ? "检测到未完成的映射写入。为避免覆盖未知状态，请先恢复原始键位映射。"
      : "已从键盘读取两层完整映射。", snapshot.pending);
    return snapshot;
  } catch (error) {
    invalidateMapping(error.message);
    return null;
  } finally {
    ui.mappingBusy = false;
    $("mapping-read-button").disabled = false;
    setText("mapping-read-button", "重新读取");
    if (ui.mapping) renderMapping(ui.mapping);
  }
}

async function applyMapping() {
  if (ui.mappingBusy || !ui.mapping || ui.mapping.pending || ui.mappingSlot == null) return;
  const action = $("mapping-action-select").value;
  if (!action) return toast("请选择要应用的操作", true);
  ui.mappingBusy = true;
  setMappingFeedback("");
  $("mapping-apply-button").disabled = true;
  $("mapping-read-button").disabled = true;
  try {
    const snapshot = await api("/api/mapping/apply", { method: "POST", body: {
      revision: ui.mapping.revision,
      bank: ui.mappingBank,
      slot: ui.mappingSlot,
      action
    }});
    renderMapping(snapshot);
    setMappingFeedback("单键映射已写入并重新读取验证。", false);
    toast("键位映射已应用");
  } catch (error) {
    invalidateMapping(`${error.message} 请重新读取，确认键盘当前映射后再试。`);
    toast(error.message, true);
  } finally {
    ui.mappingBusy = false;
    $("mapping-read-button").disabled = false;
    setText("mapping-read-button", "重新读取");
    if (ui.mapping) renderMapping(ui.mapping);
  }
}

async function restoreMapping() {
  if (ui.mappingBusy || !ui.mapping?.recovery) return;
  if (!window.confirm("将恢复桥接程序为这台键盘保存的原始普通层和 Fn 层映射。确认继续吗？")) return;
  ui.mappingBusy = true;
  setMappingFeedback("");
  $("mapping-restore-button").disabled = true;
  $("mapping-read-button").disabled = true;
  try {
    const snapshot = await api("/api/mapping/restore", { method: "POST", body: {} });
    renderMapping(snapshot);
    setMappingFeedback("原始两层映射已恢复并重新读取验证。", false);
    toast("原始键位映射已恢复");
  } catch (error) {
    invalidateMapping(`${error.message} 当前映射状态未知，请重新读取。`);
    toast(error.message, true);
  } finally {
    ui.mappingBusy = false;
    $("mapping-read-button").disabled = false;
    setText("mapping-read-button", "重新读取");
    if (ui.mapping) renderMapping(ui.mapping);
  }
}

function refreshPetDescription() {
  const pet = ui.pets.find((item) => String(item.id) === $("pet-select").value);
  setText("pet-description", pet?.description || "没有可用说明");
}

function schedulePreview(force = false) {
  window.clearTimeout(ui.previewTimer);
  ui.previewTimer = window.setTimeout(() => refreshPreview(force), 120);
}

function refreshPreview(force = false) {
  const state = ui.status?.state || "unknown";
  const draft = currentDraft();
  const telemetry = draft.layout === "dashboard" ? [ui.status?.locks, ui.status?.device?.connection, ui.status?.device?.battery] : [];
  const key = JSON.stringify([state, draft.pet_id, draft.layout, draft.background, telemetry]);
  if (!force && key === ui.previewKey) return;
  ui.previewKey = key;
  const query = new URLSearchParams({ state, layout: draft.layout, pet_id: draft.pet_id, background: draft.background, t: String(Date.now()) });
  const image = $("preview-image");
  $("preview-placeholder").hidden = false;
  image.src = `/api/preview.gif?${query.toString()}`;
  $("export-gif").href = `/api/export.gif?${query.toString()}`;
  $("export-png").href = `/api/export.png?${query.toString()}`;
}

async function loadSessions() {
  try {
    const data = await api("/api/sessions");
    ui.sessions = Array.isArray(data?.sessions) ? data.sessions : [];
    const selected = ui.config?.source === "desktop" ? ui.config.session_path : "";
    fillSelect($("session-select"), ui.sessions, selected, "请选择一个任务", (session) => session.path, (session) => session.name || session.path);
  } catch (error) {
    fillSelect($("session-select"), [], "", "无法读取任务列表", (item) => item, (item) => item);
  }
}

async function pollStatus() {
  if (ui.polling || ui.stopped) return;
  ui.polling = true;
  try {
    renderStatus(await api("/api/status"));
  } catch (error) {
    renderStatus({...ui.status, state:"unknown", validity:"unknown", summary:{},
      source_detail:"本地程序连接中断，当前状态不可用", device:null, devices:[], locks:{},
      iot:{connected:false,error:error.message}, upload:{active:false},
      macos_fn:{supported:ui.status?.macos_fn?.supported,active:false,ready:false,candidates:[],message:"连接中断，Mac Fn 状态不可用"},
      integration:{...ui.status?.integration,last_error:"本地程序连接中断，下面仅保留上次安装记录"}});
    invalidateMapping("本地程序连接中断，请重新读取键位后操作。");
  } finally {
    ui.polling = false;
  }
}

async function postAction(path, body, successMessage) {
  try {
    const result = await api(path, { method: "POST", body });
    if (successMessage) toast(successMessage);
    await pollStatus();
    return result;
  } catch (error) {
    toast(error.message, true);
    showNotice(error.message, true);
    return null;
  }
}

function bindEvents() {
  $("mac-fn-refresh").addEventListener("click", () => macFnAction("status"));
  $("mac-fn-enable").addEventListener("click", () => macFnAction("enable"));
  $("mac-fn-disable").addEventListener("click", () => macFnAction("disable"));
  $("mac-fn-remove").addEventListener("click", () => macFnAction("remove-helper"));
  $("settings-button").addEventListener("click", () => openSettings("display"));
  $("open-device-button").addEventListener("click", () => openSettings("device"));
  $("settings-close-button").addEventListener("click", showHome);
  document.querySelectorAll("#settings-tabs button").forEach((button) => {
    button.addEventListener("click", () => setSettingsTab(button.dataset.tab));
  });
  document.querySelectorAll("#appearance-picker button").forEach((button) => {
    button.addEventListener("click", () => setAppearance(button.dataset.appearance));
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("settings-view").hidden &&
        !$("hook-review-dialog").open && !$("about-dialog").open) showHome();
  });

  $("preview-image").addEventListener("load", () => { $("preview-placeholder").hidden = true; });
  $("preview-image").addEventListener("error", () => {
    const placeholder = $("preview-placeholder");
    const message = document.createElement("p");
    message.textContent = "预览暂不可用";
    placeholder.replaceChildren(message);
    placeholder.hidden = false;
  });

  document.querySelectorAll("#source-selector button").forEach((button) => button.addEventListener("click", () => setSource(button.dataset.source)));
  $("device-select").addEventListener("change", () => markDirty("device_key"));
  $("pet-select").addEventListener("change", () => { refreshPetDescription(); markDirty("pet_id"); });
  $("layout-select").addEventListener("change", () => markDirty("layout"));
  $("session-select").addEventListener("change", () => markDirty("session_path"));
  $("jsonl-path").addEventListener("input", () => markDirty("session_path"));
  $("rgb-toggle").addEventListener("change", () => { markDirty("rgb_enabled"); setText("rgb-detail", $("rgb-toggle").checked ? "保存后启用" : "保存后关闭"); });
  $("background-color").addEventListener("input", () => { $("background-text").value = $("background-color").value.toUpperCase(); markDirty("background"); });
  $("background-text").addEventListener("input", () => {
    const value = $("background-text").value;
    if (/^#[0-9a-f]{6}$/i.test(value)) { $("background-color").value = value; markDirty("background"); }
  });

  $("slot-select").addEventListener("change", () => setText("upload-button", `上传到用户槽 ${$("slot-select").value}`));
  $("connect-button").addEventListener("click", async () => {
    if (ui.configBusy) return;
    ui.configBusy = true;
    const revisions = {...ui.revisions};
    try {
    if (ui.dirty.has("device_key")) {
      const key = $("device-select").value;
      const saved = await postAction("/api/config", {device_key: key});
      if (saved === null) return;
      ui.config.device_key = key;
      clearSavedFields(["device_key"], revisions);
    }
    await postAction("/api/connect", {}, "连接请求已发送");
    } finally { ui.configBusy = false; }
  });
  $("select-input-button").addEventListener("click", async () => {
    if (ui.configBusy) return;
    const path = $("jsonl-path").value.trim();
    if (!path) return toast("请先填写 JSONL 文件路径", true);
    ui.configBusy = true;
    const revisions = {...ui.revisions};
    try {
    const result = await postAction("/api/input/select", { path }, "已选择 JSONL 状态来源");
    if (result) {
      if ((ui.revisions.source || 0) === (revisions.source || 0)) setSource("jsonl", false);
      ui.config.source = "jsonl"; ui.config.session_path = path;
      clearSavedFields(["source", "session_path"], revisions);
    }
    } finally { ui.configBusy = false; }
  });
  $("save-button").addEventListener("click", saveConfig);
  $("save-rgb-button").addEventListener("click", saveRGB);
  $("save-integration-button").addEventListener("click", saveConfig);

  document.querySelectorAll("#state-buttons button").forEach((button) => button.addEventListener("click", async () => {
    if (currentDraft().source !== "manual") return;
    await postAction("/api/state", { state: button.dataset.state }, `已切换为${stateNames[button.dataset.state]}`);
  }));

  $("upload-button").addEventListener("click", async () => {
    if (ui.dirty.has("device_key")) return toast("请先连接选定设备，再上传", true);
    const slot = Number($("slot-select").value);
    const draft = currentDraft();
    const snapshot = draft.layout === "dashboard" ? " 状态栏将保留上传时的静态快照。" : "";
    if (!window.confirm(`将覆盖用户槽 ${slot}，通常需要 30–120 秒。${snapshot}\n\n确认开始上传吗？`)) return;
    await postAction("/api/upload", { slot, state: ui.status.state,
      render: {pet_id: draft.pet_id, layout: draft.layout, background: draft.background}}, "上传已开始，请保持键盘连接");
  });
  $("cancel-upload-button").addEventListener("click", () => postAction("/api/cancel-upload", {}, "正在取消上传"));
  $("restore-rgb-button").addEventListener("click", () => postAction("/api/rgb/restore", {}, "正在恢复原 RGB 设置"));
  $("import-button").addEventListener("click", importPet);
  $("import-codex-button").addEventListener("click", async () => {
    const button = $("import-codex-button");
    button.disabled = true;
    button.textContent = "正在读取本机资源…";
    try {
      await api("/api/pets/import-codex", {method: "POST", body: {}});
      const data = await api("/api/pets");
      ui.pets = data.pets || [];
      fillSelect($("pet-select"), ui.pets, null, "请选择宠物", p => p.id, p => p.name);
      refreshPetDescription();
      toast("本机 Codex 宠物已导入，请选择宠物");
    } catch (error) { toast(error.message, true); }
    finally { button.disabled = false; button.textContent = "导入本机 Codex 内置宠物"; }
  });
  $("hook-review-button").addEventListener("click", reviewHooks);
  $("hook-refresh-button").addEventListener("click", () => hookAction("refresh", "/api/hooks/refresh", {}, "Hooks 状态已刷新"));
  $("hook-disable-button").addEventListener("click", () => hookAction("disable", "/api/hooks/disable", {}, "Hooks 已禁用，不再接收新事件"));
  $("hook-remove-button").addEventListener("click", async () => {
    if (!window.confirm("将禁用并移除 Keyphore Keydous 插件。仅此插件会被移除，本地 Keyphore marketplace 会保留。\n\n确认继续吗？")) return;
    await hookAction("remove", "/api/hooks/remove", {}, "Keyphore Keydous 插件已移除；本地 marketplace 已保留");
  });
  $("hook-consent").addEventListener("change", () => {
    $("hook-install-button").disabled = !$("hook-consent").checked || ui.hookBusy === "install";
  });
  $("hook-install-button").addEventListener("click", installReviewedHooks);
  $("mapping-read-button").addEventListener("click", readMapping);
  document.querySelectorAll("#mapping-bank-selector button").forEach((button) => {
    button.addEventListener("click", () => {
      ui.mappingBank = button.dataset.bank === "fn" ? "fn" : "normal";
      document.querySelectorAll("#mapping-bank-selector button").forEach((item) => {
        item.classList.toggle("active", item.dataset.bank === ui.mappingBank);
      });
      if (ui.mapping) renderMapping(ui.mapping);
    });
  });
  $("mapping-action-select").addEventListener("change", () => {
    $("mapping-apply-button").disabled = !ui.mapping || ui.mappingSlot == null ||
      !$("mapping-action-select").value || ui.mappingBusy || ui.mapping.pending;
  });
  $("mapping-apply-button").addEventListener("click", applyMapping);
  $("mapping-restore-button").addEventListener("click", restoreMapping);
  $("about-button").addEventListener("click", () => $("about-dialog").showModal());
  $("diagnostics-button").addEventListener("click", copyDiagnostics);
  $("shutdown-button").addEventListener("click", async () => {
    if (!window.confirm("退出后屏幕与 RGB 联动停止，不会继续访问硬件。已启用的 Hooks 仍会在本机记录生命周期元数据，直到你禁用它们。\n\n确定关闭本地桥接程序吗？")) return;
    const result = await postAction("/api/shutdown", {}, "桥接程序正在退出");
    if (result !== null) { ui.stopped = true; setText("bridge-label", "桥接程序已退出"); }
  });
}

async function installReviewedHooks() {
  const consent = $("hook-consent").checked;
  const review = ui.hookReview;
  if (!consent || !review?.digest) return;
  ui.hookBusy = "install";
  $("hook-install-button").disabled = true;
  setText("hook-install-button", "正在安装并校验…");
  $("hook-dialog-feedback").hidden = true;
  try {
    const result = await api("/api/hooks/install", { method: "POST", body: { digest: review.digest, consent: true } });
    ui.hookFeedback = "";
    if (result && typeof result === "object") ui.status.integration = result;
    ui.config = { ...(ui.config || {}), source: "hooks", session_path: "" };
    ui.dirty.delete("source");
    ui.dirty.delete("session_path");
    $("dirty-badge").hidden = !ui.dirty.size;
    setSource("hooks", false);
    $("hook-review-dialog").close();
    toast("八条 Hooks 已安装、启用并校验为受信任");
    await pollStatus();
  } catch (error) {
    ui.hookFeedback = error.message;
    const feedback = $("hook-dialog-feedback");
    feedback.textContent = error.message;
    feedback.hidden = false;
    toast(error.message, true);
  } finally {
    ui.hookBusy = "";
    setText("hook-install-button", "启用已审阅的 Hooks");
    $("hook-install-button").disabled = !$("hook-consent").checked;
    renderIntegration(ui.status?.integration || {});
  }
}

let macFnBusy = false;
function renderMacFn(status) {
  $("mac-fn-controls").hidden = status.supported !== true;
  setText("mac-fn-status", status.message || (status.active ? "Mac Fn 已启用" : "Mac Fn 仅在 macOS 上可用；下方 Fn 层属于键盘内部功能。"));
  const selected = $("mac-fn-device").value;
  const candidates = Array.isArray(status.candidates) ? status.candidates : [];
  fillSelect($("mac-fn-device"), candidates, selected, "请选择具体键盘", item => String(item.registryEntryId), item => `${item.product || "Keydous"} · ${item.registryEntryId}`);
  $("mac-fn-enable").disabled = macFnBusy || status.supported !== true || !$("mac-fn-device").value;
  $("mac-fn-disable").disabled = macFnBusy || status.supported !== true;
  $("mac-fn-remove").disabled = macFnBusy || status.supported !== true;
  $("mac-fn-refresh").disabled = macFnBusy;
}
async function macFnAction(operation) {
  if (macFnBusy) return;
  macFnBusy = true;
  const body = operation === "enable" ? {registry_entry_id: $("mac-fn-device").value, source_usage: Number($("mac-fn-source").value)} : {};
  try {
    const result = await api(`/api/macos-fn/${operation}`, {method:"POST",body});
    ui.status.macos_fn = result;
  } catch (error) {
    toast(error.message, true);
    setText("mac-fn-status", error.message);
  } finally {
    macFnBusy = false;
    await pollStatus();
    renderMacFn(ui.status.macos_fn || {});
  }
}

async function saveRGB() {
  if (ui.configBusy || !ui.dirty.has("rgb_enabled")) return;
  ui.configBusy = true;
  const revisions = {...ui.revisions};
  try {
    const saved = await postAction("/api/config", {rgb_enabled: $("rgb-toggle").checked}, "RGB 联动配置已保存");
    if (saved === null) return;
    ui.config.rgb_enabled = saved.rgb_enabled;
    clearSavedFields(["rgb_enabled"], revisions);
    renderStatus(ui.status);
  } finally { ui.configBusy = false; }
}

async function saveConfig() {
  if (ui.configBusy) return;
  const draft = currentDraft();
  if (!/^#[0-9a-f]{6}$/i.test(draft.background)) return toast("背景色必须是 #RRGGBB 格式", true);
  if (draft.source === "desktop" && !draft.session_path) return toast("请选择要跟随的桌面任务", true);
  if (draft.source === "jsonl" && !draft.session_path) return toast("请填写 JSONL 文件路径", true);
  ui.configBusy = true;
  const revisions = {...ui.revisions};
  try {
  const result = await postAction("/api/config", draft, "本次提交的配置已保存");
  if (result !== null) {
    ui.config = { ...(ui.config || {}), ...result };
    if ((ui.revisions.rgb_enabled || 0) === (revisions.rgb_enabled || 0)) $("rgb-toggle").checked = Boolean(result.rgb_enabled);
    clearSavedFields(Object.keys(draft), revisions);
    schedulePreview(true);
  }
  } finally { ui.configBusy = false; }
}

function fileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error(`无法读取 ${file.name}`));
    reader.readAsDataURL(file);
  });
}

async function importPet() {
  const name = $("import-name").value.trim();
  const manifestFile = $("manifest-file").files[0];
  const spritesheetFile = $("spritesheet-file").files[0];
  if (!name || !manifestFile || !spritesheetFile) return toast("请填写名称并选择 Manifest 与 Spritesheet", true);
  try {
    const manifest = JSON.parse(await manifestFile.text());
    const dataUrl = await fileAsDataUrl(spritesheetFile);
    const spritesheet = dataUrl.includes(",") ? dataUrl.slice(dataUrl.indexOf(",") + 1) : dataUrl;
    await api("/api/pet/import", { method: "POST", body: { name, manifest, spritesheet } });
    const petsData = await api("/api/pets");
    ui.pets = Array.isArray(petsData?.pets) ? petsData.pets : ui.pets;
    fillSelect($("pet-select"), ui.pets, null, "请选择宠物", (pet) => pet.id, (pet) => pet.name);
    const imported = [...ui.pets].reverse().find((pet) => pet.name === name);
    if (imported) $("pet-select").value = imported.id;
    refreshPetDescription();
    markDirty("pet_id");
    toast("宠物已导入，保存配置后使用");
  } catch (error) {
    toast(error instanceof SyntaxError ? "Manifest 不是有效的 JSON" : error.message, true);
  }
}

async function copyDiagnostics() {
  const payload = {
    time: new Date().toISOString(),
    config: ui.config ? { ...ui.config, session_path: ui.config.session_path ? "[已选择]" : "" } : null,
    status: ui.status,
    models: ui.models
  };
  try {
    await navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
    toast("诊断信息已复制");
  } catch (error) {
    toast("无法复制诊断信息", true);
  }
}

async function init() {
  setAppearance(savedAppearance(), false);
  bindEvents();
  try {
    const data = await api("/api/bootstrap");
    applyBootstrap(data || {});
    await loadSessions();
    setText("bridge-label", "本地桥接已就绪");
    $("bridge-dot").classList.add("online");
  } catch (error) {
    $("bridge-dot").className = "status-dot error";
    setText("bridge-label", "无法连接本地桥接程序");
    showNotice(`启动失败：${error.message}`, true);
  }
  window.setInterval(pollStatus, 1000);
}

init();
