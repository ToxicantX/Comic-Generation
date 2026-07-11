const state = {
  config: null,
  health: null,
  projects: [],
  activeProject: "",
  episodes: [],
  detail: null,
  status: null,
  jobs: [],
  dashboard: null,
  reviewCenter: null,
  agent: null,
  agentSimulation: null,
  selectedEpisode: 3,
  activeModule: "home",
  activeTab: "source",
  qaTab: "draft_review_md",
  mediaFilter: "pages",
  mediaFocusPageId: "",
  assetCategory: "all",
  assetUsageFilter: "all",
  reviewCenterFilter: "all",
  reviewTimelineFilter: "all",
  reviewTimelineRange: "all",
  reviewTimelineLimit: "40",
  taskCenterFilter: "all",
  selectedReviewItemId: "",
  selectedTaskJobId: "",
  taskFilePreview: null,
  selectedReviewTimelineId: "",
  importPreview: null,
  importStrategy: "create",
  latestImportJobId: "",
  importResult: null,
  projectManagerSlug: "",
  settingsLibrary: { items: [], summary: {}, types: {} },
  selectedSettingId: "",
  settingPromptRefresh: null,
  settingPromptRefreshApplied: null,
  lastJobState: "",
  generationBackend: null,
  settingsHealth: null,
  settingsSummary: null,
  previewPageId: "",
  settingPromptRefreshTimer: null,
  statusRefreshInFlight: false,
  jobPollTimer: null,
  jobPollInFlight: false,
};

const $ = (id) => document.getElementById(id);
const nativeAlert = window.alert.bind(window);
const nativeConfirm = window.confirm.bind(window);
const nativePrompt = window.prompt.bind(window);

function notify(message, type = "info", title = "提示") {
  const stack = $("appToastStack");
  if (!stack) {
    nativeAlert(String(message || ""));
    return;
  }
  const toast = document.createElement("div");
  toast.className = `app-toast ${type}`;
  const content = document.createElement("div");
  const heading = document.createElement("strong");
  heading.textContent = title;
  const body = document.createElement("p");
  body.textContent = String(message || "");
  const close = document.createElement("button");
  close.type = "button";
  close.setAttribute("aria-label", "关闭提示");
  close.textContent = "×";
  content.append(heading, body);
  toast.append(content, close);
  close.addEventListener("click", () => toast.remove());
  stack.appendChild(toast);
  window.setTimeout(() => toast.remove(), type === "error" ? 7000 : 4200);
}

function showAppDialog({
  title = "确认操作",
  message = "",
  kind = "确认",
  confirmText = "确认",
  cancelText = "取消",
  prompt = false,
  defaultValue = "",
} = {}) {
  const overlay = $("appDialog");
  if (!overlay) {
    if (prompt) return Promise.resolve(nativePrompt(message, defaultValue));
    return Promise.resolve(nativeConfirm(message));
  }
  const titleEl = $("appDialogTitle");
  const kindEl = $("appDialogKind");
  const messageEl = $("appDialogMessage");
  const inputEl = $("appDialogInput");
  const confirmEl = $("appDialogConfirm");
  const cancelEl = $("appDialogCancel");
  titleEl.textContent = title;
  kindEl.textContent = kind;
  messageEl.textContent = message;
  confirmEl.textContent = confirmText;
  cancelEl.textContent = cancelText;
  inputEl.classList.toggle("hidden", !prompt);
  inputEl.value = prompt ? defaultValue : "";
  overlay.classList.remove("hidden");
  return new Promise((resolve) => {
    const cleanup = (value) => {
      overlay.classList.add("hidden");
      confirmEl.removeEventListener("click", onConfirm);
      cancelEl.removeEventListener("click", onCancel);
      overlay.removeEventListener("click", onOverlay);
      document.removeEventListener("keydown", onKeyDown);
      resolve(value);
    };
    const onConfirm = () => cleanup(prompt ? inputEl.value : true);
    const onCancel = () => cleanup(prompt ? null : false);
    const onOverlay = (event) => {
      if (event.target === overlay) onCancel();
    };
    const onKeyDown = (event) => {
      if (event.key === "Escape") onCancel();
      if (event.key === "Enter" && (prompt || document.activeElement !== cancelEl)) onConfirm();
    };
    confirmEl.addEventListener("click", onConfirm);
    cancelEl.addEventListener("click", onCancel);
    overlay.addEventListener("click", onOverlay);
    document.addEventListener("keydown", onKeyDown);
    if (prompt) inputEl.focus();
    else confirmEl.focus();
  });
}

function confirmDialog(message, options = {}) {
  return showAppDialog({ message, ...options });
}

function alertDialog(message, options = {}) {
  notify(message, options.type || "info", options.title || "提示");
}

function promptDialog(message, defaultValue = "", options = {}) {
  return showAppDialog({ message, prompt: true, defaultValue, title: "填写备注", kind: "输入", confirmText: "提交", ...options });
}

window.alert = (message) => alertDialog(message);

const OUTPUT_QUALITY_DIMENSIONS = [
  { key: "character_consistency", label: "角色一致" },
  { key: "story_fit", label: "剧情贴合" },
  { key: "panel_continuity", label: "分镜连贯" },
  { key: "clean_image", label: "画面干净" },
  { key: "composition_readability", label: "构图可读" },
];

const QUALITY_STATUS_LABELS = {
  pass: "合格",
  fail: "问题",
  unknown: "未检",
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

function setValue(id, value) {
  $(id).value = value ?? "";
}

function getInt(id, fallback) {
  const value = Number.parseInt($(id).value, 10);
  return Number.isFinite(value) ? value : fallback;
}

function fileStem(filename) {
  return String(filename || "").replace(/\.[^/.\\]+$/, "").trim();
}

function slugFromFileName(filename) {
  const stem = fileStem(filename);
  const ascii = stem
    .normalize("NFKD")
    .replace(/[^\w\s-]/g, "")
    .trim()
    .replace(/[\s_]+/g, "_")
    .replace(/-+/g, "-")
    .toLowerCase();
  return ascii || `novel_${Date.now()}`;
}

function bytesToBase64(bytes) {
  const chunkSize = 0x8000;
  let binary = "";
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
  }
  return window.btoa(binary);
}

function episodeNumberFrom(value) {
  if (value && typeof value === "object") {
    const number = Number(value.episode_number ?? value.number ?? value.index);
    if (Number.isFinite(number) && number > 0) return number;
    return episodeNumberFrom(value.episode_id || value.id || value.episode_title || value.title);
  }
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const text = String(value || "");
  const match = text.match(/EP0*(\d+)/i) || text.match(/episode_number=(\d+)/i) || text.match(/第\s*(\d+)\s*章/);
  return match ? Number(match[1]) : 0;
}

function pageNumberFrom(value) {
  if (value && typeof value === "object") {
    const number = Number(value.index ?? value.page_number);
    if (Number.isFinite(number) && number > 0) return number;
    return pageNumberFrom(value.page_id || value.id || value.title);
  }
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const text = String(value || "");
  const match = text.match(/_P0*(\d+)/i) || text.match(/\bP0*(\d+)\b/i) || text.match(/第\s*(\d+)\s*页/);
  return match ? Number(match[1]) : 0;
}

function panelNumberFrom(value) {
  if (value && typeof value === "object") {
    const number = Number(value.index ?? value.panel_number);
    if (Number.isFinite(number) && number > 0) return number;
    return panelNumberFrom(value.panel_id || value.id || value.title);
  }
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const text = String(value || "");
  const match = text.match(/PANEL0*(\d+)/i) || text.match(/\bpanel\s*(\d+)\b/i) || text.match(/第\s*(\d+)\s*格/);
  return match ? Number(match[1]) : 0;
}

function cleanEpisodeTitle(value) {
  return stripInternalIdsFromText(value)
    .replace(/^第[\d一二三四五六七八九十百千万零〇两]+\s*章[\s:：、-]*/, "")
    .trim();
}

function episodeDisplayName(value, title = "") {
  const number = episodeNumberFrom(value);
  const sourceTitle = title || (value && typeof value === "object" ? value.episode_title || value.chapter_title || value.title : "");
  const cleanTitle = cleanEpisodeTitle(sourceTitle);
  const chapter = number ? `第 ${number} 章` : "";
  if (chapter && cleanTitle) return `${chapter} · ${cleanTitle}`;
  return chapter || cleanTitle || "未绑定章节";
}

function pageDisplayName(value, fallbackIndex = 0) {
  const number = pageNumberFrom(value) || Number(fallbackIndex) || 0;
  return number ? `第 ${number} 页` : "页面";
}

function panelDisplayName(value, fallbackIndex = 0) {
  const number = panelNumberFrom(value) || Number(fallbackIndex) || 0;
  return number ? `第 ${number} 格` : "分镜";
}

function fullPanelDisplayName(panelId, pageId = "") {
  const episode = episodeNumberFrom(panelId || pageId) || state.selectedEpisode;
  const page = pageNumberFrom(pageId || panelId);
  const panel = panelNumberFrom(panelId);
  return [
    episode ? `第 ${episode} 章` : "",
    page ? `第 ${page} 页` : "",
    panel ? `第 ${panel} 格` : "",
  ].filter(Boolean).join(" · ") || "分镜";
}

function internalIdDisplayName(value) {
  const match = String(value || "").match(/(?:[A-Z0-9]+_)*EP0*(\d+)(?:_P0*(\d+))?(?:_PANEL0*(\d+))?/i);
  if (!match) return "";
  return [
    `第 ${Number(match[1])} 章`,
    match[2] ? `第 ${Number(match[2])} 页` : "",
    match[3] ? `第 ${Number(match[3])} 格` : "",
  ].filter(Boolean).join(" · ");
}

function stripInternalIdsFromText(value) {
  return String(value ?? "")
    .replace(/\b(?:[A-Z0-9]+_)*EP\d+(?:_P\d+)?(?:_PANEL\d+)?\b/gi, (id) => internalIdDisplayName(id) || id)
    .replace(/\bEP0*(\d+)\b/g, (_, episode) => `第 ${Number(episode)} 章`)
    .replace(/\bP0*(\d+)\s*\/\s*panel\s*(\d+)\b/gi, (_, page, panel) => `第 ${Number(page)} 页 / 第 ${Number(panel)} 格`)
    .replace(/\bP0*(\d+)\b/g, (_, page) => `第 ${Number(page)} 页`)
    .replace(/\bpanel\s*(\d+)\b/gi, (_, panel) => `第 ${Number(panel)} 格`);
}

function displayPromptText(value) {
  const text = stripInternalIdsFromText(value);
  return text
    .replace(/^Draft\s+第\s+(\d+)\s+格\s+for\s+/i, "第 $1 格草稿：")
    .replace(/Establish the scene and dominant visual cues:/gi, "建立场景和主要视觉线索：")
    .replace(/Show the character action or discovery from this text chunk\./gi, "表现本段中的角色动作或发现。")
    .replace(/Hold on the emotional reaction or conflict turn\./gi, "突出情绪反应或冲突转折。")
    .replace(/End with a readable page-turn hook connected to the next chunk\./gi, "以清晰的翻页钩子连接下一段。")
    .replace(/Use the source excerpt in the page plan for close reading;/gi, "参考页面计划中的原文片段进行细读；")
    .replace(/ancient Chinese mythic fantasy comic/gi, "上古神话幻想漫画")
    .replace(/no text/gi, "画面不加文字")
    .replace(/\bcomic\b/gi, "漫画")
    .replace(/\s+/g, " ")
    .trim();
}

function isSkeletonPage(page) {
  return String(page?.status || "").includes("skeleton")
    || String(page?.summary || "").includes("初始页面骨架")
    || Boolean(page?.skeleton || page?.close_reading_required);
}

function isSkeletonPanel(panel, page = null) {
  const title = String(panel?.title || "");
  const prompt = String(panel?.prompt || "");
  const status = String(panel?.status || "");
  return isSkeletonPage(page)
    || status.includes("skeleton")
    || title.includes("待细读")
    || prompt.startsWith("待细读：")
    || prompt.includes("中国神话幻想漫画，无画面文字");
}

function panelPromptView(panel, page = null) {
  if (isSkeletonPanel(panel, page)) {
    return {
      placeholder: true,
      badge: "待细读",
      text: "该格尚未完成细读拆解。需要先运行“细读拆解”，生成真实动作、镜头、角色和画面提示。",
    };
  }
  return {
    placeholder: false,
    badge: panel?.reference_alias ? "已绑定素材" : "未绑定素材",
    text: displayPromptText(panel?.prompt || panel?.caption || "暂无提示"),
  };
}

function displayReviewText(value) {
  return stripInternalIdsFromText(value)
    .replace(/\bQA\b/g, "质检")
    .replace(/\bAI\b/g, "智能")
    .replace(/^>\s*待细读：.+?中国神话幻想漫画，无画面文字。$/gmu, "> 待细读拆解：该分镜尚未生成真实画面提示。")
    .replace(/Prompt:\s*\n\s*\n>\s*待细读拆解：该分镜尚未生成真实画面提示。/g, "Prompt:\n\n> 待细读拆解：该分镜尚未生成真实画面提示。")
    .trim();
}

function displayUiText(value) {
  return stripInternalIdsFromText(value)
    .replace(/\bQA\b/g, "质检")
    .replace(/\bAI\b/g, "智能")
    .replace(/ComfyUI/g, "生成后端");
}

function assetCategoryLabel(value) {
  return {
    characters: "角色资产",
    world_scenes: "世界/场景资产",
    weapons: "武器资产",
    clothing: "服装资产",
    creatures: "异兽/生物资产",
    uncategorized: "未分类资产",
  }[value] || value || "素材";
}

function settingTypeSortOrder(value) {
  return {
    world_rule: 10,
    character: 20,
    location: 30,
    prop: 40,
    faction: 50,
    style_rule: 60,
  }[value] || 999;
}

function hasChineseText(value) {
  return /[\u4e00-\u9fff]/.test(String(value || ""));
}

function displaySummaryText(value, fallback = "暂无中文摘要") {
  const text = displayUiText(value || "").trim();
  if (!text) return fallback;
  return hasChineseText(text) ? text : fallback;
}

function pageTitleDisplay(page) {
  const title = stripInternalIdsFromText(page?.title || "");
  return title
    .replace(/\s*第\s*\d+\s*页\s*$/u, "")
    .trim() || pageDisplayName(page);
}

function mediaTitleDisplay(item) {
  if (item.kind === "panel") {
    return `${pageDisplayName(item.page_id || item.id)} · ${panelDisplayName(item.panel_id || item.id)}`;
  }
  return pageDisplayName(item.page_id || item.id);
}

function versionRoleLabel(value) {
  return {
    current: "当前",
    previous: "旧版",
    backup: "备份",
  }[value] || value || "版本";
}

function versionPathUrl(path) {
  const text = String(path || "");
  const match = text.match(/[\\/]ComicPipeline[\\/](.+)$/i);
  if (!match) return "";
  const relative = match[1].replaceAll("\\", "/");
  const parts = relative.split("/");
  const filename = parts.pop();
  const subfolder = ["ComicPipeline", ...parts].join("/");
  return `/media/${subfolder}/${encodeURIComponent(filename)}`;
}

function renderOutputVersions(item) {
  const versions = item.db_versions || [];
  if (!versions.length) {
    return `<div class="media-versions empty-line">版本历史待记录</div>`;
  }
  const rows = versions.slice(0, 4).map((version) => {
    const path = version.file_path || "";
    const url = versionPathUrl(path);
    const link = url
      ? `<a href="${url}" target="_blank" rel="noreferrer" title="查看该版本图像">查看</a>`
      : `<span>无图</span>`;
    return `
      <div>
        <strong>V${Number(version.version_number || 1)} · ${escapeHtml(versionRoleLabel(version.role))}</strong>
        <small>${escapeHtml(version.reason || "未记录原因")} · ${escapeHtml(compactTime(version.created_at))}</small>
        ${link}
      </div>
    `;
  }).join("");
  return `<details class="media-versions"><summary>版本 ${versions.length}</summary>${rows}</details>`;
}

function renderGenerationContext(item) {
  const context = item.db_generation_context || {};
  const summary = context.summary || {};
  const settings = Array.isArray(context.settings) ? context.settings : [];
  const assets = Array.isArray(context.assets) ? context.assets : [];
  if (!settings.length && !assets.length) {
    return `<small>生成上下文：未记录</small>`;
  }
  const names = [
    ...settings.slice(0, 3).map((entry) => entry.name).filter(Boolean),
    ...assets.slice(0, 2).map((entry) => entry.title).filter(Boolean),
  ];
  const countText = `设定 ${Number(summary.settings_included || settings.length)} · 素材 ${Number(summary.assets_included || assets.length)}`;
  const nameText = names.length ? ` · ${names.join(" / ")}` : "";
  return `<small title="${escapeHtml(nameText || countText)}">生成上下文：${escapeHtml(countText + nameText)}</small>`;
}

function normalizeQualityChecks(checks = []) {
  const byKey = new Map((Array.isArray(checks) ? checks : [])
    .filter((item) => item && item.key)
    .map((item) => [item.key, item]));
  return OUTPUT_QUALITY_DIMENSIONS.map((dimension) => {
    const current = byKey.get(dimension.key) || {};
    const status = ["pass", "fail", "unknown"].includes(current.status) ? current.status : "unknown";
    return {
      key: dimension.key,
      label: dimension.label,
      status,
      note: current.note || "",
    };
  });
}

function qualitySummaryText(summary = {}, checks = []) {
  const cleanChecks = checks.length ? checks : normalizeQualityChecks([]);
  const passed = Number(summary.passed ?? cleanChecks.filter((item) => item.status === "pass").length);
  const failed = Number(summary.failed ?? cleanChecks.filter((item) => item.status === "fail").length);
  const unknown = Number(summary.unknown ?? cleanChecks.filter((item) => item.status === "unknown").length);
  if (failed) return `质量检查：${failed} 项问题`;
  if (!unknown && passed) return `质量检查：${passed} 项合格`;
  return `质量检查：${passed} 合格 / ${unknown} 未检`;
}

function cssEscape(value) {
  if (window.CSS && typeof window.CSS.escape === "function") return window.CSS.escape(String(value));
  return String(value).replace(/["\\]/g, "\\$&");
}

function renderOutputQuality(item) {
  const checks = normalizeQualityChecks(item.db_review_quality_checks || []);
  const summary = item.db_review_quality_summary || {};
  const buttons = checks.map((check) => `
    <button
      class="quality-pill quality-${escapeHtml(check.status)}"
      data-quality-output="${escapeHtml(item.db_output_id || "")}"
      data-quality-key="${escapeHtml(check.key)}"
      data-quality-status="${escapeHtml(check.status)}"
      type="button"
      title="${escapeHtml(`${check.label}：${QUALITY_STATUS_LABELS[check.status] || "未检"}`)}">
      <span>${escapeHtml(check.label)}</span>
      <b>${escapeHtml(QUALITY_STATUS_LABELS[check.status] || "未检")}</b>
    </button>
  `).join("");
  return `
    <div class="media-quality" data-quality-panel="${escapeHtml(item.db_output_id || "")}">
      <div class="quality-head">
        <strong>${escapeHtml(qualitySummaryText(summary, checks))}</strong>
        <small>点击切换</small>
      </div>
      <div class="quality-grid">${buttons}</div>
    </div>
  `;
}

function readQualityChecks(outputId) {
  const panel = document.querySelector(`[data-quality-panel="${cssEscape(outputId || "")}"]`);
  if (!panel) return normalizeQualityChecks([]);
  return OUTPUT_QUALITY_DIMENSIONS.map((dimension) => {
    const button = panel.querySelector(`[data-quality-key="${cssEscape(dimension.key)}"]`);
    return {
      key: dimension.key,
      label: dimension.label,
      status: button?.dataset.qualityStatus || "unknown",
      note: "",
    };
  });
}

function defaultQualityChecksForAction(action) {
  const status = action === "approve" ? "pass" : "unknown";
  return OUTPUT_QUALITY_DIMENSIONS.map((dimension) => ({
    key: dimension.key,
    label: dimension.label,
    status,
    note: "",
  }));
}

function toggleQualityStatus(button) {
  const nextStatus = {
    unknown: "pass",
    pass: "fail",
    fail: "unknown",
  }[button.dataset.qualityStatus || "unknown"] || "unknown";
  button.dataset.qualityStatus = nextStatus;
  button.classList.remove("quality-pass", "quality-fail", "quality-unknown");
  button.classList.add(`quality-${nextStatus}`);
  const label = button.querySelector("b");
  if (label) label.textContent = QUALITY_STATUS_LABELS[nextStatus] || "未检";
  const panel = button.closest(".media-quality");
  if (panel) {
    const outputId = panel.dataset.qualityPanel || "";
    const checks = readQualityChecks(outputId);
    const failed = checks.filter((item) => item.status === "fail").length;
    const passed = checks.filter((item) => item.status === "pass").length;
    const unknown = checks.filter((item) => item.status === "unknown").length;
    const head = panel.querySelector(".quality-head strong");
    if (head) head.textContent = failed
      ? `质量检查：${failed} 项问题`
      : (!unknown && passed ? `质量检查：${passed} 项合格` : `质量检查：${passed} 合格 / ${unknown} 未检`);
  }
}

function missingPanelSummary() {
  const missing = state.detail?.media?.missing?.panels || [];
  const summary = state.detail?.media?.summary || {};
  return {
    items: missing,
    count: Number(summary.missing_panels || missing.length || 0),
    total: Number(summary.panels_total || 0),
  };
}

function mediaReviewBlockers(ignoredPageId = "") {
  const rows = [
    ...(state.detail?.media?.pages || []),
    ...(state.detail?.media?.panels || []),
  ];
  const ignored = String(ignoredPageId || "").toUpperCase();
  const pending = rows.filter((item) => {
    const status = item.db_review_status || "";
    const pageId = String(item.page_id || item.id || "").toUpperCase();
    return item.db_synced
      && ["draft", "pending_review", "needs_work"].includes(status)
      && (!ignored || pageId !== ignored);
  });
  const byPage = pending.reduce((acc, item) => {
    const pageId = String(item.page_id || item.id || "");
    if (pageId) acc[pageId] = (acc[pageId] || 0) + 1;
    return acc;
  }, {});
  const firstPageId = Object.keys(byPage).sort()[0] || "";
  return {
    count: pending.length,
    firstPageId,
    firstPageCount: firstPageId ? byPage[firstPageId] : 0,
  };
}

function mediaReviewBlockerMessage(blockers) {
  const episode = state.selectedEpisode || episodeNumberFrom(state.detail?.episode_id);
  if (blockers?.firstPageId && blockers.firstPageCount) {
    return `第 ${episode} 章${pageDisplayName(blockers.firstPageId)}还有 ${blockers.firstPageCount} 个生成结果待审核，请先完成当前页面审核后再生成下一页。`;
  }
  return `第 ${episode} 章还有 ${Number(blockers?.count || 0)} 个生成结果待审核，请先完成当前页面审核后再生成下一页。`;
}

function focusedPageHasReviewWork(pageId) {
  const target = String(pageId || "");
  if (!target) return false;
  return [
    ...(state.detail?.media?.pages || []),
    ...(state.detail?.media?.panels || []),
  ].some((item) => item.page_id === target
    && item.db_synced
    && ["draft", "pending_review", "needs_work"].includes(item.db_review_status || ""));
}

function focusedPageReviewSummary(items = []) {
  const synced = items.filter((item) => item.db_synced);
  const pendingStatuses = new Set(["draft", "pending_review", "needs_work"]);
  const counts = synced.reduce((acc, item) => {
    const status = item.db_review_status || "pending_review";
    const quality = item.db_review_quality_summary || {};
    acc.total += 1;
    acc.pages += item.kind === "page" ? 1 : 0;
    acc.panels += item.kind === "panel" ? 1 : 0;
    acc.pending += pendingStatuses.has(status) ? 1 : 0;
    acc.approved += status === "approved" ? 1 : 0;
    acc.needsWork += status === "needs_work" ? 1 : 0;
    acc.qualityUnknown += Number(quality.total || 0) === 0 || Number(quality.unknown || 0) > 0 ? 1 : 0;
    acc.qualityFailed += Number(quality.failed || 0) > 0 ? 1 : 0;
    return acc;
  }, {
    total: 0,
    pages: 0,
    panels: 0,
    pending: 0,
    approved: 0,
    needsWork: 0,
    qualityUnknown: 0,
    qualityFailed: 0,
  });
  const nextAction = counts.pending
    ? `本页还有 ${counts.pending} 个待审核输出，完成后才能生成下一页。`
    : (counts.qualityFailed
      ? `本页有 ${counts.qualityFailed} 个输出存在质量问题，请标记待改或重生成。`
      : (counts.qualityUnknown
        ? `本页还有 ${counts.qualityUnknown} 个输出质量未检，整章审核前需要补齐。`
        : "本页审核已完成，可以返回首页继续下一页。"));
  return { ...counts, nextAction };
}

function focusedPageContextSummary(items = []) {
  const settings = new Map();
  const assets = new Map();
  const captures = [];
  for (const item of items) {
    const context = item.db_generation_context || {};
    if (context.captured_at) captures.push(context.captured_at);
    for (const setting of Array.isArray(context.settings) ? context.settings : []) {
      const key = setting.id || setting.name;
      if (!key || settings.has(key)) continue;
      settings.set(key, setting);
    }
    for (const asset of Array.isArray(context.assets) ? context.assets : []) {
      const key = asset.id || asset.title || asset.file_path;
      if (!key || assets.has(key)) continue;
      assets.set(key, asset);
    }
  }
  return {
    settings: [...settings.values()],
    assets: [...assets.values()],
    capturedAt: captures.sort().at(-1) || "",
  };
}

function renderFocusedPageContextSummary(items = []) {
  const context = focusedPageContextSummary(items);
  const settingRows = context.settings.length
    ? context.settings.slice(0, 4).map((setting) => `
      <li>
        <strong>${escapeHtml(setting.name || "未命名设定")}</strong>
        <span>${escapeHtml(settingTypeLabel(setting.type || ""))}${setting.locked ? " · 已锁定" : ""}</span>
      </li>
    `).join("")
    : `<li><strong>未记录</strong><span>本页输出没有保存设定上下文</span></li>`;
  const assetRows = context.assets.length
    ? context.assets.slice(0, 4).map((asset) => `
      <li>
        <strong>${escapeHtml(asset.title || "未命名素材")}</strong>
        <span>${escapeHtml(assetCategoryLabel(asset.type || ""))}${asset.locked ? " · 已锁定" : ""}</span>
      </li>
    `).join("")
    : `<li><strong>未记录</strong><span>本页输出没有保存素材上下文</span></li>`;
  const captured = context.capturedAt ? `最近快照 ${compactTime(context.capturedAt)}` : "未记录快照时间";
  return `
    <section class="media-focus-context" aria-label="本页生成上下文">
      <div class="context-head">
        <div>
          <strong>本页引用上下文</strong>
          <span>审核时用于核对画风、角色和素材一致性。</span>
        </div>
        <small>${escapeHtml(captured)}</small>
      </div>
      <div class="context-columns">
        <section>
          <h3>设定 ${context.settings.length}</h3>
          <ul>${settingRows}</ul>
        </section>
        <section>
          <h3>素材 ${context.assets.length}</h3>
          <ul>${assetRows}</ul>
        </section>
      </div>
    </section>
  `;
}

function currentMediaItems() {
  if (state.mediaFilter === "page_review") {
    return [
      ...(state.detail?.media?.pages || []),
      ...(state.detail?.media?.panels || []),
    ];
  }
  return state.detail?.media?.[state.mediaFilter] || [];
}

function generatedPages() {
  return (state.detail?.media?.pages || []).filter((item) => item.exists && item.url);
}

function ensurePreviewPageId(pages = generatedPages()) {
  if (!pages.length) {
    state.previewPageId = "";
    return "";
  }
  if (!pages.some((item) => item.page_id === state.previewPageId)) {
    const pending = pages.find((item) => item.db_review_status === "pending_review");
    state.previewPageId = (pending || pages[0]).page_id;
  }
  return state.previewPageId;
}

async function loadAll() {
  await Promise.all([loadConfig(), loadHealth(), loadProjects(), loadJobs(), loadDashboard()]);
  await loadImportResult();
  await loadEpisodes();
  if (state.activeModule !== "home") {
    await loadEpisode(state.selectedEpisode);
  } else {
    updateTopProgressMetric();
  }
}

async function loadImportResult() {
  try {
    const project = $("projectSlug")?.value?.trim() || state.activeProject || "";
    const data = await api(`/api/import-result${project ? `?project=${encodeURIComponent(project)}` : ""}`);
    state.importResult = data;
  } catch {
    state.importResult = null;
  }
  renderImportResultPanel();
}

async function loadDashboard() {
  state.dashboard = await api("/api/dashboard");
  renderHome();
  updateTopProgressMetric();
}

async function loadReviewCenter() {
  const params = new URLSearchParams({
    timeline_type: state.reviewTimelineFilter || "all",
    timeline_range: state.reviewTimelineRange || "all",
    timeline_limit: state.reviewTimelineLimit || "40",
  });
  state.reviewCenter = await api(`/api/review-center?${params.toString()}`);
  renderReviewCenter();
}

async function loadConfig() {
  state.config = await api("/api/config");
  await loadSettingsSummary();
  const c = state.config.config;
  setValue("comfyUrl", c.COMIC_PIPELINE_COMFY_URL);
  setValue("comfyRoot", c.COMIC_PIPELINE_COMFY_ROOT);
  setValue("novelPath", c.COMIC_PIPELINE_NOVEL_PATH);
  setValue("outputRoot", c.COMIC_PIPELINE_OUTPUT_ROOT);
  setValue("databaseUrl", c.COMIC_PIPELINE_DATABASE_URL);
  setValue("textModel", c.COMIC_PIPELINE_TEXT_MODEL);
  setValue("textModelTimeout", c.COMIC_PIPELINE_TEXT_MODEL_TIMEOUT || "300");
  if ($("textModelStream")) {
    $("textModelStream").checked = String(c.COMIC_PIPELINE_TEXT_MODEL_STREAM || "true").toLowerCase() !== "false";
  }
  setValue("imageModel", c.COMIC_PIPELINE_IMAGE_MODEL);
  setValue("defaultPages", c.COMIC_PIPELINE_DEFAULT_PAGES);
  setValue("encoding", c.COMIC_PIPELINE_ENCODING);
  setValue("textBaseUrl", state.config.text?.OPENAI_BASE_URL || "");
  setValue("imageBaseUrl", state.config.image?.OPENAI_BASE_URL || "");
  state.activeProject = state.config.projects?.active || c.COMIC_PIPELINE_ACTIVE_PROJECT || "";
  $("keyMetric").textContent = state.config.image?.OPENAI_API_KEY_CONFIGURED ? "已配置" : "未配置";
  updateSettingsBadges();
}

async function loadSettingsSummary() {
  try {
    const data = await api("/api/settings");
    state.settingsSummary = data.settings || null;
  } catch {
    state.settingsSummary = null;
  }
}

async function saveConfig() {
  setButtons(true);
  const payload = settingsPayloadFromForm();
  try {
    state.config = await api("/api/config", { method: "POST", body: JSON.stringify(payload) });
    await loadSettingsSummary();
    $("textApiKey").value = "";
    $("imageApiKey").value = "";
    state.settingsHealth = null;
    await Promise.all([loadHealth(), loadProjects()]);
    await loadEpisodes();
    await loadEpisode(state.selectedEpisode);
    updateSettingsBadges();
    window.alert("设置已保存。");
  } catch (error) {
    window.alert(error.message || "设置保存失败，原配置已保留。");
    await loadConfig();
  } finally {
    setButtons(false);
  }
}

function settingsPayloadFromForm() {
  return {
    config: {
      COMIC_PIPELINE_COMFY_URL: $("comfyUrl").value,
      COMIC_PIPELINE_COMFY_ROOT: $("comfyRoot").value,
      COMIC_PIPELINE_NOVEL_PATH: $("novelPath").value,
      COMIC_PIPELINE_OUTPUT_ROOT: $("outputRoot").value,
      COMIC_PIPELINE_DATABASE_URL: $("databaseUrl").value,
      COMIC_PIPELINE_TEXT_ENV_PATH: state.config?.config?.COMIC_PIPELINE_TEXT_ENV_PATH || "",
      COMIC_PIPELINE_IMAGE_ENV_PATH: state.config?.config?.COMIC_PIPELINE_IMAGE_ENV_PATH || "",
      COMIC_PIPELINE_TEXT_MODEL: $("textModel").value,
      COMIC_PIPELINE_TEXT_MODEL_TIMEOUT: String(Math.max(getInt("textModelTimeout", 300), 30)),
      COMIC_PIPELINE_TEXT_MODEL_STREAM: $("textModelStream")?.checked ? "true" : "false",
      COMIC_PIPELINE_IMAGE_MODEL: $("imageModel").value,
      COMIC_PIPELINE_DEFAULT_PAGES: $("defaultPages").value,
      COMIC_PIPELINE_ENCODING: $("encoding").value,
      COMIC_PIPELINE_ACTIVE_PROJECT: state.activeProject || "sou_shen_ji",
    },
    text: {
      OPENAI_BASE_URL: $("textBaseUrl").value,
      OPENAI_API_KEY: $("textApiKey").value,
    },
    image: {
      OPENAI_BASE_URL: $("imageBaseUrl").value,
      OPENAI_API_KEY: $("imageApiKey").value,
    },
  };
}

async function testModel(target) {
  if (target === "image") {
    const ok = await confirmDialog("将调用图片模型生成一张低质量测试图，会消耗少量图片额度。测试图只用于验证响应，不会保存到素材库。", {
      title: "测试图片生成业务",
      kind: "实际调用",
      confirmText: "开始测试",
    });
    if (!ok) return;
  }
  const resultBox = target === "text" ? $("textModelTestResult") : $("imageModelTestResult");
  setButtons(true);
  if (resultBox) {
    resultBox.className = "model-test-result running";
    resultBox.textContent = target === "text" ? "正在测试小说处理模型..." : "正在调用图片生成模型...";
  }
  try {
    state.config = await api("/api/config", { method: "POST", body: JSON.stringify(settingsPayloadFromForm()) });
    $("textApiKey").value = "";
    $("imageApiKey").value = "";
    await loadSettingsSummary();
    await loadHealth();
    const result = await api("/api/settings/test-model", {
      method: "POST",
      body: JSON.stringify({
        target,
        timeout: target === "text" ? Math.min(Math.max(getInt("textModelTimeout", 300), 30), 120) : 180,
        live: target === "image",
      }),
    });
    renderModelTestResult(target, result);
    updateSettingsBadges();
  } catch (error) {
    renderModelTestResult(target, { ok: false, message: error.message || "模型测试失败" });
  } finally {
    setButtons(false);
  }
}

function renderModelTestResult(target, result) {
  const box = target === "text" ? $("textModelTestResult") : $("imageModelTestResult");
  if (!box) return;
  box.className = `model-test-result ${result?.ok ? "ok" : "bad"}`;
  const detail = result?.detail?.elapsed_seconds
    ? `耗时 ${result.detail.elapsed_seconds} 秒`
    : (result?.dry_run ? "未生成图片" : "");
  box.innerHTML = `
    <strong>${escapeHtml(result?.ok ? "测试通过" : "测试失败")}</strong>
    <span>${escapeHtml(result?.message || "-")}</span>
    ${detail ? `<small>${escapeHtml(detail)}</small>` : ""}
  `;
}

async function checkSettingsHealth() {
  setButtons(true);
  const badge = $("settingsHealthBadge");
  if (badge) {
    badge.textContent = "检查中";
    badge.className = "mini-badge agent-state-running";
  }
  try {
    state.settingsHealth = await api("/api/settings/health-check", {
      method: "POST",
      body: JSON.stringify({}),
    });
    renderSettingsHealth();
    await loadHealth();
  } catch (error) {
    state.settingsHealth = {
      ok: false,
      checks: [{
        name: "settings_check",
        label: "连接测试",
        ok: false,
        message: error.message || "连接测试失败",
      }],
    };
    renderSettingsHealth();
  } finally {
    setButtons(false);
  }
}

async function loadHealth() {
  state.health = await api("/api/health");
  const badge = $("healthBadge");
  badge.className = "badge " + (state.health.ok ? "ok" : "bad");
  badge.textContent = state.health.ok ? "后端正常" : "后端异常";
  $("comfyMetric").textContent = state.health.checks.root?.ok ? "可访问" : "不可访问";
  $("keyMetric").textContent = state.health.image_api_key_configured ? "图片已配置" : "图片未配置";
  updateSettingsBadges();
  $("statusLine").textContent = state.health.ok
    ? "后端正常，配置、审核、生成和查看都在控制台完成。"
    : "后端或配置异常，先检查配置与生成后端状态。";
}

async function checkGenerationBackend() {
  setButtons(true);
  try {
    state.generationBackend = await api("/api/generation-backend");
    renderGenerationBackendDiagnostics();
    await loadHealth();
  } catch (error) {
    const box = $("backendDiagnostics");
    if (box) box.textContent = error.message || "生成后端检查失败";
  } finally {
    setButtons(false);
  }
}

async function startGenerationBackend() {
  const ok = window.confirm("尝试启动生成后端？这会使用设置中的 ComfyUI 根目录和端口。");
  if (!ok) return;
  setButtons(true);
  try {
    state.generationBackend = await api("/api/generation-backend/start", {
      method: "POST",
      body: JSON.stringify({ wait_seconds: 20 }),
    });
    renderGenerationBackendDiagnostics(state.generationBackend.diagnostics || state.generationBackend);
    await loadHealth();
    window.alert(state.generationBackend.message || "生成后端启动流程已执行");
  } catch (error) {
    const box = $("backendDiagnostics");
    if (box) box.textContent = error.message || "生成后端启动失败";
    window.alert(error.message || "生成后端启动失败");
  } finally {
    setButtons(false);
  }
}

async function loadProjects() {
  const data = await api("/api/projects");
  state.projects = data.projects || [];
  state.activeProject = data.active || state.activeProject;
  renderProjects();
}

async function loadEpisodes() {
  const data = await api("/api/episodes");
  state.episodes = data.episodes || [];
  const totals = data.series?.totals || {};
  $("seriesMetric").textContent = `${seriesSourceLabel(data.series?.source)} / ${totals.chapters || state.episodes.length} 章`;
  renderEpisodes();
}

async function loadEpisode(episodeNumber, options = {}) {
  const previousEpisode = state.selectedEpisode;
  state.selectedEpisode = Number(episodeNumber) || 3;
  if (previousEpisode && previousEpisode !== state.selectedEpisode) {
    state.mediaFocusPageId = "";
  }
  const [detail, status] = await Promise.all([
    api(`/api/episode-detail?episode=${state.selectedEpisode}`),
    api(`/api/status?episode=${state.selectedEpisode}`),
  ]);
  state.detail = detail;
  state.status = status;
  const mediaSummary = detail.media?.summary || {};
  const completePages = Number(mediaSummary.real_pages_ready ?? mediaSummary.pages_ready ?? 0);
  $("episodeMetric").textContent = `${completePages}/${mediaSummary.pages_total || 0} 页 · ${mediaSummary.panels_ready || 0}/${mediaSummary.panels_total || 0} 图`;
  const active = state.projects.find((item) => item.slug === state.activeProject);
  $("contextLine").textContent = `${active?.title || state.activeProject || "当前作品"} / ${episodeDisplayName(detail)}`;
  $("runEpisodeLabel").textContent = `第 ${state.selectedEpisode} 章`;
  renderEpisodes();
  renderWorkflow();
  renderReader();
  renderBreakdown();
  renderSourceView();
  renderStoryline();
  renderAssets();
  renderMedia();
  renderQaText();
  if (!options.skipAgent) {
    await loadAgent();
  }
}

async function loadAssets(episodeNumber) {
  const targetEpisode = Number(episodeNumber) || state.selectedEpisode || 3;
  state.selectedEpisode = targetEpisode;
  const assets = await api(`/api/assets?episode=${targetEpisode}`);
  if (!state.detail || typeof state.detail !== "object") {
    state.detail = {};
  }
  state.detail.assets = assets;
  renderAssets();
}

async function loadSettingsLibrary() {
  if (!state.activeProject) return;
  state.settingsLibrary = await api(`/api/novels/${encodeURIComponent(state.activeProject)}/settings`);
  renderSettingsLibrary();
}

async function loadAgent() {
  state.agent = await api(`/api/agent/inspect?episode=${state.selectedEpisode}`);
  try {
    state.agentSimulation = await api(`/api/agent/simulate?episode=${state.selectedEpisode}`);
  } catch (error) {
    state.agentSimulation = null;
  }
  renderAgent();
}

function hasActiveEpisodeJob() {
  const episode = Number(state.selectedEpisode || 0);
  if (!episode) return false;
  const activeStatuses = new Set(["running", "queued", "starting", "waiting"]);
  const episodeStages = new Set(["breakdown", "close_reading", "generate", "review", "draft_review", "regenerate"]);
  return (state.jobs || []).some((job) => {
    const jobEpisode = Number(job.episode_number || 0);
    return jobEpisode === episode && activeStatuses.has(String(job.status || "")) && episodeStages.has(String(job.stage || ""));
  });
}

function shouldRefreshRuntimeStatus() {
  if (!state.selectedEpisode) return false;
  return hasActiveEpisodeJob();
}

async function refreshRuntimeStatus(options = {}) {
  if (!options.force && !shouldRefreshRuntimeStatus()) return;
  if (state.statusRefreshInFlight) return;
  state.statusRefreshInFlight = true;
  try {
    state.status = await api(`/api/status?episode=${state.selectedEpisode}`);
    renderQaText();
  } finally {
    state.statusRefreshInFlight = false;
  }
}

function jobPollDelay() {
  if (document.hidden) return 60000;
  return hasActiveEpisodeJob() ? 7000 : 30000;
}

function scheduleJobPoll(delay = jobPollDelay()) {
  if (state.jobPollTimer) window.clearTimeout(state.jobPollTimer);
  state.jobPollTimer = window.setTimeout(pollJobs, delay);
}

async function pollJobs() {
  if (state.jobPollInFlight) {
    scheduleJobPoll();
    return;
  }
  state.jobPollInFlight = true;
  try {
    await loadJobs();
    await refreshRuntimeStatus();
  } catch (_error) {
    // The next scheduled refresh retries transient console/backend failures.
  } finally {
    state.jobPollInFlight = false;
    scheduleJobPoll();
  }
}

async function loadJobs() {
  const data = await api("/api/jobs");
  const previousLatestState = state.lastJobState;
  state.jobs = data.jobs || [];
  const latest = state.jobs[0];
  state.lastJobState = latest ? `${latest.id}:${latest.status}` : "";
  $("jobMetric").textContent = latest ? `${latest.label} ${statusText(latest.status)}` : "无";
  renderJobs();
  renderImportResultPanel();
  renderHome();
  if (latest && state.lastJobState !== previousLatestState && latest.stage === "process_novel" && latest.status === "passed") {
    await loadProjects();
    await loadEpisodes();
    const first = state.episodes[0]?.episode_number || 1;
    await loadEpisode(first);
  }
  if (latest && state.lastJobState !== previousLatestState && ["breakdown", "close_reading", "generate", "review", "draft_review"].includes(latest.stage) && ["passed", "failed"].includes(latest.status)) {
    const jobEpisode = Number(latest.episode_number || 0);
    if (jobEpisode && jobEpisode === Number(state.selectedEpisode || 0)) {
      await loadEpisode(state.selectedEpisode, { skipAgent: true });
      await loadAgent();
    }
  }
}

function renderAgent() {
  if (!state.agent) return;
  const rec = state.agent.recommendation || {};
  const badge = $("agentStateBadge");
  badge.className = `mini-badge agent-state-${rec.state || "idle"}`;
  badge.textContent = agentStateText(rec.state);
  $("agentTitle").textContent = displayUiText(rec.title || "等待检查");
  $("agentDetail").textContent = displayUiText(rec.detail || "暂无建议");
  if ($("agentCompactTitle")) $("agentCompactTitle").textContent = displayUiText(rec.title || "等待检查");
  if ($("agentCompactDetail")) $("agentCompactDetail").textContent = displayUiText(rec.detail || "暂无建议");
  $("agentPreviewLink").href = state.agent.links?.preview || "#";

  const metrics = state.agent.metrics || {};
  const completePages = Number(metrics.real_pages_ready ?? metrics.pages_ready ?? 0);
  $("agentMetrics").innerHTML = `
    <div><span>完整页</span><strong>${completePages}/${metrics.pages_total || 0}</strong></div>
    <div><span>分镜</span><strong>${metrics.panels_ready || 0}/${metrics.panels_total || 0}</strong></div>
    <div><span>素材</span><strong>${metrics.assets_total || 0}</strong></div>
    <div><span>质检</span><strong>${metrics.qa_exists ? "已生成" : "待生成"}</strong></div>
  `;
  renderApprovalGates();
  renderAgentSimulation();
  renderAgentChecks();
  renderAgentPrimary();
  renderWorkflow();
  updateStageActions();
}

function renderApprovalGates() {
  const approvals = state.agent?.approvals || {};
  const box = $("approvalGates");
  const gates = (state.agent?.gate_states || []).filter((item) => ["breakdown", "assets", "generation", "qa"].includes(item.key));
  const gateMap = { breakdown: "draft", assets: "assets", generation: "generation", qa: "qa" };
  box.innerHTML = gates.map((item) => {
    const gate = gateMap[item.key];
    const approved = Boolean(approvals[gate]);
    const canClick = ["review", "done"].includes(item.state);
    return `
    <button data-approval-gate="${gate}" class="${approved ? "approved" : ""}" type="button" ${canClick ? "" : "disabled"} title="${escapeHtml(item.detail || "")}">
      <span>${escapeHtml(displayUiText(item.label))}</span>
      <strong>${approved ? "已通过" : item.state_label || "待确认"}</strong>
    </button>
  `;
  }).join("");
  box.querySelectorAll("[data-approval-gate]").forEach((button) => {
    button.addEventListener("click", () => {
      const gate = button.dataset.approvalGate;
      const approved = !button.classList.contains("approved");
      const ok = window.confirm(`${approved ? "通过" : "撤回"}${approvalGateLabel(gate)}？`);
      if (!ok) return;
      setApproval(gate, approved);
    });
  });
}

function renderAgentSimulation() {
  const box = $("agentSimulation");
  if (!box) return;
  const simulation = state.agentSimulation || {};
  const rec = simulation.recommendation || {};
  if (!rec.title) {
    box.innerHTML = `
      <strong>流程演练</strong>
      <p>暂时没有可演练的下一步。</p>
    `;
    return;
  }
  box.innerHTML = `
    <div>
      <strong>模拟审核后推荐</strong>
      <span>只读演练，不会改变审核状态</span>
    </div>
    <p>${escapeHtml(displayUiText(simulation.assumption || ""))}</p>
    <article class="simulation-result agent-state-${escapeHtml(rec.state || "idle")}">
      <b>${escapeHtml(displayUiText(rec.title || ""))}</b>
      <small>${escapeHtml(displayUiText(rec.detail || ""))}</small>
      <em>${escapeHtml(rec.action_label || "下一步")}</em>
    </article>
  `;
}

function renderAgentChecks() {
  const box = $("agentChecks");
  const checks = state.agent?.checks || [];
  box.innerHTML = checks.map((item) => `
    <div class="agent-check ${item.ok ? "ok" : "bad"}">
      <span>${item.ok ? "正常" : "异常"}</span>
      <strong>${escapeHtml(displayUiText(item.label))}</strong>
      <small>${escapeHtml(displayUiText(item.detail || ""))}</small>
    </div>
  `).join("");
}

function renderAgentPrimary() {
  const button = $("agentPrimaryButton");
  const compactButton = $("agentCompactButton");
  const rec = state.agent?.recommendation || {};
  button.textContent = rec.action_label || "执行建议";
  button.disabled = false;
  button.dataset.agentStage = rec.stage || "";
  button.dataset.agentGate = rec.gate || "";
  button.dataset.nextEpisode = rec.next_episode || "";
  if (compactButton) {
    compactButton.textContent = rec.action_label || "执行建议";
    compactButton.disabled = false;
    compactButton.dataset.agentStage = rec.stage || "";
    compactButton.dataset.agentGate = rec.gate || "";
    compactButton.dataset.nextEpisode = rec.next_episode || "";
  }
  if (rec.state === "blocked" && !rec.stage) {
    button.disabled = true;
    if (compactButton) compactButton.disabled = true;
  }
}

function renderHome() {
  renderHomeStats();
  renderHomeTodos();
  renderHomeSystem();
  renderHomeRecentWork();
  renderHomeNovels();
  if (state.activeModule === "home") updateTopProgressMetric();
}

function mainEpisodeFromDashboard() {
  const todos = state.dashboard?.todos || [];
  for (const todo of todos) {
    const episode = Number(todo?.target?.episode || 0);
    if (episode > 0) return episode;
  }
  return Number(state.selectedEpisode || 0);
}

async function updateTopProgressMetric() {
  const metric = $("episodeMetric");
  if (!metric) return;
  if (state.activeModule !== "home" && state.detail?.media?.summary) {
    const mediaSummary = state.detail.media.summary;
    const completePages = Number(mediaSummary.real_pages_ready ?? mediaSummary.pages_ready ?? 0);
    metric.textContent = `${completePages}/${mediaSummary.pages_total || 0} 页 · ${mediaSummary.panels_ready || 0}/${mediaSummary.panels_total || 0} 图`;
    return;
  }
  const episode = mainEpisodeFromDashboard();
  if (!episode) {
    metric.textContent = "暂无主线";
    return;
  }
  try {
    const detail = await api(`/api/episode-detail?episode=${episode}`);
    const mediaSummary = detail.media?.summary || {};
    const completePages = Number(mediaSummary.real_pages_ready ?? mediaSummary.pages_ready ?? 0);
    metric.textContent = `第 ${episode} 章 ${completePages}/${mediaSummary.pages_total || 0} 页 · ${mediaSummary.panels_ready || 0}/${mediaSummary.panels_total || 0} 图`;
  } catch (error) {
    metric.textContent = `第 ${episode} 章待刷新`;
  }
}

function renderHomeStats() {
  const box = $("homeStats");
  if (!box) return;
  const stats = state.dashboard?.stats || {};
  const active = state.projects.find((item) => item.slug === state.activeProject) || state.projects[0] || {};
  const settingSummary = state.settingsLibrary?.summary || {};
  const latest = state.jobs[0];
  box.innerHTML = `
    <article>
      <span>小说项目</span>
      <strong>${Number(stats.novels || state.projects.length || 0)}</strong>
      <small>${escapeHtml(active.title || "暂无当前小说")}</small>
    </article>
    <article>
      <span>章节总数</span>
      <strong>${Number(stats.chapters || 0)}</strong>
      <small>${Number(active.episodes || 0)} 个生产流程</small>
    </article>
    <article>
      <span>待审核设定</span>
      <strong>${Number(stats.pending_settings || settingSummary.by_status?.pending_review || 0)}</strong>
      <small>先审核再进入稳定生成</small>
    </article>
    <article>
      <span>失败任务</span>
      <strong>${Number(stats.failed_jobs || 0)}</strong>
      <small>${latest ? `${stageLabel(latest.stage)} ${statusText(latest.status)}` : "暂无任务"}</small>
    </article>
  `;
}

function renderHomeSystem() {
  const box = $("homeSystemStatus");
  if (!box) return;
  const system = state.dashboard?.system_status || {};
  const dbReady = Boolean(system.database?.schema_ready || state.health?.database?.schema_ready);
  const comfyReady = Boolean(system.comfyui?.ok || state.health?.ok);
  const textKeyReady = Boolean(state.settingsSummary?.api_keys?.text?.configured || state.config?.text?.OPENAI_API_KEY_CONFIGURED || state.health?.text_api_key_configured);
  const imageKeyReady = Boolean(system.api_key?.configured || state.settingsSummary?.api_keys?.image?.configured || state.health?.image_api_key_configured);
  const keyReady = textKeyReady && imageKeyReady;
  $("homeSystemBadge").textContent = dbReady && comfyReady && keyReady ? "全部正常" : "需处理";
  $("homeSystemBadge").className = `mini-badge ${dbReady && comfyReady && keyReady ? "agent-state-complete" : "agent-state-blocked"}`;
  box.innerHTML = [
    ["PostgreSQL", dbReady, dbReady ? "数据库已连接，schema 已就绪。" : (system.database?.error || "数据库未就绪。")],
    ["生成后端", comfyReady, comfyReady ? "生成后端可访问。" : "生成后端不可访问，漫画生成会被阻断。"],
    ["小说处理密钥", textKeyReady, textKeyReady ? "小说处理 API Key 已配置。" : "小说处理 API Key 未配置。"],
    ["图片生成密钥", imageKeyReady, imageKeyReady ? "图片生成 API Key 已配置。" : "图片生成 API Key 未配置。"],
  ].map(([label, ok, detail]) => `
    <div class="home-status ${ok ? "ok" : "bad"}">
      <span>${ok ? "正常" : "异常"}</span>
      <strong>${escapeHtml(label)}</strong>
      <small>${escapeHtml(detail)}</small>
    </div>
  `).join("");
}

function todoStateLabel(value) {
  return {
    blocked: "需处理",
    resume: "补齐",
    review: "待审核",
    generate: "可生成",
    settings: "设定",
    history: "历史",
    next: "下一章",
    info: "提示",
  }[value] || "待办";
}

function renderHomeTodos() {
  const box = $("homeTodos");
  if (!box) return;
  const todos = state.dashboard?.todos || [];
  $("homeTodoBadge").textContent = todos.length ? `${todos.length} 项` : "已清空";
  $("homeTodoBadge").className = `mini-badge ${todos.length ? "agent-state-review" : "agent-state-complete"}`;
  if (!todos.length) {
    box.innerHTML = `<div class="empty">当前没有聚合待办。可以进入小说详情继续生产，或导入新的小说项目。</div>`;
    return;
  }
  box.innerHTML = todos.map((todo, index) => `
    <button class="todo-row todo-${escapeHtml(todo.state || "info")}" type="button" data-todo-index="${index}">
      <span>${escapeHtml(todoStateLabel(todo.state))}</span>
      <strong>${escapeHtml(displayUiText(todo.title || ""))}</strong>
      <small>${escapeHtml(displayUiText(todo.detail || ""))}</small>
      <em>${escapeHtml(todo.action_label || "处理")}</em>
    </button>
  `).join("");
  box.querySelectorAll("[data-todo-index]").forEach((button) => {
    button.addEventListener("click", async () => {
      const todo = todos[Number(button.dataset.todoIndex)];
      await openDashboardTodo(todo);
    });
  });
}

async function openDashboardTodo(todo) {
  const target = todo?.target || {};
  await openReviewTarget(target);
  if (target.quick_action === "regenerate_page" && target.page_id) {
    await regeneratePage(target.page_id);
  }
}

async function openReviewTarget(target = {}) {
  const episode = Number(target.episode || 0);
  if (episode && episode !== state.selectedEpisode) {
    await loadEpisode(episode);
  }
  if (target.media_filter) {
    state.mediaFilter = target.media_filter;
  }
  state.mediaFocusPageId = target.focus_page_id || "";
  if (target.module) {
    await switchModule(target.module);
  }
  if (target.tab) {
    switchTab(target.tab);
    if (target.tab === "media") renderMedia();
  }
  if (target.quick_action === "regenerate_page" && target.page_id) {
    await regeneratePage(target.page_id);
  }
  if (target.module === "settingsLibrary" && target.setting_id) {
    await loadSettingsLibrary();
    const item = (state.settingsLibrary?.items || []).find((setting) => Number(setting.id) === Number(target.setting_id));
    if (item) fillSettingEditor(item);
  }
  if (target.module === "assets" && target.asset_id) {
    const card = document.querySelector(`[data-asset-card-id="${CSS.escape(String(target.asset_id))}"]`);
    if (card) card.scrollIntoView({ block: "center", behavior: "smooth" });
  }
}

function openTaskCenter() {
  switchModule("taskCenter");
}

function reviewTargetKey(target = {}, fallback = "") {
  if (!target || typeof target !== "object") return fallback;
  return [
    target.module || "",
    target.tab || "",
    target.episode || "",
    target.focus_page_id || target.page_id || "",
    target.setting_id || "",
    target.asset_id || "",
    target.media_filter || "",
  ].join("|") || fallback;
}

function reviewHistoryGroups(timeline = []) {
  const groups = new Map();
  timeline.forEach((item) => {
    const key = reviewTargetKey(item.target || {}, `${item.target_type || ""}|${item.target_id || ""}`);
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        target: item.target || {},
        target_label: item.target_label || item.target_type_label || "审核对象",
        target_type_label: item.target_type_label || "审核对象",
        count: 0,
        latest_at: "",
        latest_action: "",
        latest_comment: "",
        actions: {},
        items: [],
      });
    }
    const group = groups.get(key);
    group.count += 1;
    group.items.push(item);
    const action = item.action_label || item.action || "审核";
    group.actions[action] = (group.actions[action] || 0) + 1;
    if (!group.latest_at || String(item.created_at || "") > String(group.latest_at || "")) {
      group.latest_at = item.created_at || "";
      group.latest_action = action;
      group.latest_comment = item.comment || "";
      group.target_label = item.target_label || group.target_label;
      group.target_type_label = item.target_type_label || group.target_type_label;
    }
  });
  return Array.from(groups.values()).sort((a, b) => String(b.latest_at || "").localeCompare(String(a.latest_at || "")));
}

function reviewDetailFromItem(item = null, timeline = []) {
  const groups = reviewHistoryGroups(timeline);
  if (!item) {
    return { item: null, history: [], group: null };
  }
  const key = reviewTargetKey(item.target || {}, item.id || "");
  const group = groups.find((entry) => entry.key === key) || null;
  return { item, history: group?.items || [], group };
}

function renderReviewObjectDetail(item = null, timeline = []) {
  const box = $("reviewObjectDetail");
  if (!box) return;
  const { history, group } = reviewDetailFromItem(item, timeline);
  if (!item) {
    box.innerHTML = `<div class="empty">选择左侧审核项查看对象详情、历史聚合和定位入口。</div>`;
    return;
  }
  const canOpenTarget = item.target && item.target.module;
  const canBatchOutput = item.kind === "output" && Array.isArray(item.batch?.output_ids) && item.batch.output_ids.length;
  const actionSummary = group
    ? Object.entries(group.actions).slice(0, 4).map(([label, count]) => `${label} ${count}`).join(" · ")
    : "暂无历史记录";
  box.innerHTML = `
    <div class="review-object-title">
      <span>${escapeHtml(item.kind_label || item.kind || "审核对象")}</span>
      <strong>${escapeHtml(displayUiText(item.title || ""))}</strong>
      <small>${escapeHtml(displayUiText(item.detail || ""))}</small>
    </div>
    <dl class="review-object-grid">
      <div><dt>状态</dt><dd>${escapeHtml(item.status_label || item.status || "-")}</dd></div>
      <div><dt>数量</dt><dd>${Number(item.count || 1)} 项</dd></div>
      <div><dt>更新</dt><dd>${escapeHtml(compactTime(item.updated || ""))}</dd></div>
      <div><dt>对象</dt><dd>${escapeHtml(reviewTargetKey(item.target || {}, item.id || "-"))}</dd></div>
    </dl>
    <section class="review-history-group">
      <header>
        <span>历史聚合</span>
        <b>${history.length ? `${history.length} 条` : "暂无"}</b>
      </header>
      <p>${escapeHtml(actionSummary)}</p>
      <div class="review-history-list">
        ${history.slice(0, 5).map((record) => `
          <article>
            <strong>${escapeHtml(record.action_label || record.action || "审核")}</strong>
            <small>${escapeHtml(compactTime(record.created_at))} · ${escapeHtml(displayUiText(record.comment || "无备注"))}</small>
          </article>
        `).join("") || `<small>该对象暂无最近审核记录。</small>`}
      </div>
    </section>
    <div class="review-object-actions">
      ${canBatchOutput ? `
        <button type="button" data-review-output-batch="approve" title="通过本页全部待审核输出"><span aria-hidden="true">✓</span><strong>本页全部通过</strong></button>
        <button type="button" data-review-output-batch="needs_work" title="填写问题并将本页输出批量退回"><span aria-hidden="true">?</span><strong>本页批量待改</strong></button>
      ` : ""}
      <button class="review-detail-jump" type="button" data-review-object-jump ${canOpenTarget ? "" : "disabled"} title="${canOpenTarget ? "在现有工作区定位该对象" : "该对象暂无定位入口"}">
        <span aria-hidden="true">⌖</span><strong>${canOpenTarget ? (item.action_label || "定位处理") : "暂无定位"}</strong>
      </button>
    </div>
  `;
  const jumpButton = box.querySelector("[data-review-object-jump]");
  if (jumpButton && canOpenTarget) {
    jumpButton.addEventListener("click", async () => {
      await openReviewTarget(item.target || {});
    });
  }
  box.querySelectorAll("[data-review-output-batch]").forEach((button) => {
    button.addEventListener("click", () => reviewCenterOutputBatch(item, button.dataset.reviewOutputBatch || ""));
  });
}

async function reviewCenterOutputBatch(item, action) {
  const outputIds = item?.batch?.output_ids || [];
  if (!outputIds.length) return;
  let comment = "审核中心批量通过";
  if (action === "needs_work") {
    comment = window.prompt("请填写本页需要修改的具体问题，后续重生成会保留此审核反馈：", "") || "";
    if (!comment.trim()) {
      window.alert("批量待改必须填写具体问题。");
      return;
    }
  } else if (!window.confirm(`确认通过本页 ${outputIds.length} 个生成结果？`)) {
    return;
  }
  setButtons(true);
  try {
    await api("/api/outputs/review-batch", {
      method: "POST",
      body: JSON.stringify({
        output_ids: outputIds,
        action,
        scope_page_id: item.batch.scope_page_id || "",
        comment,
        quality_checks: defaultQualityChecksForAction(action),
      }),
    });
    await Promise.all([loadReviewCenter(), loadDashboard()]);
    notify(action === "approve" ? "本页生成结果已批量通过。" : "问题已记录，本页结果已批量标记待改。", action === "approve" ? "success" : "warn", "审核完成");
  } catch (error) {
    window.alert(error.message || "审核中心批量操作失败");
  } finally {
    setButtons(false);
  }
}

function renderReviewObjectGroups(timeline = []) {
  const box = $("reviewObjectGroups");
  const badge = $("reviewObjectGroupBadge");
  if (!box) return;
  const groups = reviewHistoryGroups(timeline);
  if (badge) badge.textContent = groups.length ? `${groups.length} 组` : "暂无";
  if (!groups.length) {
    box.innerHTML = `<div class="empty">暂无可聚合的审核历史。</div>`;
    return;
  }
  box.innerHTML = groups.slice(0, 8).map((group) => `
    <button class="review-object-group" type="button" data-review-group-key="${escapeHtml(group.key)}">
      <span>${escapeHtml(group.target_type_label)}</span>
      <strong>${escapeHtml(displayUiText(group.target_label))}</strong>
      <small>${escapeHtml(group.latest_action || "审核")} · ${group.count} 条 · ${escapeHtml(compactTime(group.latest_at))}</small>
    </button>
  `).join("");
  box.querySelectorAll("[data-review-group-key]").forEach((button) => {
    button.addEventListener("click", () => {
      const group = groups.find((entry) => entry.key === button.dataset.reviewGroupKey);
      if (group?.items?.[0]) {
        state.selectedReviewTimelineId = String(group.items[0].id || "");
        renderReviewCenter();
      }
    });
  });
}

function renderReviewReasonStats(stats = {}) {
  const box = $("reviewReasonStats");
  if (!box) return;
  const reasons = Array.isArray(stats.return_reasons) ? stats.return_reasons : [];
  const actions = Array.isArray(stats.actions) ? stats.actions : [];
  const targetTypes = Array.isArray(stats.target_types) ? stats.target_types : [];
  const chips = reasons.length
    ? reasons.map((item) => `<span>${escapeHtml(displayUiText(item.label))}<b>${Number(item.count || 0)}</b></span>`).join("")
    : `<small>当前范围内没有退回 / 待改原因。</small>`;
  box.innerHTML = `
    <section>
      <header>
        <strong>${escapeHtml(stats.range_label || "全部时间")}</strong>
        <em>${Number(stats.total || 0)} 条记录 · ${Number(stats.return_total || 0)} 条退回 / 待改</em>
      </header>
      <div class="review-reason-chips">${chips}</div>
    </section>
    <section class="review-reason-columns">
      <div>
        <span>动作分布</span>
        ${actions.length ? actions.slice(0, 4).map((item) => `<p>${escapeHtml(item.label)} <b>${Number(item.count || 0)}</b></p>`).join("") : "<p>暂无</p>"}
      </div>
      <div>
        <span>对象分布</span>
        ${targetTypes.length ? targetTypes.slice(0, 4).map((item) => `<p>${escapeHtml(item.label)} <b>${Number(item.count || 0)}</b></p>`).join("") : "<p>暂无</p>"}
      </div>
    </section>
  `;
}

function renderReviewCenter() {
  const data = state.reviewCenter || {};
  const items = data.items || [];
  const summary = data.summary || {};
  const timeline = data.timeline || [];
  const reviewStats = data.review_stats || {};
  const badge = $("reviewCenterBadge");
  if (badge) {
    badge.textContent = items.length ? `${items.length} 项` : "已清空";
    badge.className = `mini-badge ${items.length ? "agent-state-review" : "agent-state-complete"}`;
  }
  const scope = $("reviewScopeMetric");
  if (scope) scope.textContent = data.project?.title ? `${data.project.title} · 审核中心` : "审核中心";
  const summaryBox = $("reviewCenterSummary");
  if (summaryBox) {
    summaryBox.innerHTML = `
      <article><span>生成结果</span><strong>${Number(summary.outputs || 0)}</strong><small>页面 / 分镜待审核</small></article>
      <article><span>章节拆解</span><strong>${Number(summary.breakdowns || 0)}</strong><small>拆解草稿待确认</small></article>
      <article><span>小说设定</span><strong>${Number(summary.settings || 0)}</strong><small>角色、场景、规则</small></article>
      <article><span>视觉素材</span><strong>${Number(summary.assets || 0)}</strong><small>作品级参考资产</small></article>
      <article><span>任务诊断</span><strong>${Number(summary.jobs || 0)}</strong><small>失败 / 等待任务</small></article>
    `;
  }
  const timelineBadge = $("reviewTimelineBadge");
  const visibleTimeline = timeline;
  if (timelineBadge) timelineBadge.textContent = visibleTimeline.length ? `${visibleTimeline.length} 条` : "暂无";
  renderReviewReasonStats(reviewStats);
  renderReviewObjectGroups(visibleTimeline);
  const timelineList = $("reviewTimelineList");
  if (timelineList) {
    if (!visibleTimeline.length) {
      timelineList.innerHTML = `<div class="empty">当前筛选下没有审核记录。</div>`;
    } else {
      const selectedExists = visibleTimeline.some((item) => String(item.id) === String(state.selectedReviewTimelineId));
      if (!selectedExists) state.selectedReviewTimelineId = String(visibleTimeline[0]?.id || "");
      timelineList.innerHTML = visibleTimeline.slice(0, 12).map((item) => {
        const changes = item.change_summary || [];
        const selectedClass = String(item.id) === String(state.selectedReviewTimelineId) ? " active" : "";
        return `
          <button class="review-timeline-item${selectedClass}" type="button" data-review-timeline-id="${escapeHtml(item.id)}">
            <header>
              <span>${escapeHtml(item.target_type_label || "审核记录")}</span>
              <b>${escapeHtml(item.action_label || "审核")}</b>
            </header>
            <strong>${escapeHtml(displayUiText(item.target_label || item.target_type_label || "审核记录"))}</strong>
            <small>${escapeHtml(item.comment || "无备注")} · ${escapeHtml(compactTime(item.created_at))}</small>
            ${changes.length ? `<ul class="review-change-list">${changes.map((change) => `<li>${escapeHtml(displayUiText(change))}</li>`).join("")}</ul>` : ""}
          </button>
        `;
      }).join("");
      timelineList.querySelectorAll("[data-review-timeline-id]").forEach((button) => {
        button.addEventListener("click", () => {
          state.selectedReviewTimelineId = button.dataset.reviewTimelineId || "";
          renderReviewCenter();
        });
      });
    }
  }
  const detailBox = $("reviewTimelineDetail");
  if (detailBox) {
    const selected = visibleTimeline.find((item) => String(item.id) === String(state.selectedReviewTimelineId)) || visibleTimeline[0];
    if (!selected) {
      detailBox.innerHTML = `<div class="empty">选择一条审核记录查看详情。</div>`;
    } else {
      const changes = selected.change_summary || [];
      const details = selected.change_details || [];
      const canOpenTarget = selected.target && selected.target.module;
      detailBox.innerHTML = `
        <div class="review-detail-title">
          <span>${escapeHtml(selected.target_type_label || "审核记录")}</span>
          <strong>${escapeHtml(selected.action_label || "审核")}</strong>
        </div>
        <dl class="review-detail-grid">
          <div><dt>对象</dt><dd>${escapeHtml(displayUiText(selected.target_label || selected.target_type_label || "审核记录"))}</dd></div>
          <div><dt>时间</dt><dd>${escapeHtml(compactTime(selected.created_at))}</dd></div>
          <div><dt>备注</dt><dd>${escapeHtml(selected.comment || "无备注")}</dd></div>
          <div><dt>记录</dt><dd>#${escapeHtml(selected.id || "-")}</dd></div>
        </dl>
        <div class="review-detail-changes">
          <span>变更摘要</span>
          ${changes.length ? `<ul>${changes.map((change) => `<li>${escapeHtml(displayUiText(change))}</li>`).join("")}</ul>` : `<small>暂无结构化变更。</small>`}
        </div>
        <div class="review-diff-table">
          <span>修改前后</span>
          ${details.length ? `
            <div class="review-diff-head"><b>字段</b><b>修改前</b><b>修改后</b></div>
            ${details.map((item) => `
              <div class="review-diff-row">
                <b>${escapeHtml(item.label || item.field || "字段")}</b>
                <small>${escapeHtml(displayUiText(item.before || "空"))}</small>
                <small>${escapeHtml(displayUiText(item.after || "空"))}</small>
              </div>
            `).join("")}
          ` : `<small>暂无可展示的字段级对比。</small>`}
        </div>
        <button class="review-detail-jump" type="button" data-review-detail-jump ${canOpenTarget ? "" : "disabled"} title="${canOpenTarget ? "在现有工作区定位该对象" : "该记录暂无可定位对象"}">
          <span aria-hidden="true">⌖</span><strong>${canOpenTarget ? "定位对象" : "暂无定位"}</strong>
        </button>
      `;
      const jumpButton = detailBox.querySelector("[data-review-detail-jump]");
      if (jumpButton && canOpenTarget) {
        jumpButton.addEventListener("click", async () => {
          await openReviewTarget(selected.target || {});
        });
      }
    }
  }
  const list = $("reviewCenterList");
  if (!list) return;
  const filter = state.reviewCenterFilter || "all";
  const visible = items.filter((item) => filter === "all" || item.kind === filter);
  if (!visible.length) {
    list.innerHTML = `<div class="empty">当前筛选下没有待处理审核项。</div>`;
    renderReviewObjectDetail(null, visibleTimeline);
    return;
  }
  if (!visible.some((item) => String(item.id) === String(state.selectedReviewItemId))) {
    state.selectedReviewItemId = String(visible[0]?.id || "");
  }
  const selectedReviewItem = visible.find((item) => String(item.id) === String(state.selectedReviewItemId)) || visible[0];
  renderReviewObjectDetail(selectedReviewItem, visibleTimeline);
  list.innerHTML = visible.map((item, index) => `
    <button class="review-center-row review-kind-${escapeHtml(item.kind || "info")} ${String(item.id) === String(state.selectedReviewItemId) ? "active" : ""}" type="button" data-review-index="${index}">
      <span>${escapeHtml(item.kind_label || item.kind || "审核")}</span>
      <strong>${escapeHtml(displayUiText(item.title || ""))}</strong>
      <small>${escapeHtml(displayUiText(item.detail || ""))}</small>
      <footer>
        <b>${escapeHtml(item.status_label || item.status || "-")}</b>
        <em>${escapeHtml(item.action_label || "处理")}</em>
      </footer>
    </button>
  `).join("");
  list.querySelectorAll("[data-review-index]").forEach((button) => {
    button.addEventListener("click", () => {
      const item = visible[Number(button.dataset.reviewIndex)];
      state.selectedReviewItemId = String(item?.id || "");
      renderReviewCenter();
    });
  });
}

function renderHomeRecentWork() {
  const box = $("homeRecentWork");
  if (!box) return;
  const jobs = state.jobs.length ? state.jobs : (state.dashboard?.recent_work || []);
  $("homeRecentBadge").textContent = jobs.length ? `${Math.min(jobs.length, 5)} 条` : "暂无";
  if (!jobs.length) {
    box.innerHTML = `<div class="empty">暂无最近任务。可以从小说列表进入工作台，或先导入小说。</div>`;
    return;
  }
  box.innerHTML = jobs.slice(0, 5).map((job) => `
    <button class="home-row" type="button" data-home-job="${escapeHtml(job.id || job.job_id || "")}">
      <span>${escapeHtml(statusText(job.status))}</span>
      <strong>${escapeHtml(stageLabel(job.stage || job.label))}</strong>
      <small>${escapeHtml(job.label || job.result_path || compactTime(job.started || job.started_at))}</small>
    </button>
  `).join("");
  box.querySelectorAll("[data-home-job]").forEach((button) => {
    button.addEventListener("click", () => {
      openTaskCenter();
    });
  });
}

function renderHomeNovels() {
  const box = $("homeNovelList");
  if (!box) return;
  const novels = state.projects.length ? state.projects : (state.dashboard?.novels || []);
  $("homeNovelBadge").textContent = novels.length ? `${novels.length} 本` : "暂无";
  if (!novels.length) {
    box.innerHTML = `<div class="empty">暂无小说项目。请先进入设置选择小说文件，再执行处理/导入小说。</div>`;
    return;
  }
  box.innerHTML = novels.map((novel) => {
    const active = novel.slug === state.activeProject;
    const archived = novel.status === "archived" || novel.archived;
    const config = novel.project_config || {};
    const managerOpen = state.projectManagerSlug === novel.slug;
    const statusLabel = archived ? "已归档" : active ? "当前" : "可选";
    return `
      <article class="novel-card ${active ? "active" : ""} ${archived ? "archived" : ""}">
        <div>
          <span>${active ? "当前小说" : archived ? "归档小说" : "小说项目"}</span>
          <h3>${escapeHtml(novel.title || novel.slug)}</h3>
          <p>${escapeHtml(displayPath(novel.novel_path || novel.source_file_path || ""))}</p>
        </div>
        <div class="novel-metrics">
          <div><span>章节</span><strong>${Number(novel.chapters || novel.chapter_count || 0)}</strong></div>
          <div><span>流程</span><strong>${Number(novel.episodes || novel.episode_count || 0)}</strong></div>
          <div><span>状态</span><strong>${escapeHtml(statusLabel)}</strong></div>
        </div>
        <div class="novel-meta">
          <span>最近打开：${escapeHtml(compactTime(novel.last_opened_at || novel.updated_at || "")) || "未记录"}</span>
          <span>项目配置：${config.text_model || config.image_model || config.output_root ? "已设置" : "使用全局"}</span>
        </div>
        <div class="novel-actions">
          <button data-open-novel="${escapeHtml(novel.slug)}" class="primary" type="button" ${archived ? "disabled title=\"归档小说需要恢复后才能进入\"" : ""}>进入详情</button>
          <button data-open-settings-library="${escapeHtml(novel.slug)}" type="button" ${archived ? "disabled title=\"归档小说需要恢复后才能查看设定库\"" : ""}>设定库</button>
          <button data-manage-project="${escapeHtml(novel.slug)}" type="button">${managerOpen ? "收起管理" : "项目管理"}</button>
          <button data-archive-project="${escapeHtml(novel.slug)}" data-archive-value="${archived ? "false" : "true"}" type="button" ${active && !archived ? "disabled title=\"当前小说不能归档，请先切换到其他小说\"" : ""}>${archived ? "恢复" : "归档"}</button>
        </div>
        ${managerOpen ? renderProjectManager(novel) : ""}
      </article>
    `;
  }).join("");
  box.querySelectorAll("[data-open-novel]").forEach((button) => {
    button.addEventListener("click", async () => {
      await switchProject(button.dataset.openNovel);
      switchModule("workflow");
      switchTab("source");
    });
  });
  box.querySelectorAll("[data-open-settings-library]").forEach((button) => {
    button.addEventListener("click", async () => {
      await switchProject(button.dataset.openSettingsLibrary);
      switchModule("settingsLibrary");
    });
  });
  box.querySelectorAll("[data-manage-project]").forEach((button) => {
    button.addEventListener("click", () => {
      const slug = button.dataset.manageProject || "";
      state.projectManagerSlug = state.projectManagerSlug === slug ? "" : slug;
      renderHomeNovels();
    });
  });
  box.querySelectorAll("[data-archive-project]").forEach((button) => {
    button.addEventListener("click", async () => {
      const slug = button.dataset.archiveProject || "";
      const archived = button.dataset.archiveValue === "true";
      await archiveProject(slug, archived);
    });
  });
  box.querySelectorAll("[data-save-project]").forEach((button) => {
    button.addEventListener("click", async () => {
      await saveProjectSettings(button.dataset.saveProject || "");
    });
  });
}

function renderProjectManager(novel) {
  const config = novel.project_config || {};
  return `
    <section class="project-manager" aria-label="小说项目管理">
      <div class="project-manager-head">
        <div>
          <span>项目级配置</span>
          <strong>${escapeHtml(novel.slug || "")}</strong>
        </div>
        <small>留空时继续使用全局设置；这里仅保存项目级覆盖项。</small>
      </div>
      <div class="project-manager-grid">
        <label>作品名称<input data-project-field="title" data-project-slug="${escapeHtml(novel.slug)}" value="${escapeHtml(novel.title || "")}"></label>
        <label>小说处理模型<input data-project-field="text_model" data-project-slug="${escapeHtml(novel.slug)}" value="${escapeHtml(config.text_model || "")}" placeholder="> 留空使用全局模型"></label>
        <label>图片生成模型<input data-project-field="image_model" data-project-slug="${escapeHtml(novel.slug)}" value="${escapeHtml(config.image_model || "")}" placeholder="> 留空使用全局模型"></label>
        <label>项目输出目录<input data-project-field="output_root" data-project-slug="${escapeHtml(novel.slug)}" value="${escapeHtml(config.output_root || "")}" placeholder="> 留空使用全局输出目录"></label>
      </div>
      <div class="project-manager-actions">
        <button data-save-project="${escapeHtml(novel.slug)}" class="primary" type="button">保存项目配置</button>
        <span>${novel.status === "archived" ? "当前状态：已归档" : "当前状态：活跃"}</span>
      </div>
    </section>
  `;
}

function projectFieldValue(slug, field) {
  const input = document.querySelector(`[data-project-field="${field}"][data-project-slug="${CSS.escape(slug)}"]`);
  return input ? input.value.trim() : "";
}

async function saveProjectSettings(slug) {
  if (!slug) return;
  setButtons(true);
  try {
    await api(`/api/projects/${encodeURIComponent(slug)}`, {
      method: "PATCH",
      body: JSON.stringify({
        title: projectFieldValue(slug, "title"),
        project_config: {
          text_model: projectFieldValue(slug, "text_model"),
          image_model: projectFieldValue(slug, "image_model"),
          output_root: projectFieldValue(slug, "output_root"),
        },
      }),
    });
    await Promise.all([loadProjects(), loadDashboard(), loadSettingsSummary()]);
    updateSettingsBadges();
  } catch (error) {
    window.alert(error.message || "保存项目配置失败");
  } finally {
    setButtons(false);
  }
}

async function archiveProject(slug, archived) {
  if (!slug) return;
  const verb = archived ? "归档" : "恢复";
  if (archived && !window.confirm(`确认${verb}这个小说项目？归档不会删除小说、数据库记录或输出文件。`)) return;
  setButtons(true);
  try {
    await api(`/api/projects/${encodeURIComponent(slug)}/archive`, {
      method: "POST",
      body: JSON.stringify({ archived }),
    });
    await Promise.all([loadProjects(), loadDashboard()]);
  } catch (error) {
    window.alert(error.message || `${verb}项目失败`);
  } finally {
    setButtons(false);
  }
}

function renderProjects() {
  const select = $("projectSelect");
  if (!select) return;
  select.innerHTML = "";
  for (const project of state.projects) {
    const option = document.createElement("option");
    option.value = project.slug;
    option.textContent = `${project.title || project.slug} · ${Number(project.episodes || 0)} 章`;
    option.selected = project.slug === state.activeProject;
    select.append(option);
  }
  const active = state.projects.find((item) => item.slug === state.activeProject) || state.projects[0];
  if (active) {
    $("projectMetric").textContent = `${active.title || active.slug} · ${Number(active.chapters || 0)} 章 · ${Number(active.episodes || 0)} 个流程`;
    setValue("projectTitle", active.title || "");
    setValue("projectSlug", active.slug || "");
    setValue("novelPath", active.novel_path || $("novelPath").value);
  } else {
    $("projectMetric").textContent = "未创建";
  }
  renderHome();
}

async function switchProject(slug) {
  if (!slug || slug === state.activeProject) return;
  setButtons(true);
  try {
    await api("/api/projects/active", {
      method: "POST",
      body: JSON.stringify({ slug }),
    });
    state.activeProject = slug;
    state.selectedEpisode = 1;
    await Promise.all([loadConfig(), loadProjects(), loadEpisodes()]);
    const first = state.episodes[0]?.episode_number || 1;
    await loadEpisode(first);
    await loadSettingsLibrary();
    await loadDashboard();
    await loadImportResult();
  } catch (error) {
    window.alert(error.message || "切换项目失败");
  } finally {
    setButtons(false);
  }
}

async function processNovel() {
  const title = $("projectTitle").value.trim();
  const novelPath = $("novelPath").value.trim();
  const slug = $("projectSlug").value.trim();
  const strategy = state.importPreview?.duplicate?.exists ? state.importStrategy : "create";
  const strategyLabels = {
    create: "创建新项目",
    update: "更新索引并保留审核",
    refresh_chapters: "只刷新章节索引",
  };
  if (!novelPath) {
    window.alert("请先填写小说文件路径。");
    return;
  }
  if (state.importPreview?.duplicate?.exists && !["update", "refresh_chapters"].includes(strategy)) {
    window.alert("项目标识已存在。请先预览章节，并选择可用的更新策略。");
    return;
  }
  const ok = window.confirm(`开始处理小说？当前策略：${strategyLabels[strategy] || strategy}。任务会写入 PostgreSQL，并更新该作品的章节索引。`);
  if (!ok) return;
  setButtons(true);
  try {
    const job = await api("/api/process-novel", {
      method: "POST",
      body: JSON.stringify({
        project_title: title,
        project_slug: slug,
        novel_path: novelPath,
        encoding: $("encoding").value,
        pages_per_chapter: getInt("defaultPages", 8),
        panels_per_page: 4,
        skeleton_count: 3,
        import_strategy: strategy,
        force: $("forceRun")?.checked || false,
      }),
    });
    state.latestImportJobId = job.id || "";
    await loadJobs();
    await loadProjects();
    await loadDashboard();
    await loadImportResult();
    state.importPreview = null;
    renderChapterImportPreview();
    renderImportResultPanel();
    switchModule("taskCenter");
  } catch (error) {
    window.alert(error.message || "处理小说启动失败");
  } finally {
    setButtons(false);
  }
}

function renderImportPreview(file = null, savedName = "") {
  const box = $("importPreview");
  if (!box) return;
  const title = $("projectTitle")?.value?.trim() || "未填写";
  const slug = $("projectSlug")?.value?.trim() || "未填写";
  const path = $("novelPath")?.value?.trim() || "未选择";
  const pages = $("defaultPages")?.value || "8";
  const encoding = $("encoding")?.value || "utf-8";
  const fileLine = file
    ? `${file.name} · ${Math.max(1, Math.round(file.size / 1024)).toLocaleString("zh-CN")} KB`
    : (savedName || "等待选择小说文件");
  box.innerHTML = `
    <div><span>文件</span><strong>${escapeHtml(fileLine)}</strong></div>
    <div><span>作品</span><strong>${escapeHtml(title)} / ${escapeHtml(slug)}</strong></div>
    <div><span>路径</span><strong>${escapeHtml(path)}</strong></div>
    <div><span>解析</span><strong>默认 ${escapeHtml(pages)} 页 / 章 · ${escapeHtml(encoding)}</strong></div>
  `;
}

function renderChapterImportPreview() {
  const box = $("importChapterPreview");
  if (!box) return;
  const preview = state.importPreview;
  if (!preview) {
    box.innerHTML = `<div class="import-preview-empty">选择文件后点击“预览章节”，导入前会显示章节识别结果和重复项目策略。</div>`;
    return;
  }
  const parse = preview.parse || {};
  const file = preview.file || {};
  const duplicate = preview.duplicate || {};
  const strategies = preview.strategies || [];
  const warnings = parse.warnings || [];
  const sample = parse.sample || [];
  const strategyCards = strategies.map((item) => {
    const disabled = item.disabled ? " disabled" : "";
    const active = state.importStrategy === item.value ? " active" : "";
    return `
      <button class="import-strategy${active}${disabled}" type="button" data-import-strategy="${escapeHtml(item.value)}" ${item.disabled ? "disabled" : ""}>
        <span>${escapeHtml(item.label)}</span>
        <small>${escapeHtml(item.description)}</small>
      </button>
    `;
  }).join("");
  const sampleRows = sample.length ? sample.map((chapter) => `
    <tr>
      <td>${Number(chapter.number || 0)}</td>
      <td>${escapeHtml(chapter.title || "")}</td>
      <td>${escapeHtml(chapter.volume || "")}</td>
      <td>${Number(chapter.line || 0)}</td>
    </tr>
  `).join("") : `<tr><td colspan="4">没有可显示的章节样例。</td></tr>`;
  box.innerHTML = `
    <div class="import-preview-head">
      <div>
        <p class="eyebrow">章节预览</p>
        <h3>${escapeHtml(preview.project?.title || "未命名作品")}</h3>
        <small>${escapeHtml(preview.project?.slug || "")} · ${escapeHtml(file.encoding_used || "")} · ${Number(file.line_count || 0).toLocaleString("zh-CN")} 行</small>
      </div>
      <span class="mini-badge ${parse.chapters ? "ok" : "warn"}">${Number(parse.chapters || 0)} 章</span>
    </div>
    <div class="import-preview-metrics">
      <div><span>卷/分区</span><strong>${Number(parse.volumes || 0)}</strong></div>
      <div><span>字符</span><strong>${Number(file.char_count || 0).toLocaleString("zh-CN")}</strong></div>
      <div><span>解析方式</span><strong>${parse.used_fallback ? "兜底分段" : "章节标题"}</strong></div>
      <div><span>重复项目</span><strong>${duplicate.exists ? "已存在" : "未发现"}</strong></div>
    </div>
    ${warnings.length ? `<div class="import-warnings">${warnings.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>` : ""}
    <div class="import-strategies">${strategyCards}</div>
    <div class="import-chapter-table-wrap">
      <table class="import-chapter-table">
        <thead><tr><th>#</th><th>章节</th><th>卷/分区</th><th>行号</th></tr></thead>
        <tbody>${sampleRows}</tbody>
      </table>
    </div>
  `;
  box.querySelectorAll("[data-import-strategy]").forEach((button) => {
    button.addEventListener("click", () => {
      state.importStrategy = button.dataset.importStrategy || "create";
      renderChapterImportPreview();
    });
  });
}

function importSummaryHtml(job, options = {}) {
  const summary = job?.import_summary || {};
  if (!summary.project_slug && !summary.chapters) return "";
  const compact = Boolean(options.compact);
  const projectSlug = summary.project_slug || job.project_slug || "";
  const status = statusText(job.status);
  const textModel = summary.text_model_used
    ? `${summary.text_model_name || "小说处理模型"} 已使用`
    : (summary.text_model_configured
      ? (summary.text_model_error ? "模型增强失败，已保留确定性解析" : "模型未参与")
      : "未配置小说处理模型");
  const textModelError = importTextModelErrorLabel(summary.text_model_error || "");
  return `
    <section class="import-result-card ${compact ? "compact" : ""}">
      <div class="import-preview-head">
        <div>
          <p class="eyebrow">导入结果</p>
          <h3>${escapeHtml(summary.project_title || job.project_title || "未命名作品")}</h3>
          <small>${escapeHtml(summary.project_slug || job.project_slug || "")} · ${escapeHtml(status)} · ${escapeHtml(compactTime(summary.updated || job.finished || job.started || ""))}</small>
        </div>
        <span class="mini-badge ${job.status === "passed" ? "ok" : (job.status === "failed" ? "danger" : "warn")}">${escapeHtml(status)}</span>
      </div>
      <div class="import-result-metrics">
        <div><span>章节</span><strong>${Number(summary.chapters || 0).toLocaleString("zh-CN")}</strong></div>
        <div><span>流程</span><strong>${Number(summary.episodes || 0).toLocaleString("zh-CN")}</strong></div>
        <div><span>初始骨架</span><strong>${Number(summary.skeleton_total || 0)}</strong></div>
        <div><span>模型处理</span><strong>${escapeHtml(textModel)}</strong></div>
      </div>
      ${textModelError ? `<div class="import-warnings"><span>${escapeHtml(textModelError)}</span></div>` : ""}
      ${compact ? "" : `
        <div class="import-result-files">
          <div><span>章节索引</span><strong>${escapeHtml(displayPath(summary.chapter_index_path || ""))}</strong></div>
          <div><span>系列计划</span><strong>${escapeHtml(displayPath(summary.series_plan_path || ""))}</strong></div>
        </div>
        <div class="import-result-actions" aria-label="导入结果后续操作">
          <button type="button" class="tool-action primary" data-import-open-workflow="${escapeHtml(projectSlug)}" title="进入当前小说详情">
            <span aria-hidden="true">↗</span><strong>进入小说详情</strong>
          </button>
          <button type="button" class="tool-action" data-import-open-settings="${escapeHtml(projectSlug)}" title="查看当前小说设定库">
            <span aria-hidden="true">※</span><strong>查看设定库</strong>
          </button>
          <button type="button" class="tool-action" data-import-repreview="${escapeHtml(projectSlug)}" title="重新读取当前文件并预览章节">
            <span aria-hidden="true">↻</span><strong>重新预览章节</strong>
          </button>
        </div>
      `}
    </section>
  `;
}

function bindImportResultActions(root) {
  if (!root) return;
  root.querySelectorAll("[data-import-open-workflow]").forEach((button) => {
    button.addEventListener("click", async () => {
      const slug = button.dataset.importOpenWorkflow || "";
      if (slug) await switchProject(slug);
      await switchModule("workflow");
      switchTab("source");
    });
  });
  root.querySelectorAll("[data-import-open-settings]").forEach((button) => {
    button.addEventListener("click", async () => {
      const slug = button.dataset.importOpenSettings || "";
      if (slug) await switchProject(slug);
      await switchModule("settingsLibrary");
    });
  });
  root.querySelectorAll("[data-import-repreview]").forEach((button) => {
    button.addEventListener("click", async () => {
      const slug = button.dataset.importRepreview || "";
      if (slug) await switchProject(slug);
      await switchModule("importNovel");
      await previewNovelImport();
    });
  });
}

function importTextModelErrorLabel(error) {
  const text = String(error || "");
  if (!text) return "";
  if (text.includes("HTTP 429") || /rate.?limit/i.test(text)) return "小说处理模型限流，导入已使用确定性章节解析完成。";
  if (text.includes("HTTP 503") || /Service temporarily unavailable/i.test(text)) return "小说处理模型临时不可用，导入已使用确定性章节解析完成。";
  if (text.includes("HTTP 401") || text.includes("HTTP 403")) return "小说处理模型鉴权失败，导入已使用确定性章节解析完成。";
  if (/timeout|timed out/i.test(text)) return "小说处理模型请求超时，导入已使用确定性章节解析完成。连接测试只验证短请求；长小说处理可在设置里提高“长文本超时秒数”，并保持“流式响应”开启。";
  return "小说处理模型增强失败，导入已使用确定性章节解析完成。";
}

function latestImportJob() {
  if (!state.jobs.length) return null;
  if (state.latestImportJobId) {
    const matched = state.jobs.find((job) => String(job.id || job.job_id || "") === String(state.latestImportJobId));
    if (matched) return matched;
  }
  return state.jobs.find((job) => job.stage === "process_novel") || null;
}

function renderImportResultPanel() {
  const box = $("importResultPanel");
  if (!box) return;
  const job = latestImportJob();
  const persisted = state.importResult?.summary
    ? {
      stage: "process_novel",
      status: state.importResult.exists ? "passed" : "passed",
      project_slug: state.importResult.project?.slug || "",
      project_title: state.importResult.project?.title || "",
      import_summary: state.importResult.summary,
      result_path: state.importResult.result_path || "",
    }
    : null;
  const source = job || persisted;
  if (!source) {
    box.innerHTML = `<div class="import-preview-empty">导入完成后，这里会显示章节入库、初始骨架和模型处理结果。</div>`;
    return;
  }
  if (["running", "queued", "starting"].includes(source.status)) {
    box.innerHTML = `
      <section class="import-result-card">
        <div class="import-preview-head">
          <div>
            <p class="eyebrow">导入任务</p>
            <h3>${escapeHtml(source.project_title || "小说处理中")}</h3>
            <small>任务正在运行，完成后会显示章节入库结果。</small>
          </div>
          <span class="mini-badge warn">${escapeHtml(statusText(source.status))}</span>
        </div>
      </section>
    `;
    return;
  }
  const html = importSummaryHtml(source);
  box.innerHTML = html || `<div class="import-preview-empty">最近导入任务还没有可读取的结果摘要，请到任务中心查看日志。</div>`;
  bindImportResultActions(box);
}

async function previewNovelImport() {
  const novelPath = $("novelPath").value.trim();
  if (!novelPath) {
    window.alert("请先选择小说文件。");
    return;
  }
  setButtons(true);
  const badge = $("importWizardBadge");
  if (badge) badge.textContent = "正在预览";
  try {
    const result = await api("/api/import-preview", {
      method: "POST",
      body: JSON.stringify({
        project_title: $("projectTitle").value.trim(),
        project_slug: $("projectSlug").value.trim(),
        novel_path: novelPath,
        encoding: $("encoding").value,
        pages_per_chapter: getInt("defaultPages", 8),
      }),
    });
    state.importPreview = result;
    state.importStrategy = result.duplicate?.exists ? "update" : "create";
    renderChapterImportPreview();
    if (badge) badge.textContent = result.duplicate?.exists ? "预览完成 / 更新" : "预览完成 / 新建";
  } catch (error) {
    state.importPreview = null;
    renderChapterImportPreview();
    if (badge) badge.textContent = "预览失败";
    window.alert(error.message || "章节预览失败");
  } finally {
    setButtons(false);
  }
}

async function uploadNovelFile(file) {
  if (!file) return;
  const status = $("novelFileStatus");
  const maxBytes = 100 * 1024 * 1024;
  if (file.size > maxBytes) {
    window.alert("小说文件超过 100MB，请先拆分后再导入。");
    $("novelFile").value = "";
    return;
  }
  if (status) status.textContent = "正在上传小说文件...";
  $("novelFile").disabled = true;
  setButtons(true);
  try {
    const bytes = new Uint8Array(await file.arrayBuffer());
    const result = await api("/api/novel-file", {
      method: "POST",
      body: JSON.stringify({
        filename: file.name,
        content_base64: bytesToBase64(bytes),
      }),
    });
    setValue("novelPath", result.path);
    if (!$("projectTitle").value.trim()) setValue("projectTitle", fileStem(file.name));
    if (!$("projectSlug").value.trim()) setValue("projectSlug", slugFromFileName(file.name));
    if (status) status.textContent = `已选择：${result.saved_name || file.name}`;
    state.importPreview = null;
    state.latestImportJobId = "";
    renderImportPreview(file, result.saved_name || file.name);
    renderChapterImportPreview();
    renderImportResultPanel();
  } catch (error) {
    if (status) status.textContent = error.message || "小说文件上传失败";
    window.alert(error.message || "小说文件上传失败");
  } finally {
    $("novelFile").disabled = false;
    setButtons(false);
  }
}

async function setApproval(gate, approved) {
  try {
    await api("/api/agent/approval", {
      method: "POST",
      body: JSON.stringify({
        episode_number: state.selectedEpisode,
        gate,
        approved,
      }),
    });
    await loadAgent();
  } catch (error) {
    window.alert(error.message || "审核状态更新失败");
  }
}

async function runAgentPrimary() {
  const rec = state.agent?.recommendation || {};
  if (rec.gate === "next_episode" && rec.next_episode) {
    const ok = window.confirm(`确认进入第 ${Number(rec.next_episode)} 章？`);
    if (!ok) return;
    await setApproval("next_episode", true);
    await loadEpisode(rec.next_episode);
    $("agentPanel").scrollIntoView({ block: "nearest" });
    return;
  }
  if (rec.requires_approval && rec.gate) {
    const ok = window.confirm(`通过${approvalGateLabel(rec.gate)}？`);
    if (!ok) return;
    await setApproval(rec.gate, true);
    return;
  }
  if (rec.stage) {
    const ok = window.confirm(`执行 ${rec.action_label || rec.stage}？任务会进入后台日志，当前章节为第 ${state.selectedEpisode} 章。`);
    if (!ok) return;
    await runStage(rec.stage);
    await Promise.all([loadJobs(), loadAgent()]);
  }
}

function renderEpisodes() {
  const box = $("episodeList");
  const keyword = ($("episodeSearch").value || "").trim().toLowerCase();
  const filter = $("episodeFilter").value || "all";
  box.innerHTML = "";
  const visible = state.episodes.filter((episode) => {
    const text = `${episode.episode_id} ${episode.source_volume} ${episode.chapter_title} ${episode.production_state} ${episodeDisplayName(episode)}`.toLowerCase();
    const matchesText = !keyword || text.includes(keyword);
    const matchesFilter = filter === "all" || episode.production_state === filter;
    return matchesText && matchesFilter;
  });
  $("episodeCount").textContent = `显示 ${Math.min(visible.length, 80)} / ${visible.length}，总计 ${state.episodes.length} 章`;
  const groups = [];
  for (const episode of visible.slice(0, 80)) {
    const volume = episode.source_volume || "未分卷";
    let group = groups.find((item) => item.volume === volume);
    if (!group) {
      group = { volume, episodes: [] };
      groups.push(group);
    }
    group.episodes.push(episode);
  }
  for (const group of groups) {
    const details = document.createElement("details");
    const hasActive = group.episodes.some((episode) => episode.episode_number === state.selectedEpisode);
    details.className = "episode-tree-group";
    details.open = hasActive || Boolean(keyword) || filter !== "all";
    const generated = group.episodes.filter((episode) => episode.production_state === "generated").length;
    details.innerHTML = `
      <summary>
        <span>${escapeHtml(group.volume)}</span>
        <strong>${group.episodes.length} 章</strong>
        <small>${generated}/${group.episodes.length} 已生成</small>
      </summary>
      <div class="episode-tree-children"></div>
    `;
    const children = details.querySelector(".episode-tree-children");
    for (const episode of group.episodes) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "episode-item" + (episode.episode_number === state.selectedEpisode ? " active" : "");
    button.innerHTML = `
      <span>第 ${Number(episode.episode_number || 0)} 章</span>
      <strong>${escapeHtml(episode.chapter_title || "未命名章节")}</strong>
      <small>${episode.generated_pages}/${episode.planned_pages} 页 · ${episode.generated_panels}/${episode.planned_panels} 图 · ${stateLabel(episode.production_state)}</small>
    `;
    button.addEventListener("click", () => loadEpisode(episode.episode_number));
      children.append(button);
    }
    box.append(details);
  }
}

function renderWorkflow() {
  const box = $("workflowSteps");
  box.innerHTML = "";
  const steps = state.agent?.gate_states || state.detail?.workflow || [];
  for (const step of steps) {
    const item = document.createElement("div");
    item.className = `step step-${step.state || "idle"}`;
    item.innerHTML = `
      <span>${escapeHtml(step.state_label || "待处理")}</span>
      <strong>${escapeHtml(displayUiText(step.label))}</strong>
      <small>${escapeHtml(displayUiText(step.detail || step.gate || ""))}</small>
    `;
    box.append(item);
  }
}

function renderReader() {
  const detail = state.detail || {};
  const breakdown = detail.breakdown || {};
  const source = detail.novel_source || {};
  const pages = detail.pages || [];
  const media = detail.media?.summary || {};
  const title = source.chapter_title || detail.episode_title || episodeDisplayName(detail);
  const volume = source.volume || detail.source_volume || "当前小说";
  const lineRange = source.line_start && source.line_end ? `第 ${source.line_start}-${source.line_end} 行` : "行号待生成";
  const plannedPanels = pages.reduce((sum, page) => sum + (page.panels || []).length, 0);
  const hasBreakdown = pages.length > 0;
  const closeStats = closeReadingStats(pages);
  const realPages = Math.max(0, pages.length - closeStats.skeleton);
  const realPanels = pages.reduce((sum, page) => {
    return sum + (page.panels || []).filter((panel) => !isSkeletonPanel(panel, page)).length;
  }, 0);

  $("readerTitle").textContent = episodeDisplayName(detail, title);
  $("readerBadge").textContent = hasBreakdown
    ? closeStats.skeleton > 0 ? "初始拆解" : "已有拆解"
    : "待拆解";
  $("readerBadge").className = `mini-badge ${hasBreakdown && closeStats.skeleton <= 0 ? "ok" : ""}`;
  $("breakdownReviewBadge").textContent = reviewStatusLabel(breakdown.review_status || "draft");
  $("breakdownEditorNote").value = breakdown.raw?.editor_note || "";
  renderCloseReadingSummary(pages, breakdown);
  $("readerSummary").innerHTML = `
    <div><span>卷册</span><strong>${escapeHtml(volume)}</strong></div>
    <div><span>原文范围</span><strong>${escapeHtml(lineRange)}</strong></div>
    <div><span>拆解页</span><strong>${realPages}/${pages.length || 0}</strong></div>
    <div><span>分镜提示</span><strong>${realPanels}/${plannedPanels}</strong></div>
  `;

  const sourceText = source.text || pages.map((page) => page.source_excerpt).filter(Boolean).join("\n\n");
  $("readerSourcePreview").textContent = sourceText ? sourceText.slice(0, 2600) : (source.reason || "当前章节还没有可查看的原小说片段");

  if (!hasBreakdown) {
    $("readerBreakdownPreview").innerHTML = `<div class="empty">当前章节还没有拆解结果。先执行“智能拆解”，生成页面计划和分镜提示后再审核。</div>`;
    return;
  }

  const stageNotice = closeStats.skeleton > 0
    ? `<div class="reader-breakdown-notice">
        <strong>当前是初始拆解骨架</strong>
        <span>已生成 ${pages.length} 页页面计划和 ${plannedPanels} 个分镜占位，但分镜仍待细读。点击“细读拆解”后，才会生成可审核的动作、镜头、角色和画面提示。</span>
      </div>`
    : `<div class="reader-breakdown-notice is-ready">
        <strong>细读拆解已生成</strong>
        <span>可以在这里核对页面摘要、原文片段和每格提示，也可以进入“章节拆解”查看完整内容。</span>
      </div>`;
  $("readerBreakdownPreview").innerHTML = stageNotice + pages.map((page) => {
    const panels = page.panels || [];
    const range = page.source_line_start && page.source_line_end ? `原文第 ${page.source_line_start}-${page.source_line_end} 行` : "原文行号待定";
    const skeleton = isSkeletonPage(page);
    const panelItems = panels.map((panel) => {
      const promptView = panelPromptView(panel, page);
      return `
        <li class="${promptView.placeholder ? "is-placeholder" : ""}">
          <strong>${escapeHtml(panelDisplayName(panel))}</strong>
          <span>${escapeHtml(promptView.text)}</span>
        </li>
      `;
    }).join("");
    return `
      <article class="reader-page-item ${skeleton ? "is-skeleton" : ""}">
        <header>
          <div>
            <span>${escapeHtml(pageDisplayName(page))}</span>
            <strong>${escapeHtml(pageTitleDisplay(page))}</strong>
          </div>
          <small>${escapeHtml(skeleton ? "待细读" : "已细读")} · ${panels.length} 格 · ${escapeHtml(range)}</small>
        </header>
        <p>${escapeHtml(displaySummaryText(page.summary, "暂无页面摘要"))}</p>
        ${page.source_excerpt ? `<blockquote>${escapeHtml(page.source_excerpt.slice(0, 220))}${page.source_excerpt.length > 220 ? "..." : ""}</blockquote>` : ""}
        <ol class="reader-panel-snippets">${panelItems}</ol>
      </article>
    `;
  }).join("");
}

function renderBreakdownOverview(pages = []) {
  const stats = closeReadingStats(pages);
  const totalPanels = pages.reduce((sum, page) => sum + (page.panels || []).length, 0);
  const realPanels = pages.reduce((sum, page) => {
    return sum + (page.panels || []).filter((panel) => !isSkeletonPanel(panel, page)).length;
  }, 0);
  if (!pages.length) return "";
  const metrics = state.agent?.metrics || {};
  const globalReady = Boolean(metrics.global_assets_ready_for_close_reading);
  const globalBlocker = metrics.global_assets_blocker || "需要先完成全局设定和全局素材确认。";
  const running = state.jobs.some((job) => ["running", "waiting"].includes(job.status) && job.stage === "close_reading");
  const canCloseRead = stats.safe > 0 && !running && globalReady;
  const closeReadingTitle = !globalReady
    ? globalBlocker
    : running
      ? "细读拆解任务正在运行。"
      : stats.safe > 0
        ? `将细读 ${stats.safe} 个未生成页面。`
        : "当前没有可安全细读的页面。";
  return `
    <section class="breakdown-overview ${stats.skeleton ? "has-skeleton" : ""}">
      <div>
        <span>页面计划</span>
        <strong>${pages.length}</strong>
      </div>
      <div>
        <span>待细读页</span>
        <strong>${stats.skeleton}</strong>
      </div>
      <div>
        <span>可审核分镜</span>
        <strong>${realPanels}/${totalPanels}</strong>
      </div>
      <p>${stats.skeleton ? "当前拆解结果已经存在，但仍是初始骨架。请先运行“细读拆解”，再进入拆解审核。" : "当前章节已有可审核的细读拆解结果。"}</p>
      <div class="breakdown-overview-actions">
        <button data-stage="close_reading" class="${stats.skeleton ? "primary" : ""}" type="button" ${canCloseRead ? "" : "disabled"} title="${escapeHtml(closeReadingTitle)}">细读拆解</button>
        <button data-stage="breakdown" type="button" title="重新检查页面计划、工作流和审稿包">重新智能拆解</button>
        <button data-open-task-center type="button" title="查看最近任务日志">查看任务日志</button>
      </div>
    </section>
  `;
}
function closeReadingStats(pages = []) {
  return pages.reduce((acc, page) => {
    const media = page.media || {};
    const hasPageOutput = Boolean(media.exists || media.db_synced || media.db_output_id);
    const hasPanelOutput = (page.panels || []).some((panel) => {
      const panelMedia = panel.media || {};
      return Boolean(panelMedia.exists || panelMedia.db_synced || panelMedia.db_output_id);
    });
    const skeleton = String(page.status || "").includes("skeleton")
      || String(page.summary || "").includes("初始页面骨架")
      || (page.panels || []).some((panel) => String(panel.title || panel.prompt || "").includes("待细读"));
    if (skeleton) acc.skeleton += 1;
    if (skeleton && !hasPageOutput && !hasPanelOutput) acc.safe += 1;
    if (skeleton && (hasPageOutput || hasPanelOutput)) acc.protected += 1;
    return acc;
  }, { skeleton: 0, safe: 0, protected: 0 });
}

function renderCloseReadingSummary(pages = [], breakdown = {}) {
  const box = $("closeReadingSummary");
  const button = $("closeReadingButton");
  if (!box || !button) return;
  const stats = closeReadingStats(pages);
  const metrics = state.agent?.metrics || {};
  const globalBlocker = metrics.global_assets_ready_for_close_reading
    ? ""
    : (metrics.global_assets_blocker || "需要先完成全局设定和全局素材确认。");
  const hasBreakdown = pages.length > 0;
  const running = state.jobs.some((job) => ["running", "waiting"].includes(job.status) && job.stage === "close_reading");
  const disabledReason = !hasBreakdown
    ? "需要先执行智能拆解，生成章节页面计划。"
    : globalBlocker
      ? globalBlocker
      : running
        ? "细读拆解任务正在运行。"
        : stats.safe <= 0
          ? "没有可安全细读的页面；已有输出或审核记录的页面不会被覆盖。"
          : "";
  button.disabled = Boolean(disabledReason);
  button.title = disabledReason || `将细读 ${stats.safe} 个未生成页面，并保护 ${stats.protected} 个已有输出页面`;
  box.innerHTML = `
    <div>
      <span>骨架页</span>
      <strong>${stats.skeleton}</strong>
    </div>
    <div>
      <span>可细读</span>
      <strong>${stats.safe}</strong>
    </div>
    <div>
      <span>已保护</span>
      <strong>${stats.protected}</strong>
    </div>
    <small>${escapeHtml(disabledReason || "细读会更新未生成页面的剧情、镜头、动作、对白和图片提示词；完成后需要重新审核拆解。")}</small>
  `;
  const raw = breakdown.raw || {};
  const closeReading = raw.close_reading || raw.close_reading_result || {};
  if (closeReading.updated || closeReading.updated_pages) {
    const pagesText = Array.isArray(closeReading.updated_pages) ? closeReading.updated_pages.length : 0;
    box.insertAdjacentHTML("beforeend", `<small>最近细读：更新 ${pagesText} 页 · ${escapeHtml(compactTime(closeReading.updated || raw.synced_at || ""))}</small>`);
  }
}

async function saveBreakdownNote() {
  const id = state.detail?.breakdown?.id;
  if (!id) {
    window.alert("当前章节还没有可保存的拆解记录。");
    return;
  }
  setButtons(true);
  try {
    await api(`/api/breakdowns/${id}`, {
      method: "PATCH",
      body: JSON.stringify({
        editor_note: $("breakdownEditorNote").value,
        comment: "保存章节拆解审核备注",
      }),
    });
    await loadEpisode(state.selectedEpisode);
  } catch (error) {
    window.alert(error.message || "保存拆解备注失败");
  } finally {
    setButtons(false);
  }
}

async function reviewBreakdown(action) {
  const id = state.detail?.breakdown?.id;
  if (!id) {
    window.alert("当前章节还没有可审核的拆解记录。");
    return;
  }
  const label = action === "approve" ? "通过当前章节拆解？" : "标记当前章节拆解待改？";
  if (!window.confirm(label)) return;
  setButtons(true);
  try {
    await api(`/api/breakdowns/${id}/review`, {
      method: "POST",
      body: JSON.stringify({
        action,
        comment: $("breakdownEditorNote").value,
      }),
    });
    await loadEpisode(state.selectedEpisode);
  } catch (error) {
    window.alert(error.message || "审核拆解失败");
  } finally {
    setButtons(false);
  }
}

function renderBreakdown() {
  const box = $("breakdownView");
  box.innerHTML = "";
  const pages = state.detail?.pages || [];
  if (!pages.length) {
    box.innerHTML = `<div class="empty">当前章节还没有拆解结果</div>`;
    return;
  }
  box.insertAdjacentHTML("beforeend", renderBreakdownOverview(pages));
  for (const page of pages) {
    const details = document.createElement("details");
    details.className = "page-block";
    if (page.index === 1) details.open = true;
    const skeleton = isSkeletonPage(page);
    const panelRows = (page.panels || []).map((panel) => {
      const promptView = panelPromptView(panel, page);
      const directorMeta = [panel.panel_role, panel.shot_type, panel.visual_priority, panel.camera_direction].filter(Boolean);
      return `
      <article class="panel-row ${promptView.placeholder ? "panel-row-placeholder" : ""}">
        <div>
          <strong>${escapeHtml(panelDisplayName(panel))}</strong>
          <small>${escapeHtml(promptView.badge)}</small>
        </div>
        <p>${escapeHtml(promptView.text)}</p>
        ${directorMeta.length ? `<small class="panel-director-meta">${escapeHtml(directorMeta.join(" · "))}</small>` : ""}
      </article>
    `;
    }).join("");
    details.innerHTML = `
      <summary>
        <span>${escapeHtml(pageDisplayName(page))}</span>
        <strong>${escapeHtml(pageTitleDisplay(page))}</strong>
        <small>${escapeHtml(skeleton ? "待细读拆解" : stateLabel(page.status || ""))}</small>
      </summary>
      <div class="page-body">
        <div class="page-copy">
          <div class="page-copy-head">
            <h3>页面摘要</h3>
            ${skeleton ? "" : `<button data-edit-breakdown-page="${escapeHtml(page.page_id)}" type="button" title="编辑本页导演层与分镜"><span aria-hidden="true">✎</span><strong>编辑本页</strong></button>`}
          </div>
          ${skeleton ? `<div class="page-stage-notice">本页当前只是初始骨架，尚未生成可审核的真实分镜提示。</div>` : ""}
          <p>${escapeHtml(displaySummaryText(page.summary, "暂无中文摘要"))}</p>
          ${renderDirectorBlock(page)}
          <details class="source-block">
            <summary>原文片段</summary>
            <pre class="excerpt">${escapeHtml(page.source_excerpt || "暂无原文")}</pre>
          </details>
        </div>
        <div class="panel-list">${panelRows}</div>
      </div>
    `;
    box.append(details);
  }
  box.querySelectorAll("[data-edit-breakdown-page]").forEach((button) => {
    button.addEventListener("click", () => openBreakdownPageEditor(button.dataset.editBreakdownPage || ""));
  });
}

function layoutStyleLabel(value) {
  return {
    splash_opening: "开场主视觉",
    diagonal_action: "斜向动作",
    bottom_reveal: "底部揭示",
    bleed_tension: "出血压迫",
    inset_reaction: "嵌入反应",
  }[value] || value || "";
}

function renderDirectorBlock(page) {
  const director = page.director || {};
  const cameraFlow = Array.isArray(director.camera_flow) ? director.camera_flow.join("；") : director.camera_flow;
  const rows = [
    ["页面节奏", director.page_rhythm || page.reading_flow],
    ["情绪弧线", director.emotional_arc],
    ["推荐版式", layoutStyleLabel(director.layout_style || page.layout_style)],
    ["视觉重点", director.visual_priority || page.visual_priority],
    ["对白策略", director.lettering_strategy],
    ["翻页钩子", director.page_turn_hook],
    ["镜头流向", cameraFlow],
  ].filter(([, value]) => value);
  if (!rows.length) return "";
  return `
    <section class="director-summary" aria-label="导演层">
      <h3>导演层</h3>
      <dl>${rows.map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}</dl>
    </section>
  `;
}

function openBreakdownPageEditor(pageId) {
  const page = (state.detail?.pages || []).find((item) => item.page_id === pageId);
  if (!page) return;
  const director = page.director || {};
  const cameraFlow = Array.isArray(director.camera_flow) ? director.camera_flow.join("；") : (director.camera_flow || "");
  const dialog = document.createElement("dialog");
  dialog.className = "breakdown-page-editor-dialog";
  dialog.innerHTML = `
    <form method="dialog" class="breakdown-page-editor-form">
      <header>
        <div><span>${escapeHtml(pageDisplayName(page))}</span><h2>编辑细读拆解</h2></div>
        <button value="cancel" type="submit" title="关闭"><span aria-hidden="true">×</span></button>
      </header>
      <div class="breakdown-page-editor-scroll">
        <section>
          <h3>页面内容</h3>
          <label>页面摘要<textarea data-page-field="summary" rows="3">${escapeHtml(page.summary || "")}</textarea></label>
          <div class="breakdown-editor-grid">
            <label>推荐版式
              <select data-page-field="layout_style">
                ${[
                  ["", "未指定"],
                  ["splash_opening", "开场主视觉"],
                  ["diagonal_action", "斜向动作"],
                  ["bottom_reveal", "底部揭示"],
                  ["bleed_tension", "出血压迫"],
                  ["inset_reaction", "嵌入反应"],
                ].map(([value, label]) => `<option value="${value}" ${String(page.layout_style || director.layout_style || "") === value ? "selected" : ""}>${label}</option>`).join("")}
              </select>
            </label>
            <label>阅读流向<input data-page-field="reading_flow" value="${escapeHtml(page.reading_flow || "")}"></label>
            <label>视觉重点<input data-page-field="visual_priority" value="${escapeHtml(page.visual_priority || "")}"></label>
          </div>
        </section>
        <section>
          <h3>导演层</h3>
          <div class="breakdown-editor-grid">
            <label>页面节奏<input data-director-field="page_rhythm" value="${escapeHtml(director.page_rhythm || "")}"></label>
            <label>情绪弧线<input data-director-field="emotional_arc" value="${escapeHtml(director.emotional_arc || "")}"></label>
            <label>对白策略<input data-director-field="lettering_strategy" value="${escapeHtml(director.lettering_strategy || "")}"></label>
            <label>翻页钩子<input data-director-field="page_turn_hook" value="${escapeHtml(director.page_turn_hook || "")}"></label>
          </div>
          <label>镜头流向<textarea data-director-field="camera_flow" rows="2">${escapeHtml(cameraFlow)}</textarea></label>
        </section>
        <section>
          <h3>分镜</h3>
          <div class="breakdown-panel-editors">
            ${(page.panels || []).map((panel) => `
              <details data-panel-editor="${escapeHtml(panel.panel_id)}">
                <summary><strong>${escapeHtml(panelDisplayName(panel))}</strong><span>${escapeHtml(panel.shot_type || "未指定镜头")}</span></summary>
                <label>标题<input data-panel-field="title" value="${escapeHtml(panel.title || "")}"></label>
                <label>画面提示<textarea data-panel-field="prompt" rows="3">${escapeHtml(panel.prompt || "")}</textarea></label>
                <div class="breakdown-editor-grid">
                  <label>分镜职责<input data-panel-field="panel_role" value="${escapeHtml(panel.panel_role || "")}"></label>
                  <label>景别<input data-panel-field="shot_type" value="${escapeHtml(panel.shot_type || "")}"></label>
                  <label>视觉重点<input data-panel-field="visual_priority" value="${escapeHtml(panel.visual_priority || "")}"></label>
                  <label>镜头方向<input data-panel-field="camera_direction" value="${escapeHtml(panel.camera_direction || "")}"></label>
                </div>
              </details>
            `).join("")}
          </div>
        </section>
      </div>
      <footer>
        <button value="cancel" type="submit">取消</button>
        <button data-save-breakdown-page class="primary" value="default" type="button">保存并重新审核</button>
      </footer>
    </form>
  `;
  document.body.append(dialog);
  dialog.addEventListener("close", () => dialog.remove(), { once: true });
  dialog.querySelector("[data-save-breakdown-page]").addEventListener("click", async () => {
    const pagePayload = { page_id: page.page_id, director: {}, panels: [] };
    dialog.querySelectorAll("[data-page-field]").forEach((field) => {
      pagePayload[field.dataset.pageField] = field.value;
    });
    dialog.querySelectorAll("[data-director-field]").forEach((field) => {
      pagePayload.director[field.dataset.directorField] = field.value;
    });
    dialog.querySelectorAll("[data-panel-editor]").forEach((panelEditor) => {
      const panel = { panel_id: panelEditor.dataset.panelEditor };
      panelEditor.querySelectorAll("[data-panel-field]").forEach((field) => {
        panel[field.dataset.panelField] = field.value;
      });
      pagePayload.panels.push(panel);
    });
    await saveBreakdownPageEdit(pagePayload, dialog);
  });
  dialog.showModal();
}

async function saveBreakdownPageEdit(pagePayload, dialog) {
  const id = state.detail?.breakdown?.id;
  if (!id) return;
  const saveButton = dialog.querySelector("[data-save-breakdown-page]");
  saveButton.disabled = true;
  try {
    await api(`/api/breakdowns/${id}`, {
      method: "PATCH",
      body: JSON.stringify({
        pages: [pagePayload],
        editor_note: $("breakdownEditorNote").value,
        comment: `人工编辑${pageDisplayName(pagePayload.page_id)}细读拆解，重新进入审核`,
      }),
    });
    dialog.close();
    await loadEpisode(state.selectedEpisode);
    switchTab("breakdown");
    notify("细读拆解已保存，章节状态已回到待审核。", "warn", "保存成功");
  } catch (error) {
    notify(error.message || "保存细读拆解失败", "error", "保存失败");
  } finally {
    saveButton.disabled = false;
  }
}

function renderSourceView() {
  const box = $("sourceView");
  box.innerHTML = "";
  const source = state.detail?.novel_source || {};
  const pages = state.detail?.pages || [];
  if (!source.available && !pages.some((page) => page.source_excerpt)) {
    box.innerHTML = `<div class="empty">${escapeHtml(source.reason || "当前章节还没有可查看的原小说片段")}</div>`;
    return;
  }
  const header = document.createElement("section");
  header.className = "source-overview";
  const lineRange = source.line_start && source.line_end ? `第 ${source.line_start}-${source.line_end} 行` : "行号待定";
  header.innerHTML = `
    <div>
      <span>${escapeHtml(source.volume || "原小说")}</span>
      <h3>${escapeHtml(source.chapter_title || state.detail?.episode_title || "当前章节")}</h3>
    </div>
    <small>${escapeHtml(lineRange)} · ${escapeHtml(source.encoding || "自动编码")}</small>
  `;
  box.append(header);

  for (const page of pages) {
    const node = document.createElement("article");
    node.className = "source-page-card";
    const pageRange = page.source_line_start && page.source_line_end
      ? `原文第 ${page.source_line_start}-${page.source_line_end} 行`
      : "原文行号待定";
    const skeleton = isSkeletonPage(page);
    const panelRows = (page.panels || []).map((panel) => {
      const promptView = panelPromptView(panel, page);
      return `
      <li class="${promptView.placeholder ? "source-panel-placeholder" : ""}">
        <strong>${escapeHtml(panelDisplayName(panel))}</strong>
        ${promptView.placeholder ? `<em>${escapeHtml(promptView.badge)}</em>` : ""}
        <span>${escapeHtml(promptView.text)}</span>
      </li>
    `;
    }).join("");
    node.innerHTML = `
      <header>
        <span>${escapeHtml(pageDisplayName(page))}</span>
        <strong>${escapeHtml(pageTitleDisplay(page))}</strong>
        <small>${escapeHtml(skeleton ? `${pageRange} · 待细读拆解` : pageRange)}</small>
      </header>
      ${skeleton ? `<div class="source-stage-notice">本页还没有真实画面拆解，右侧仅显示待处理状态，不再展示通用占位提示词。</div>` : ""}
      <div class="source-page-grid">
        <pre class="source-text">${escapeHtml(page.source_excerpt || "暂无原文")}</pre>
        <ol class="source-panel-list">${panelRows || "<li><span>暂无分镜</span></li>"}</ol>
      </div>
    `;
    box.append(node);
  }
}

function renderStoryline() {
  const box = $("storylineView");
  box.innerHTML = "";
  const items = state.detail?.storyline || [];
  if (!items.length) {
    box.innerHTML = `<div class="empty">当前章节还没有故事线摘要</div>`;
    return;
  }
  for (const item of items) {
    const node = document.createElement("article");
    node.className = "timeline-item";
    node.innerHTML = `
      <span>${escapeHtml(pageDisplayName(item))}</span>
      <h3>${escapeHtml(stripInternalIdsFromText(item.title || pageDisplayName(item)))}</h3>
      <p>${escapeHtml(displaySummaryText(item.summary || item.source_excerpt, "暂无中文故事线摘要"))}</p>
    `;
    box.append(node);
  }
}

function renderAssets() {
  const box = $("assetView");
  box.innerHTML = "";
  const assets = state.detail?.assets;
  if (!assets) {
    box.innerHTML = `<div class="empty">素材库尚未加载。请先选择小说或进入小说工作台加载章节上下文。</div>`;
    return;
  }
  const labels = assets?.labels || {};
  const allItems = Object.values(assets?.categories || {}).flat();
  const currentUsedCount = allItems.filter((item) => item.is_used_in_current).length;
  const visibleCategories = filteredAssetCategories(assets);
  const db = assets?.database || {};
  const active = state.projects.find((item) => item.slug === state.activeProject);
  $("assetScopeMetric").textContent = `${active?.title || state.activeProject || "当前作品"} · ${Number(assets?.total_assets || 0)} 个素材`;
  $("assetContextLine").textContent = `作品级素材库 · 当前第 ${state.selectedEpisode} 章使用 ${currentUsedCount} 个 · 已入库 ${Number(db.linked || 0)} 个`;
  const assetDbBadge = $("assetDbBadge");
  if (assetDbBadge) {
    const pending = Number(db.pending_sync || 0);
    assetDbBadge.textContent = pending ? `待入库 ${pending}` : `已入库 ${Number(db.linked || 0)}`;
    assetDbBadge.className = "mini-badge " + (pending ? "warn" : "ok");
  }
  renderAssetCategoryFilters(assets);
  let renderedCount = 0;
  for (const [category, items] of Object.entries(visibleCategories)) {
    if (!items.length) continue;
    renderedCount += items.length;
    const section = document.createElement("section");
    section.className = "asset-section";
    const cards = items.map((item) => assetCard(item)).join("");
    section.innerHTML = `
      <div class="asset-section-head">
        <h3>${escapeHtml(labels[category] || category)}</h3>
        <span>${items.length}</span>
      </div>
      <div class="asset-grid">${cards}</div>
    `;
    box.append(section);
  }
  if (!renderedCount) {
    box.innerHTML = `<div class="empty">没有符合条件的素材</div>`;
  }
  box.querySelectorAll("[data-asset-regenerate]").forEach((button) => {
    button.addEventListener("click", () => {
      regenerateAsset({
        id: button.dataset.assetId,
        alias: button.dataset.assetRegenerate,
        path: button.dataset.assetPath,
        category: button.dataset.assetCategory,
      });
    });
  });
  box.querySelectorAll("[data-asset-review]").forEach((button) => {
    button.addEventListener("click", () => reviewAsset(button.dataset.assetReview, button.dataset.assetAction));
  });
  box.querySelectorAll("[data-asset-lock]").forEach((button) => {
    button.addEventListener("click", () => lockAsset(button.dataset.assetLock, button.dataset.assetLocked !== "true"));
  });
  box.querySelectorAll("[data-asset-setting]").forEach((select) => {
    select.addEventListener("change", () => bindAssetSetting(select.dataset.assetSetting, select.value));
  });
}

async function syncAssetsToDatabase() {
  const total = Number(state.detail?.assets?.total_assets || 0);
  const approvedSettings = (state.detail?.assets?.setting_candidates || [])
    .filter((item) => item.review_status === "approved" || item.locked).length;
  if (!total && !approvedSettings) {
    window.alert("当前没有可同步的素材。请先在小说设定库审核或锁定关键设定。");
    return;
  }
  const ok = window.confirm(`将当前扫描到的 ${total} 个作品级素材，以及 ${approvedSettings} 个已审核全局设定同步到素材库？已有素材会更新使用关系，不会覆盖已通过或已锁定的审核状态。`);
  if (!ok) return;
  setButtons(true);
  try {
    const result = await api("/api/assets/sync", {
      method: "POST",
      body: JSON.stringify({ episode_number: state.selectedEpisode }),
    });
    state.detail.assets = result.assets;
    renderAssets();
    await loadProjects();
    window.alert(result.message || "素材同步完成");
  } catch (error) {
    window.alert(error.message || "素材同步失败");
  } finally {
    setButtons(false);
  }
}

async function syncOutputsToDatabase() {
  const total = Number(state.detail?.media?.summary?.real_pages_ready || 0) + Number(state.detail?.media?.summary?.panels_ready || 0);
  if (!total) {
    window.alert("当前章节还没有可同步的生成结果。");
    return;
  }
  setButtons(true);
  try {
    await api("/api/outputs/sync", {
      method: "POST",
      body: JSON.stringify({ episode_number: state.selectedEpisode }),
    });
    await loadEpisode(state.selectedEpisode);
  } catch (error) {
    window.alert(error.message || "同步生成结果失败");
  } finally {
    setButtons(false);
  }
}

async function reviewOutput(outputId, action) {
  if (!outputId) {
    window.alert("生成结果尚未入库，请先同步结果入库。");
    return;
  }
  const labels = {
    approve: "审核通过",
    needs_work: "标记待改",
    pending: "退回待审",
  };
  const comment = window.prompt(`${labels[action] || "更新审核状态"}：可填写审核备注`, "");
  if (comment === null) return;
  const qualityChecks = readQualityChecks(outputId);
  setButtons(true);
  try {
    await api(`/api/outputs/${encodeURIComponent(outputId)}/review`, {
      method: "POST",
      body: JSON.stringify({ action, comment, quality_checks: qualityChecks }),
    });
    await loadEpisode(state.selectedEpisode);
    await loadAgent();
    renderMedia();
  } catch (error) {
    window.alert(error.message || "生成结果审核失败");
  } finally {
    setButtons(false);
  }
}

async function reviewVisibleOutputs(action) {
  const allItems = currentMediaItems();
  const focusPageId = state.mediaFocusPageId || "";
  const items = focusPageId
    ? allItems.filter((item) => (item.kind === "page" ? item.page_id === focusPageId : item.page_id === focusPageId))
    : allItems;
  const outputIds = [...new Set(items
    .map((item) => Number(item.db_output_id || 0))
    .filter((id) => id > 0))];
  if (!outputIds.length) {
    window.alert("当前筛选下没有已入库的生成结果。");
    return;
  }
  const labels = {
    approve: "批量审核通过",
    needs_work: "批量标记待改",
    pending: "批量退回待审",
  };
  const targetLabel = state.mediaFilter === "pages" ? "页面" : (state.mediaFilter === "panels" ? "分镜" : "生成结果");
  const scopeLabel = focusPageId ? `${pageDisplayName(focusPageId)}当前聚焦的` : "当前筛选中的";
  const ok = window.confirm(`${labels[action] || "批量审核"}${scopeLabel} ${outputIds.length} 个${targetLabel}？`);
  if (!ok) return;
  const qualityChecks = defaultQualityChecksForAction(action);
  setButtons(true);
  try {
    await api("/api/outputs/review-batch", {
      method: "POST",
      body: JSON.stringify({
        output_ids: outputIds,
        action,
        scope_page_id: focusPageId,
        comment: `${labels[action] || "批量审核"} · ${focusPageId ? pageDisplayName(focusPageId) : "控制台当前筛选"}`,
        quality_checks: qualityChecks,
      }),
    });
    await loadEpisode(state.selectedEpisode);
    if (focusPageId && !focusedPageHasReviewWork(focusPageId)) {
      state.mediaFocusPageId = "";
    }
    await loadAgent();
    await loadDashboard();
    renderMedia();
    renderHomeTodos();
  } catch (error) {
    window.alert(error.message || "批量审核失败");
  } finally {
    setButtons(false);
  }
}

async function reviewAsset(assetId, action) {
  if (!assetId) {
    window.alert("素材尚未入库，请先同步入库。");
    return;
  }
  setButtons(true);
  try {
    await api(`/api/assets/${encodeURIComponent(assetId)}/review`, {
      method: "POST",
      body: JSON.stringify({ action }),
    });
    await loadEpisode(state.selectedEpisode);
  } catch (error) {
    window.alert(error.message || "素材审核失败");
  } finally {
    setButtons(false);
  }
}

async function lockAsset(assetId, locked) {
  if (!assetId) {
    window.alert("素材尚未入库，请先同步入库。");
    return;
  }
  setButtons(true);
  try {
    await api(`/api/assets/${encodeURIComponent(assetId)}/lock`, {
      method: "POST",
      body: JSON.stringify({ locked }),
    });
    await loadEpisode(state.selectedEpisode);
  } catch (error) {
    window.alert(error.message || "素材锁定失败");
  } finally {
    setButtons(false);
  }
}

async function bindAssetSetting(assetId, settingItemId) {
  if (!assetId) {
    window.alert("素材尚未入库，请先同步入库。");
    return;
  }
  setButtons(true);
  try {
    await api(`/api/assets/${encodeURIComponent(assetId)}/setting`, {
      method: "POST",
      body: JSON.stringify({ setting_item_id: settingItemId || null }),
    });
    await loadEpisode(state.selectedEpisode);
  } catch (error) {
    window.alert(error.message || "绑定设定失败");
  } finally {
    setButtons(false);
  }
}

function settingTypeLabel(value) {
  return {
    character: "角色",
    location: "场景",
    prop: "道具/武器",
    faction: "组织/阵营",
    world_rule: "世界观",
    style_rule: "画风规范",
  }[value] || value || "未分类";
}

function reviewStatusLabel(value) {
  return {
    draft: "草稿",
    pending_review: "待审核",
    approved: "已通过",
    needs_work: "待修改",
    rejected: "已退回",
  }[value] || value || "未知";
}

function settingImportanceLabel(value) {
  return {
    core: "核心",
    high: "重要",
    normal: "普通",
    low: "低",
  }[value] || value || "普通";
}

function usageSummaryText(usage = {}) {
  const outputs = Number(usage.outputs || 0);
  const chapters = Number(usage.chapters || 0);
  const pages = Number(usage.pages || 0);
  const panels = Number(usage.panels || 0);
  const bindings = Number(usage.asset_bindings || 0);
  const parts = [];
  if (chapters) parts.push(`${chapters} 章`);
  if (pages) parts.push(`${pages} 页`);
  if (panels) parts.push(`${panels} 格`);
  if (outputs) parts.push(`${outputs} 个输出`);
  if (bindings) parts.push(`${bindings} 个素材绑定`);
  return parts.length ? parts.join(" · ") : "未被生成引用";
}

function usageReferenceText(usage = {}) {
  const refs = Array.isArray(usage.references) ? usage.references : [];
  if (!refs.length) return "";
  return refs
    .slice(0, 3)
    .map((item) => item.label || [episodeCode(item.chapter_number), pageDisplayName(item.page_id), item.panel_id ? fullPanelDisplayName(item.panel_id, item.page_id) : ""].filter(Boolean).join(" · "))
    .filter(Boolean)
    .join(" / ");
}

function usageLine(usage = {}) {
  const summary = usageSummaryText(usage);
  const ref = usageReferenceText(usage);
  return ref ? `${summary} · 最近：${ref}` : summary;
}

function renderSettingsLibrary() {
  const items = state.settingsLibrary?.items || [];
  const active = state.projects.find((item) => item.slug === state.activeProject);
  const metric = $("settingScopeMetric");
  const context = $("settingContextLine");
  if (metric) metric.textContent = `${active?.title || state.activeProject || "当前小说"} · ${items.length} 条设定`;
  if (context) {
    const locked = items.filter((item) => item.locked).length;
    const pending = items.filter((item) => ["draft", "pending_review"].includes(item.review_status)).length;
    context.textContent = `待审核 ${pending} 条 · 已锁定 ${locked} 条 · 设定属于整本小说`;
  }
  renderSettingSummary(items);
  renderSettingList(items);
  if (!state.selectedSettingId && items[0]) fillSettingEditor(items[0]);
}

function renderSettingSummary(items) {
  const box = $("settingSummary");
  if (!box) return;
  const typeCounts = items.reduce((acc, item) => {
    acc[item.item_type] = (acc[item.item_type] || 0) + 1;
    return acc;
  }, {});
  const statusCounts = items.reduce((acc, item) => {
    acc[item.review_status] = (acc[item.review_status] || 0) + 1;
    return acc;
  }, {});
  box.innerHTML = `
    <div><span>总数</span><strong>${items.length}</strong></div>
    <div><span>待审核</span><strong>${statusCounts.pending_review || statusCounts.draft || 0}</strong></div>
    <div><span>已通过</span><strong>${statusCounts.approved || 0}</strong></div>
    <div><span>已锁定</span><strong>${items.filter((item) => item.locked).length}</strong></div>
    <div><span>角色</span><strong>${typeCounts.character || 0}</strong></div>
    <div><span>场景</span><strong>${typeCounts.location || 0}</strong></div>
    <div><span>已引用</span><strong>${items.filter((item) => Number(item.usage?.outputs || 0) > 0).length}</strong></div>
  `;
}

function filteredSettings(items) {
  const keyword = ($("settingSearch")?.value || "").trim().toLowerCase();
  const type = $("settingTypeFilter")?.value || "all";
  const status = $("settingStatusFilter")?.value || "all";
  return items.filter((item) => {
    const haystack = `${item.name} ${item.description} ${item.visual_prompt} ${(item.aliases || []).join(" ")}`.toLowerCase();
    return (!keyword || haystack.includes(keyword))
      && (type === "all" || item.item_type === type)
      && (status === "all" || item.review_status === status);
  });
}

function renderSettingList(items) {
  const box = $("settingList");
  if (!box) return;
  const visible = filteredSettings(items);
  if (!visible.length) {
    box.innerHTML = `<div class="empty">没有符合条件的设定</div>`;
    return;
  }
  box.innerHTML = "";
  const groups = visible.reduce((acc, item) => {
    const key = item.item_type || "unknown";
    if (!acc[key]) acc[key] = [];
    acc[key].push(item);
    return acc;
  }, {});
  Object.entries(groups)
    .sort(([left], [right]) => settingTypeSortOrder(left) - settingTypeSortOrder(right) || settingTypeLabel(left).localeCompare(settingTypeLabel(right), "zh-CN"))
    .forEach(([type, groupItems]) => {
      const section = document.createElement("section");
      section.className = "setting-group";
      const approved = groupItems.filter((item) => item.review_status === "approved").length;
      const locked = groupItems.filter((item) => item.locked).length;
      section.innerHTML = `
        <header class="setting-group-head">
          <div>
            <strong>${escapeHtml(settingTypeLabel(type))}</strong>
            <span>${groupItems.length} 条 · 已通过 ${approved} · 已锁定 ${locked}</span>
          </div>
        </header>
        <div class="setting-group-list"></div>
      `;
      const list = section.querySelector(".setting-group-list");
      for (const item of groupItems) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "setting-item" + (String(item.id) === String(state.selectedSettingId) ? " active" : "");
        button.innerHTML = `
          <span>${escapeHtml(settingImportanceLabel(item.importance))}</span>
          <strong>${escapeHtml(item.name || "未命名设定")}</strong>
          <small>${escapeHtml(reviewStatusLabel(item.review_status))}${item.locked ? " · 已锁定" : ""}</small>
          <small class="reference-line">${escapeHtml(usageSummaryText(item.usage))}</small>
          <p>${escapeHtml(displaySummaryText(item.description, "暂无描述"))}</p>
          ${item.visual_prompt ? `<small class="setting-prompt-line">视觉提示：${escapeHtml(displaySummaryText(item.visual_prompt, ""))}</small>` : ""}
        `;
        button.addEventListener("click", () => fillSettingEditor(item));
        list.append(button);
      }
      box.append(section);
    });
}

function fillSettingEditor(item = null) {
  state.selectedSettingId = item?.id ? String(item.id) : "";
  state.settingPromptRefresh = null;
  state.settingPromptRefreshApplied = null;
  setValue("settingId", state.selectedSettingId);
  setValue("settingItemType", item?.item_type || "character");
  setValue("settingName", item?.name || "");
  setValue("settingAliases", (item?.aliases || []).join(", "));
  setValue("settingFirstChapter", item?.first_chapter_number || "");
  setValue("settingChapters", (item?.chapter_numbers || []).join(", "));
  setValue("settingDescription", item?.description || "");
  setValue("settingVisualPrompt", item?.visual_prompt || "");
  setValue("settingNegativePrompt", item?.negative_prompt || "");
  $("settingEditorTitle").textContent = item?.id ? `编辑设定 · ${item.name}` : "新增设定";
  $("settingEditorBadge").textContent = item?.id ? reviewStatusLabel(item.review_status) : "待编辑";
  $("settingLockButton").textContent = item?.locked ? "解除锁定" : "锁定设定";
  renderSettingUsage(item);
  renderSettingPromptRefresh();
  renderSettingList(state.settingsLibrary?.items || []);
}

function renderSettingUsage(item = null) {
  const existing = document.querySelector(".setting-usage-panel");
  if (existing) existing.remove();
  const actions = document.querySelector(".setting-editor-actions");
  if (!actions || !item?.id) return;
  const usage = item.usage || {};
  const refs = Array.isArray(usage.references) ? usage.references : [];
  const panel = document.createElement("section");
  panel.className = "setting-usage-panel";
  panel.innerHTML = `
    <span>引用关系</span>
    <strong>${escapeHtml(usageSummaryText(usage))}</strong>
    <ul>
      ${refs.length ? refs.slice(0, 5).map((ref) => `
        <li>
          <b>${escapeHtml(ref.label || "未绑定位置")}</b>
          <small>${escapeHtml(reviewStatusLabel(ref.review_status || ""))}${ref.output_type ? ` · ${escapeHtml(ref.output_type === "page" ? "页面" : "分镜")}` : ""}</small>
        </li>
      `).join("") : `<li><b>暂无生成引用</b><small>审核并锁定后会进入后续生成上下文</small></li>`}
    </ul>
  `;
  actions.before(panel);
}

function settingPayloadFromEditor(extra = {}) {
  return {
    item_type: $("settingItemType").value,
    name: $("settingName").value.trim(),
    aliases: $("settingAliases").value,
    first_chapter_number: $("settingFirstChapter").value,
    chapter_numbers: $("settingChapters").value,
    description: $("settingDescription").value.trim(),
    visual_prompt: $("settingVisualPrompt").value.trim(),
    negative_prompt: $("settingNegativePrompt").value.trim(),
    ...extra,
  };
}

function settingRefreshExtraPayload() {
  const id = $("settingId").value;
  const applied = state.settingPromptRefreshApplied;
  if (!applied || String(applied.settingId || "") !== String(id || "")) return {};
  const payload = applied.payload || {};
  return {
    source_evidence: payload.source_evidence || [],
    raw: payload.raw || {},
    relations: payload.relations || {},
    importance: payload.importance || "normal",
  };
}

function candidateToEditorPayload(item = {}) {
  return {
    item_type: item.item_type || "character",
    name: item.name || "",
    aliases: item.aliases || [],
    first_chapter_number: item.first_chapter_number || "",
    chapter_numbers: item.chapter_numbers || [],
    description: item.description || "",
    visual_prompt: item.visual_prompt || "",
    negative_prompt: item.negative_prompt || "",
  };
}

function renderSettingSuggestions(items = []) {
  const box = $("settingSuggestResults");
  const badge = $("settingSuggestBadge");
  if (!box) return;
  if (badge) badge.textContent = items.length ? `候选 ${items.length}` : "待输入";
  if (!items.length) {
    box.innerHTML = "";
    return;
  }
  box.innerHTML = items.map((item, index) => `
    <article class="setting-suggest-card">
      <div>
        <span>${escapeHtml(settingTypeLabel(item.item_type))} · ${escapeHtml((item.chapter_numbers || []).length ? `出现章节 ${(item.chapter_numbers || []).slice(0, 5).join(", ")}` : "待确认章节")}</span>
        <strong>${escapeHtml(item.name || "未命名候选")}</strong>
        <p>${escapeHtml(displaySummaryText(item.description, "暂无描述"))}</p>
        ${item.visual_prompt ? `<small class="setting-prompt-line">视觉提示：${escapeHtml(displaySummaryText(item.visual_prompt, ""))}</small>` : ""}
      </div>
      <button data-setting-suggest-use="${index}" type="button">采用</button>
    </article>
  `).join("");
  box.querySelectorAll("[data-setting-suggest-use]").forEach((button) => {
    button.addEventListener("click", () => {
      const item = items[Number(button.dataset.settingSuggestUse || 0)];
      fillSettingEditor(candidateToEditorPayload(item));
      $("settingId").value = "";
      state.selectedSettingId = "";
      $("settingEditorTitle").textContent = "新增设定";
      $("settingEditorBadge").textContent = "待保存";
    });
  });
}

async function suggestSettingFromInstruction() {
  if (!state.activeProject) return;
  const instruction = ($("settingSuggestInstruction")?.value || "").trim();
  if (!instruction) {
    window.alert("请输入需要补充的设定说明");
    return;
  }
  setButtons(true);
  try {
    const result = await api(`/api/novels/${encodeURIComponent(state.activeProject)}/suggest-settings`, {
      method: "POST",
      body: JSON.stringify({ instruction, limit: 12 }),
    });
    renderSettingSuggestions(result.items || []);
  } catch (error) {
    window.alert(error.message || "扫描候选设定失败");
  } finally {
    setButtons(false);
  }
}

function renderSettingPromptRefresh() {
  const box = $("settingRefreshResult");
  const applyButton = $("settingApplyRefreshButton");
  if (!box) return;
  const result = state.settingPromptRefresh;
  if (applyButton) applyButton.disabled = !result?.editor_payload || Boolean(result?.loading);
  if (result?.loading) {
    const elapsed = Math.max(0, Math.round((Date.now() - Number(result.refreshStartedAt || Date.now())) / 1000));
    const isAi = result.extraction_mode === "ai";
    box.innerHTML = `
      <div class="setting-refresh-running">
        <div class="setting-refresh-running-head">
          <span class="setting-refresh-spinner" aria-hidden="true"></span>
          <div>
            <strong>${isAi ? "AI 增强处理中" : "脚本提取处理中"}</strong>
            <span>已耗时 ${elapsed} 秒 · ${result.mode === "overwrite" ? "覆盖预览" : "补全预览"}</span>
          </div>
        </div>
        <div class="setting-refresh-progress" aria-hidden="true"></div>
        <p>${isAi ? "正在读取关联章节、召回证据并调用小说处理模型。完成后会先进入预览，不会直接保存到数据库。" : "正在根据全文索引和来源证据提取描述与提示词。"}</p>
      </div>
    `;
    return;
  }
  if (result?.error) {
    box.innerHTML = `
      <div class="setting-refresh-card">
        <span>提取失败</span>
        <strong>当前结果不可用</strong>
        <p>${escapeHtml(result.error)}</p>
      </div>
    `;
    return;
  }
  if (!result?.editor_payload) {
    box.innerHTML = `<p>选择一个设定后，可针对该设定重新提取描述、视觉提示词和来源证据。</p>`;
    return;
  }
  const labels = {
    description: "描述",
    visual_prompt: "视觉提示词",
    negative_prompt: "负面提示词",
    first_chapter_number: "首次出现",
    chapter_numbers: "出现章节",
    source_evidence: "来源证据",
  };
  const rows = Object.entries(result.changes || {})
    .filter(([, change]) => change?.changed)
    .map(([field, change]) => `
      <li>
        <strong>${escapeHtml(labels[field] || field)}</strong>
        <span>${escapeHtml(displaySummaryText(Array.isArray(change.after) ? change.after.join(", ") : String(change.after ?? ""), "无变化"))}</span>
      </li>
    `).join("");
  const candidate = result.candidate || {};
  const enhancement = result.enhancement || {};
  const enhancementText = enhancement.requested
    ? enhancement.used
      ? `AI 增强已使用${enhancement.model ? ` · ${enhancement.model}` : ""}`
      : `AI 增强未使用：${enhancement.error || "模型未返回可用结果，已保留脚本提取"}`
    : "脚本提取";
  box.innerHTML = `
    <div class="setting-refresh-card">
      <span>${escapeHtml(result.mode === "overwrite" ? "覆盖预览" : "补全预览")}${result.locked ? " · 已锁定设定" : ""} · ${escapeHtml(enhancementText)}</span>
      <strong>${escapeHtml(candidate.name || "当前设定")}</strong>
      <p>${escapeHtml(displaySummaryText(candidate.visual_prompt || candidate.description || "", "未提取到提示词"))}</p>
      <ul>${rows || `<li><strong>无字段变化</strong><span>当前模式下没有可应用的新内容</span></li>`}</ul>
    </div>
  `;
}

function startSettingPromptRefreshProgress(mode, extractionMode) {
  if (state.settingPromptRefreshTimer) {
    window.clearInterval(state.settingPromptRefreshTimer);
    state.settingPromptRefreshTimer = null;
  }
  state.settingPromptRefresh = {
    loading: true,
    mode,
    extraction_mode: extractionMode,
    refreshStartedAt: Date.now(),
  };
  state.settingPromptRefreshApplied = null;
  renderSettingPromptRefresh();
  state.settingPromptRefreshTimer = window.setInterval(() => {
    if (!state.settingPromptRefresh?.loading) {
      window.clearInterval(state.settingPromptRefreshTimer);
      state.settingPromptRefreshTimer = null;
      return;
    }
    renderSettingPromptRefresh();
  }, 1000);
}

function stopSettingPromptRefreshProgress() {
  if (!state.settingPromptRefreshTimer) return;
  window.clearInterval(state.settingPromptRefreshTimer);
  state.settingPromptRefreshTimer = null;
}

async function refreshSelectedSettingPrompt() {
  const id = $("settingId").value;
  if (!id) {
    alertDialog("请先选择一个设定条目", { type: "warn" });
    return;
  }
  const mode = $("settingRefreshMode")?.value || "fill_missing";
  const extractionMode = $("settingRefreshExtractionMode")?.value || "script";
  if (mode === "overwrite") {
    const ok = await confirmDialog("覆盖模式会把重新提取的内容应用到编辑器。仍需点击“保存设定”才会写入数据库。确认继续？", {
      title: "覆盖预览",
      kind: "确认",
      confirmText: "继续提取",
    });
    if (!ok) return;
  }
  if (extractionMode === "ai") {
    const ok = await confirmDialog("AI 增强会调用小说处理模型，可能需要更长时间并消耗 API。结果仍只进入预览，不会直接保存。确认继续？", {
      title: "AI 增强",
      kind: "模型调用",
      confirmText: "开始增强",
    });
    if (!ok) return;
  }
  setButtons(true);
  startSettingPromptRefreshProgress(mode, extractionMode);
  try {
    state.settingPromptRefresh = await api(`/api/settings/${encodeURIComponent(id)}/refresh-prompt`, {
      method: "POST",
      body: JSON.stringify({ mode, extraction_mode: extractionMode }),
    });
    state.settingPromptRefreshApplied = null;
    renderSettingPromptRefresh();
    const enhancement = state.settingPromptRefresh?.enhancement || {};
    if (extractionMode === "ai") {
      notify(enhancement.used ? "AI 增强完成，结果已进入预览。" : `AI 增强未返回可用结果，已保留脚本提取。${enhancement.error || ""}`.trim(), enhancement.used ? "success" : "warn", "重提提示词");
    } else {
      notify("脚本提取完成，结果已进入预览。", "success", "重提提示词");
    }
  } catch (error) {
    state.settingPromptRefresh = {
      error: error.message || "重新提取提示词失败",
    };
    renderSettingPromptRefresh();
    alertDialog(error.message || "重新提取提示词失败", { type: "error", title: "重提提示词失败" });
  } finally {
    stopSettingPromptRefreshProgress();
    setButtons(false);
  }
}

async function applySettingPromptRefresh() {
  const result = state.settingPromptRefresh;
  const payload = result?.editor_payload;
  if (!payload) {
    alertDialog("请先重新提取提示词", { type: "warn" });
    return;
  }
  if (result.locked) {
    const ok = await confirmDialog("当前设定已锁定。应用到编辑器后仍需保存才会覆盖，请确认你要继续。", {
      title: "已锁定设定",
      kind: "确认",
      confirmText: "应用到编辑器",
    });
    if (!ok) return;
  }
  setValue("settingDescription", payload.description || "");
  setValue("settingVisualPrompt", payload.visual_prompt || "");
  setValue("settingNegativePrompt", payload.negative_prompt || "");
  setValue("settingFirstChapter", payload.first_chapter_number || "");
  setValue("settingChapters", (payload.chapter_numbers || []).join(", "));
  state.settingPromptRefreshApplied = {
    settingId: result.setting_id,
    payload,
  };
  renderSettingPromptRefresh();
}

async function scanSettingsLibrary() {
  if (!state.activeProject) return;
  const extractionMode = $("settingScanExtractionMode")?.value || "script";
  setButtons(true);
  try {
    const preview = await api(`/api/novels/${encodeURIComponent(state.activeProject)}/scan-settings-preview?extraction_mode=${encodeURIComponent(extractionMode)}`);
    const modeLabel = extractionMode === "ai" ? "AI 增强" : "脚本扫描";
    const message = [
      `小说：${preview.project?.title || state.activeProject}`,
      `扫描模式：${modeLabel}`,
      `章节数：${Number(preview.chapter_count || 0)}`,
      `现有设定：${Number(preview.existing_settings || 0)} 条`,
      `已锁定：${Number(preview.locked_settings || 0)} 条`,
      `待审核：${Number(preview.pending_settings || 0)} 条`,
      `预计候选：${Number(preview.estimated_candidates || 0)} 条`,
      `小说处理模型：${preview.model?.name || "未配置"}（${sourceLabel(preview.model?.source)}）`,
      "",
      ...(extractionMode === "ai" ? ["AI 增强会逐条调用小说处理模型，耗时和 API 消耗会明显高于脚本扫描。"] : []),
      "确认后会创建后台任务，结果进入任务中心；不会自动锁定设定。",
    ].join("\n");
    const ok = await confirmDialog(message, {
      title: "全书设定扫描",
      kind: modeLabel,
      confirmText: "创建任务",
    });
    if (!ok) return;
    const result = await api(`/api/novels/${encodeURIComponent(state.activeProject)}/scan-settings`, {
      method: "POST",
      body: JSON.stringify({ limit: 80, confirmed: true, extraction_mode: extractionMode }),
    });
    state.selectedTaskJobId = result.id || result.job_id || "";
    await loadJobs();
    await loadProjects();
    switchModule("taskCenter");
  } catch (error) {
    window.alert(error.message || "启动全书扫描失败");
  } finally {
    setButtons(false);
  }
}

async function saveSetting() {
  if (!$("settingName").value.trim()) {
    window.alert("设定名称不能为空");
    return;
  }
  const id = $("settingId").value;
  const before = id
    ? (state.settingsLibrary?.items || []).find((entry) => String(entry.id) === String(id))
    : null;
  const path = id ? `/api/settings/${encodeURIComponent(id)}` : `/api/novels/${encodeURIComponent(state.activeProject)}/settings`;
  const method = id ? "PATCH" : "POST";
  setButtons(true);
  try {
    const result = await api(path, {
      method,
      body: JSON.stringify(settingPayloadFromEditor(settingRefreshExtraPayload())),
    });
    await loadSettingsLibrary();
    fillSettingEditor(result.item);
    if (before?.review_status === "approved" && result.item?.review_status === "pending_review") {
      notify("设定已保存。由于已通过内容发生修改，状态已回到待审核，请重新确认。", "warn", "保存设定");
    } else {
      notify("设定已保存。", "success", "保存设定");
    }
  } catch (error) {
    window.alert(error.message || "保存设定失败");
  } finally {
    setButtons(false);
  }
}

async function reviewSetting(action) {
  const id = $("settingId").value;
  if (!id) {
    window.alert("请先选择一个设定条目");
    return;
  }
  setButtons(true);
  try {
    const result = await api(`/api/settings/${encodeURIComponent(id)}/review`, {
      method: "POST",
      body: JSON.stringify({ action }),
    });
    await loadSettingsLibrary();
    fillSettingEditor(result.item);
  } catch (error) {
    window.alert(error.message || "审核设定失败");
  } finally {
    setButtons(false);
  }
}

async function toggleSettingLock() {
  const id = $("settingId").value;
  if (!id) {
    window.alert("请先选择一个设定条目");
    return;
  }
  const item = (state.settingsLibrary?.items || []).find((entry) => String(entry.id) === String(id));
  const locked = !item?.locked;
  setButtons(true);
  try {
    const result = await api(`/api/settings/${encodeURIComponent(id)}/lock`, {
      method: "POST",
      body: JSON.stringify({ locked }),
    });
    await loadSettingsLibrary();
    fillSettingEditor(result.item);
  } catch (error) {
    window.alert(error.message || "锁定设定失败");
  } finally {
    setButtons(false);
  }
}

function filteredAssetCategories(assets) {
  const keyword = ($("assetSearch")?.value || "").trim().toLowerCase();
  const usage = state.assetUsageFilter || "all";
  const selectedCategory = state.assetCategory || "all";
  const output = {};
  for (const [category, items] of Object.entries(assets?.categories || {})) {
    if (selectedCategory !== "all" && category !== selectedCategory) continue;
    const filtered = items.filter((item) => {
      const episodeText = (item.episodes || []).map((episode) => `${episode.episode_id} ${episode.episode_title}`).join(" ");
      const haystack = `${item.alias} ${item.label} ${item.category_label} ${item.path} ${episodeText}`.toLowerCase();
      const matchesKeyword = !keyword || haystack.includes(keyword);
      const matchesUsage =
        usage === "all" ||
        (usage === "current" && item.is_used_in_current) ||
        (usage === "unused-current" && !item.is_used_in_current) ||
        (usage === "missing" && !item.exists);
      return matchesKeyword && matchesUsage;
    });
    output[category] = filtered;
  }
  return output;
}

function renderAssetCategoryFilters(assets) {
  const box = $("assetCategoryFilters");
  if (!box || box.dataset.renderedFor === String(assets?.total_assets || 0)) return;
  box.dataset.renderedFor = String(assets?.total_assets || 0);
  box.innerHTML = "";
  const buttons = [["all", "全部", Number(assets?.total_assets || 0)]];
  for (const [category, label] of Object.entries(assets?.labels || {})) {
    const count = Number((assets?.categories?.[category] || []).length);
    if (!count) continue;
    buttons.push([category, label, count]);
  }
  for (const [category, label, count] of buttons) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.assetCategory = category;
    button.className = category === state.assetCategory ? "active" : "";
    button.innerHTML = `<span>${escapeHtml(label)}</span><strong>${count}</strong>`;
    button.addEventListener("click", () => {
      state.assetCategory = category;
      box.querySelectorAll("button").forEach((item) => item.classList.toggle("active", item === button));
      renderAssets();
    });
    box.append(button);
  }
}

function assetUsageText(item) {
  const currentText = item.is_used_in_current
    ? `本章 ${Number(item.current_panel_count || 0)} 格`
    : "本章未用";
  return `${currentText} · ${assetEpisodeSummary(item)}`;
}

function assetUsageDetail(item) {
  const episodeLabels = (item.episodes || [])
    .map((episode) => episodeDisplayName(episode))
    .filter(Boolean);
  const currentText = item.is_used_in_current
    ? `本章使用 ${Number(item.current_panel_count || 0)} 格`
    : "本章未使用";
  return `${currentText} · 出现：${episodeLabels.join("、") || "未绑定章节"}`;
}

function assetEpisodeSummary(item) {
  const codes = (item.episodes || [])
    .map((episode) => episodeCode(episode))
    .filter(Boolean);
  if (!codes.length) return "未绑定";
  if (codes.length === 1) return codes[0];
  if (codes.length === 2) return codes.join("、");
  return `${codes[0]}-${codes[codes.length - 1]}`;
}

function episodeCode(value) {
  const number = episodeNumberFrom(value);
  return number ? `第 ${number} 章` : "";
}

function assetDisplayName(alias) {
  return String(alias || "")
    .replace(/_(turnaround|reference)$/i, "")
    .replaceAll("_", " ");
}

function assetFallbackTitle(item) {
  const prefix = item.category_label || "素材";
  const id = item.db_asset_id || "";
  return id ? `${prefix} #${id}` : `未绑定${prefix}`;
}

function assetPrimaryTitle(item) {
  return item.setting_name || item.db_title || assetFallbackTitle(item);
}

function assetSecondaryText(item) {
  const binding = item.setting_name
    ? `${item.setting_type_label || "设定"} · ${reviewStatusLabel(item.setting_review_status)}${item.setting_locked ? " · 已锁定" : ""}`
    : "未绑定小说设定";
  return `${binding} · ${assetUsageText(item)}`;
}

function assetUsageSummaryText(item) {
  const usage = item.usage_summary || {};
  const summary = usageSummaryText(usage);
  const legacy = assetUsageText(item);
  return summary === "未被生成引用" ? legacy : summary;
}

function jobTargetDisplay(job) {
  if (job.panel_id) return fullPanelDisplayName(job.panel_id, job.page_id);
  if (job.asset_alias) return assetDisplayName(job.asset_alias);
  return "";
}

function displayPath(value) {
  const text = String(value || "");
  if (!text) return "";
  return stripInternalIdsFromText(text.split(/[\\/]/).pop() || text);
}

function seriesSourceLabel(value) {
  return {
    "Sou Shen Ji": "搜神记",
  }[value] || stripInternalIdsFromText(value || "系列");
}

function assetCard(item) {
  const image = item.exists && item.url
    ? `<img src="${item.url}" alt="${escapeHtml(item.alias)}" loading="lazy">`
    : `<div class="missing-thumb">缺失</div>`;
  const title = assetPrimaryTitle(item);
  const secondary = assetSecondaryText(item);
  const candidates = state.detail?.assets?.setting_candidates || [];
  const bindingControl = item.db_asset_id
    ? `<label class="asset-binding">
        <span>绑定设定</span>
        <select data-asset-setting="${escapeHtml(item.db_asset_id)}">
          <option value="">未绑定</option>
          ${candidates.map((setting) => `
            <option value="${escapeHtml(setting.id)}" ${String(setting.id) === String(item.setting_item_id || "") ? "selected" : ""}>
              ${escapeHtml(setting.name)} / ${escapeHtml(setting.type_label || settingTypeLabel(setting.item_type))}
            </option>
          `).join("")}
        </select>
      </label>`
    : `<div class="asset-binding muted">同步入库后可绑定小说设定</div>`;
  const viewAction = item.url
    ? `<a href="${item.url}" target="_blank" rel="noreferrer" title="查看素材原图" aria-label="查看素材原图"><i aria-hidden="true">⌕</i><span>查看</span></a>`
    : `<span title="素材文件缺失"><i aria-hidden="true">⌕</i><span>缺失</span></span>`;
  const regenAction = item.can_regenerate && item.db_asset_id
    ? `<button data-asset-regenerate="${escapeHtml(item.alias)}" data-asset-id="${escapeHtml(item.db_asset_id || "")}" data-asset-path="${escapeHtml(item.path)}" data-asset-category="${escapeHtml(item.category)}" type="button" title="重新生成素材" aria-label="重新生成素材"><i aria-hidden="true">↻</i><span>重生成</span></button>`
    : `<span title="${escapeHtml(item.db_asset_id ? (item.action_note || "不可生成") : "先同步素材入库")}"><i aria-hidden="true">×</i><span>${item.db_asset_id ? "不可生成" : "先入库"}</span></span>`;
  const dbState = item.db_synced
    ? `${reviewStatusLabel(item.db_review_status)}${item.db_locked ? " · 已锁定" : ""}`
    : "未入库";
  const referenceLine = usageLine(item.usage_summary || {});
  const approveAction = item.db_asset_id
    ? `<button data-asset-review="${escapeHtml(item.db_asset_id)}" data-asset-action="approve" type="button" title="审核通过素材"><i aria-hidden="true">✓</i><span>通过</span></button>`
    : `<span title="先同步入库"><i aria-hidden="true">!</i><span>待入库</span></span>`;
  const needsWorkAction = item.db_asset_id
    ? `<button data-asset-review="${escapeHtml(item.db_asset_id)}" data-asset-action="needs_work" type="button" title="标记素材待修改"><i aria-hidden="true">?</i><span>待改</span></button>`
    : "";
  const lockAction = item.db_asset_id
    ? `<button data-asset-lock="${escapeHtml(item.db_asset_id)}" data-asset-locked="${item.db_locked ? "true" : "false"}" type="button" title="${item.db_locked ? "解除锁定" : "锁定素材"}"><i aria-hidden="true">${item.db_locked ? "□" : "■"}</i><span>${item.db_locked ? "解锁" : "锁定"}</span></button>`
    : "";
  return `
    <article class="asset-card" ${item.db_asset_id ? `data-asset-card-id="${escapeHtml(item.db_asset_id)}"` : ""}>
      ${image}
      <strong title="${escapeHtml(title)}">${escapeHtml(title)}</strong>
      <small title="${escapeHtml(assetUsageDetail(item))}">${escapeHtml(secondary)}</small>
      <small class="reference-line" title="${escapeHtml(referenceLine)}">${escapeHtml(assetUsageSummaryText(item))}</small>
      <small class="asset-db-state">${escapeHtml(dbState)}</small>
      ${bindingControl}
      <div class="asset-actions">${viewAction}${regenAction}</div>
      <div class="asset-review-actions">${approveAction}${needsWorkAction}${lockAction}</div>
    </article>
  `;
}

function renderMedia() {
  const box = $("mediaView");
  box.innerHTML = "";
  document.querySelectorAll("[data-media-filter]").forEach((button) => {
    button.classList.toggle("active", button.dataset.mediaFilter === state.mediaFilter);
  });
  const allItems = currentMediaItems();
  const focusPageId = state.mediaFocusPageId || "";
  updateOutputBatchButtons(focusPageId);
  const items = focusPageId
    ? allItems.filter((item) => item.page_id === focusPageId)
    : allItems;
  const dbSummary = state.detail?.media?.db_summary || {};
  const missing = missingPanelSummary();
  const outputBadge = $("outputDbBadge");
  if (outputBadge) {
    outputBadge.textContent = Number(dbSummary.synced || 0)
      ? `已入库 ${Number(dbSummary.synced || 0)}`
      : "待同步";
  }
  const preview = renderComicPreview();
  if (preview) {
    box.insertAdjacentHTML("beforeend", preview);
  }
  const missingNotice = state.mediaFilter === "panels" && missing.count
    ? `<section class="missing-panel-notice">
        <strong>待补分镜 ${missing.count}/${missing.total || missing.count}</strong>
        <span>可以逐格补生成，也可以在页面卡片中按页补齐缺失分镜。</span>
      </section>`
    : "";
  if (!items.length) {
    box.innerHTML = `${missingNotice}<div class="empty">当前筛选下还没有生成结果</div>`;
    return;
  }
  if (missingNotice) {
    box.insertAdjacentHTML("beforeend", missingNotice);
  }
  if (focusPageId) {
    const summary = focusedPageReviewSummary(items);
    box.insertAdjacentHTML("beforeend", `
      <section class="media-focus-notice">
        <div>
          <strong>正在聚焦 ${escapeHtml(pageDisplayName(focusPageId))}</strong>
          <span>只显示当前待审核页面相关输出，处理完后再继续下一页。</span>
        </div>
        <button id="clearMediaFocusButton" type="button" title="显示本章全部生成结果"><i aria-hidden="true">□</i><span>显示全部</span></button>
      </section>
      <section class="media-focus-summary" aria-label="当前页审核汇总">
        <div>
          <strong>本页审核</strong>
          <span>${escapeHtml(`页面 ${summary.pages} · 分镜 ${summary.panels}`)}</span>
        </div>
        <dl>
          <div><dt>待审核</dt><dd>${summary.pending}</dd></div>
          <div><dt>已通过</dt><dd>${summary.approved}</dd></div>
          <div><dt>待修改</dt><dd>${summary.needsWork}</dd></div>
          <div><dt>质量未检</dt><dd>${summary.qualityUnknown}</dd></div>
          <div><dt>质量问题</dt><dd>${summary.qualityFailed}</dd></div>
        </dl>
        <p>${escapeHtml(summary.nextAction)}</p>
      </section>
      ${renderFocusedPageContextSummary(items)}
    `);
  }
  for (const item of items) {
    const card = document.createElement("article");
    const missingPanel = item.kind === "panel" && !item.exists;
    card.className = "media-card " + (item.kind === "panel" ? "panel-media" : "page-media") + (item.placeholder ? " placeholder-media" : "") + (missingPanel ? " missing-panel-media" : "");
    const title = mediaTitleDisplay(item);
    const image = item.exists && item.url
      ? `<img src="${item.url}" alt="${escapeHtml(title)}" loading="lazy">`
      : `<div class="missing-thumb">未生成</div>`;
    const pageMissingCount = item.kind === "page"
      ? (state.detail?.media?.panels || []).filter((panel) => panel.page_id === item.page_id && !panel.exists).length
      : 0;
    const pageBlockers = item.kind === "page" ? mediaReviewBlockers(item.page_id) : { count: 0 };
    const pageBlocked = item.kind === "page" && pageMissingCount && pageBlockers.count;
    const pageActionTitle = pageBlocked
      ? mediaReviewBlockerMessage(pageBlockers)
      : (pageMissingCount ? "补齐本页缺失分镜并合成页面" : "本页分镜已齐全，可重新同步入库");
    const actions = item.kind === "panel"
      ? `<button data-regenerate="${escapeHtml(item.panel_id)}" data-page="${escapeHtml(item.page_id)}" type="button" title="${missingPanel ? "补生成缺失分镜" : "重新生成分镜"}"><i aria-hidden="true">↻</i><span>${missingPanel ? "补生成" : "重生成"}</span></button>`
      : `<button data-regenerate-page="${escapeHtml(item.page_id)}" type="button" title="${escapeHtml(pageActionTitle)}" ${pageMissingCount && !pageBlocked ? "" : "disabled"}><i aria-hidden="true">▣</i><span>补齐本页</span></button>
         ${item.url
          ? `<a href="${item.url}" target="_blank" rel="noreferrer" title="查看生成图"><i aria-hidden="true">⌕</i><span>查看</span></a>`
          : `<span title="图片尚未生成"><i aria-hidden="true">⌕</i><span>未生成</span></span>`}`;
    const dbReviewLabel = reviewStatusLabel(item.db_review_status || "pending_review");
    const dbState = item.db_synced
      ? `${dbReviewLabel} · 已入库`
      : "未入库";
    const reviewNote = item.db_review_comment
      ? `审核备注：${item.db_review_comment}`
      : (item.db_reviewed_at ? `最近审核：${compactTime(item.db_reviewed_at)}` : "");
    const reviewActions = item.db_output_id
      ? `<button data-output-review="${escapeHtml(item.db_output_id)}" data-output-action="approve" type="button" title="审核通过当前${item.kind === "panel" ? "分镜" : "页面"}"><i aria-hidden="true">✓</i><span>通过</span></button>
         <button data-output-review="${escapeHtml(item.db_output_id)}" data-output-action="needs_work" type="button" title="标记当前${item.kind === "panel" ? "分镜" : "页面"}需要修改"><i aria-hidden="true">?</i><span>待改</span></button>
         <button data-output-review="${escapeHtml(item.db_output_id)}" data-output-action="pending" type="button" title="退回待审核状态"><i aria-hidden="true">↺</i><span>待审</span></button>`
      : `<span title="先同步结果入库"><i aria-hidden="true">!</i><span>待入库</span></span>
         <span title="先同步结果入库"><i aria-hidden="true">!</i><span>待入库</span></span>
         <span title="先同步结果入库"><i aria-hidden="true">!</i><span>待入库</span></span>`;
    const productionState = item.placeholder
      ? "占位页 · 等待真实分镜"
      : (item.production_status === "partial"
        ? `部分页面 · 缺 ${pageMissingCount} 格`
        : (item.exists ? "真实输出" : (missingPanel ? "缺失分镜 · 可补生成" : "未生成")));
    card.innerHTML = `
      ${image}
      <div class="media-meta">
        <strong>${escapeHtml(title)}</strong>
        <small>${item.kind === "panel" ? "分镜图" : "页面图"}</small>
        <small>${escapeHtml(productionState)}</small>
        <small>${item.exists ? escapeHtml(compactTime(item.updated)) : "未生成"}</small>
        <small>${escapeHtml(dbState)}</small>
        ${item.db_synced ? renderGenerationContext(item) : ""}
        ${reviewNote ? `<small>${escapeHtml(reviewNote)}</small>` : ""}
      </div>
      ${item.db_synced ? renderOutputQuality(item) : ""}
      <div class="media-actions">${actions}</div>
      <div class="media-review-actions">${reviewActions}</div>
      ${item.db_synced ? renderOutputVersions(item) : ""}
    `;
    box.append(card);
  }
  box.querySelectorAll("[data-regenerate]").forEach((button) => {
    button.addEventListener("click", () => regeneratePanel(button.dataset.page, button.dataset.regenerate));
  });
  box.querySelectorAll("[data-regenerate-page]").forEach((button) => {
    button.addEventListener("click", () => regeneratePage(button.dataset.regeneratePage));
  });
  box.querySelectorAll("[data-output-review]").forEach((button) => {
    button.addEventListener("click", () => reviewOutput(button.dataset.outputReview, button.dataset.outputAction));
  });
  box.querySelectorAll("[data-quality-key]").forEach((button) => {
    button.addEventListener("click", () => toggleQualityStatus(button));
  });
  const clearFocus = $("clearMediaFocusButton");
  if (clearFocus) {
    clearFocus.addEventListener("click", () => {
      state.mediaFocusPageId = "";
      renderMedia();
    });
  }
  bindComicPreviewEvents();
}

function renderComicPreview() {
  const pages = generatedPages();
  if (!pages.length) {
    return `
      <section class="comic-preview empty-preview">
        <div>
          <strong>漫画预览</strong>
          <span>当前章节还没有可预览的页面图。生成完成后会自动显示在这里。</span>
        </div>
      </section>
    `;
  }
  const activeId = ensurePreviewPageId(pages);
  const activeIndex = Math.max(0, pages.findIndex((item) => item.page_id === activeId));
  const active = pages[activeIndex] || pages[0];
  const reviewText = reviewStatusLabel(active.db_review_status || "pending_review");
  const thumbs = pages.map((page, index) => `
    <button class="${page.page_id === active.page_id ? "active" : ""}" data-preview-page="${escapeHtml(page.page_id)}" type="button" title="${escapeHtml(pageDisplayName(page))}">
      <img src="${page.url}" alt="${escapeHtml(pageDisplayName(page))}" loading="lazy">
      <span>${index + 1}</span>
    </button>
  `).join("");
  return `
    <section class="comic-preview" aria-label="漫画预览">
      <header>
        <div>
          <span>漫画预览</span>
          <strong>${escapeHtml(pageDisplayName(active))}</strong>
          <small>${escapeHtml(`${activeIndex + 1}/${pages.length} · ${reviewText} · ${compactTime(active.updated)}`)}</small>
        </div>
        <div class="comic-preview-actions">
          <button data-preview-step="-1" type="button" ${activeIndex <= 0 ? "disabled" : ""} title="上一页"><i aria-hidden="true">‹</i><span>上一页</span></button>
          <button data-preview-step="1" type="button" ${activeIndex >= pages.length - 1 ? "disabled" : ""} title="下一页"><i aria-hidden="true">›</i><span>下一页</span></button>
          <a href="${active.url}" target="_blank" rel="noreferrer" title="打开原图"><i aria-hidden="true">⌕</i><span>原图</span></a>
        </div>
      </header>
      <div class="comic-preview-reader">
        <img src="${active.url}" alt="${escapeHtml(pageDisplayName(active))}">
      </div>
      <div class="comic-preview-strip" aria-label="页面缩略图">${thumbs}</div>
    </section>
  `;
}

function bindComicPreviewEvents() {
  const pages = generatedPages();
  if (!pages.length) return;
  document.querySelectorAll("[data-preview-page]").forEach((button) => {
    button.addEventListener("click", () => {
      state.previewPageId = button.dataset.previewPage || "";
      renderMedia();
    });
  });
  document.querySelectorAll("[data-preview-step]").forEach((button) => {
    button.addEventListener("click", () => {
      const activeId = ensurePreviewPageId(pages);
      const current = Math.max(0, pages.findIndex((item) => item.page_id === activeId));
      const nextIndex = Math.max(0, Math.min(pages.length - 1, current + Number(button.dataset.previewStep || 0)));
      state.previewPageId = pages[nextIndex]?.page_id || activeId;
      renderMedia();
    });
  });
}

function updateOutputBatchButtons(focusPageId = "") {
  const focused = Boolean(focusPageId);
  const labels = focused
    ? { approve: "本页通过", needs_work: "本页待改", pending: "本页待审" }
    : { approve: "批量通过", needs_work: "批量待改", pending: "批量待审" };
  const scope = focused ? `${pageDisplayName(focusPageId)}当前聚焦结果` : "当前筛选中已入库的生成结果";
  document.querySelectorAll("[data-output-batch]").forEach((button) => {
    const action = button.dataset.outputBatch || "";
    const strong = button.querySelector("strong");
    if (strong && labels[action]) strong.textContent = labels[action];
    const actionText = {
      approve: "审核通过",
      needs_work: "标记待修改",
      pending: "退回待审",
    }[action] || "批量审核";
    button.title = `${actionText}${scope}`;
  });
}

function renderQaText() {
  const text = state.status?.texts?.[state.qaTab] || "暂无内容";
  $("textOutput").textContent = displayReviewText(text);
}

function renderJobList(box, jobs = state.jobs) {
  if (!box) return;
  box.innerHTML = "";
  if (!jobs.length) {
    box.innerHTML = `<div class="empty">暂无任务记录</div>`;
    return;
  }
  for (const job of jobs) {
    const item = document.createElement("article");
    item.className = `job${String(job.id || "") === String(state.selectedTaskJobId || "") ? " active" : ""}`;
    const summary = job.result?.summary ? stripInternalIdsFromText(JSON.stringify(job.result.summary, null, 2)) : "";
    const importSummary = importSummaryHtml(job, { compact: true });
    const targetLabel = jobTargetDisplay(job);
    const target = targetLabel ? `<small>目标：${escapeHtml(targetLabel)}${job.backup_path ? " / 已备份旧图" : ""}</small>` : "";
    const diagnostics = jobDiagnosticsHtml(job);
    const progress = jobProgressHtml(job, { compact: true });
    const retryAction = canRetryJob(job)
      ? `<button class="job-retry" data-job-retry="${escapeHtml(job.id || "")}" type="button" title="使用原任务参数重新启动"><i aria-hidden="true">↻</i><span>重试任务</span></button>`
      : "";
    const cancelAction = canCancelJob(job)
      ? `<button class="job-cancel" data-job-cancel="${escapeHtml(job.id || "")}" type="button" title="取消正在运行的任务"><i aria-hidden="true">×</i><span>取消任务</span></button>`
      : "";
    item.innerHTML = `
      <div class="job-head">
        <strong>${escapeHtml(job.label)} / ${statusText(job.status)}</strong>
        <span>${escapeHtml(stageLabel(job.stage))}</span>
      </div>
      <small>${escapeHtml(job.started)}${job.finished ? ` -> ${escapeHtml(job.finished)}` : ""}</small>
      ${target}
      <small>${escapeHtml(displayPath(job.result_path || ""))}</small>
      ${progress}
      <div class="job-actions job-inline-actions">
        <button class="job-detail-button" data-job-detail="${escapeHtml(job.id || "")}" type="button" title="查看任务详情"><span aria-hidden="true">◎</span><span>查看详情</span></button>
      </div>
      ${diagnostics}
      ${importSummary}
      ${retryAction || cancelAction ? `<div class="job-actions">${retryAction}${cancelAction}</div>` : ""}
      ${summary ? `<details class="job-log"><summary>结果摘要</summary><pre>${escapeHtml(summary)}</pre></details>` : ""}
      ${job.stderr_tail ? `<details class="job-log"><summary>错误日志</summary><pre>${escapeHtml(stripInternalIdsFromText(job.stderr_tail))}</pre></details>` : ""}
    `;
    box.append(item);
  }
  box.querySelectorAll("[data-job-retry]").forEach((button) => {
    button.addEventListener("click", () => retryJob(button.dataset.jobRetry || ""));
  });
  box.querySelectorAll("[data-job-cancel]").forEach((button) => {
    button.addEventListener("click", () => cancelJob(button.dataset.jobCancel || ""));
  });
  box.querySelectorAll("[data-job-detail]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedTaskJobId = button.dataset.jobDetail || "";
      renderTaskCenter();
    });
  });
}

function canCancelJob(job) {
  return ["running", "queued", "starting"].includes(String(job?.status || ""));
}

function canRetryJob(job) {
  return ["failed", "waiting", "partial", "interrupted", "cancelled"].includes(String(job?.status || ""))
    && Boolean(job?.retry_payload && Object.keys(job.retry_payload).length);
}

function inferredJobProgress(job) {
  const raw = job && typeof job.progress === "object" && job.progress ? job.progress : {};
  const status = String(job?.status || "");
  const total = Math.max(Number(raw.total || 0), 1);
  let completed = Number(raw.completed || 0);
  let failed = Number(raw.failed || 0);
  if (!job?.progress) {
    if (["passed", "complete", "completed"].includes(status)) completed = 1;
    if (["failed", "error", "interrupted"].includes(status)) failed = 1;
  }
  completed = Math.max(0, Math.min(completed, total));
  failed = Math.max(0, Math.min(failed, total));
  const active = ["running", "queued", "starting"].includes(status);
  const cancelled = Boolean(raw.cancelled) || status === "cancelled";
  const interrupted = Boolean(raw.interrupted) || status === "interrupted";
  const waiting = Boolean(raw.waiting) || status === "waiting";
  const partial = Boolean(raw.partial) || status === "partial";
  const doneUnits = Math.min(total, completed + failed);
  let percent = total ? Math.round((doneUnits / total) * 100) : 0;
  if (active && percent === 0) percent = 8;
  if (waiting && percent === 0) percent = 12;
  if (cancelled && percent === 0) percent = 100;
  if (interrupted && percent === 0) percent = 100;
  percent = Math.max(0, Math.min(percent, 100));
  const current = raw.current || (active ? "运行中" : waiting ? "等待继续处理" : cancelled ? "已取消" : interrupted ? "服务重启后任务已中断" : partial ? "部分完成" : statusText(status));
  return { total, completed, failed, percent, current, active, cancelled, interrupted, waiting, partial };
}

function jobProgressHtml(job, options = {}) {
  const progress = inferredJobProgress(job);
  const compact = Boolean(options.compact);
  const classes = [
    "job-progress",
    compact ? "compact" : "",
    progress.active ? "active" : "",
    progress.cancelled ? "cancelled" : "",
    progress.interrupted ? "interrupted" : "",
    progress.waiting ? "waiting" : "",
    progress.failed || progress.interrupted ? "has-failure" : "",
  ].filter(Boolean).join(" ");
  const title = progress.total > 1 || progress.failed
    ? `${progress.completed}/${progress.total} 完成${progress.failed ? ` · ${progress.failed} 失败` : ""}`
    : progress.cancelled
      ? "已取消"
      : progress.interrupted
        ? "已中断"
        : progress.waiting
          ? "等待中"
          : progress.active
            ? `${progress.percent}%`
            : `${progress.completed}/${progress.total} 完成`;
  return `
    <div class="${classes}" aria-label="任务进度 ${escapeHtml(title)}">
      <div class="job-progress-track">
        <span class="job-progress-fill" style="width: ${progress.percent}%"></span>
      </div>
      <div class="job-progress-meta">
        <strong>${escapeHtml(title)}</strong>
        <span>${escapeHtml(stripInternalIdsFromText(String(progress.current || "")))}</span>
      </div>
    </div>
  `;
}

function renderJobs() {
  renderJobList($("jobs"), state.jobs);
  renderTaskCenter();
}

function taskStatusGroup(status) {
  const value = String(status || "");
  if (["running", "queued", "starting"].includes(value)) return "running";
  if (value === "waiting") return "waiting";
  if (["failed", "error", "interrupted"].includes(value)) return "failed";
  if (value === "cancelled") return "cancelled";
  if (["passed", "complete", "completed"].includes(value)) return "passed";
  return "other";
}

function renderTaskCenter() {
  const badge = $("taskCenterBadge");
  const summary = $("taskCenterSummary");
  const list = $("taskCenterJobs");
  const detail = $("taskDetail");
  if (!badge || !summary || !list) return;
  const counts = state.jobs.reduce((acc, job) => {
    const group = taskStatusGroup(job.status);
    acc.total += 1;
    acc[group] = (acc[group] || 0) + 1;
    if (job.diagnostics?.issues?.length || Number(job.diagnostics?.waiting_for_panels || 0)) acc.diagnostics += 1;
    return acc;
  }, { total: 0, running: 0, waiting: 0, failed: 0, passed: 0, other: 0, diagnostics: 0 });
  badge.textContent = counts.total ? `${counts.total} 条` : "暂无";
  const cards = [
    ["全部", counts.total, "最近任务记录"],
    ["运行中", counts.running, "正在执行或排队"],
    ["等待", counts.waiting, "需要继续处理"],
    ["失败", counts.failed, "需要诊断或重试"],
    ["已完成", counts.passed, "最近完成任务"],
    ["诊断", counts.diagnostics, "含结构化诊断"],
  ];
  summary.innerHTML = cards.map(([label, value, detail]) => `
    <article class="task-summary-card">
      <span>${escapeHtml(label)}</span>
      <strong>${Number(value || 0)}</strong>
      <small>${escapeHtml(detail)}</small>
    </article>
  `).join("");
  const filter = state.taskCenterFilter || "all";
  const visible = state.jobs.filter((job) => filter === "all" || taskStatusGroup(job.status) === filter);
  if (!visible.some((job) => String(job.id || "") === String(state.selectedTaskJobId || ""))) {
    state.selectedTaskJobId = visible[0]?.id || "";
    state.taskFilePreview = null;
  }
  renderJobList(list, visible);
  if (detail) renderTaskDetail(selectedTaskJob(visible));
}

function selectedTaskJob(jobs = state.jobs) {
  return jobs.find((job) => String(job.id || "") === String(state.selectedTaskJobId || "")) || jobs[0] || null;
}

function taskFileActionsHtml(job) {
  const actions = [
    ["结果文件", job.result_path, "select"],
    ["结果目录", job.result_path, "folder"],
    ["上下文文件", job.generation_context_path, "select"],
    ["备份文件", job.backup_path, "select"],
  ].filter(([, path]) => path);
  const previewPath = job.result_path || job.generation_context_path || "";
  if (!actions.length && !previewPath) return "";
  const preview = state.taskFilePreview;
  const shouldShowPreview = preview
    && String(preview.jobId || "") === String(job.id || "")
    && String(preview.path || "") === String(previewPath || "");
  return `
    <div class="task-file-actions">
      ${previewPath ? `
        <button type="button" data-file-preview="${escapeHtml(previewPath)}" title="预览任务结果文本">
          <span aria-hidden="true">▤</span><strong>预览结果</strong>
        </button>
        <button type="button" data-file-download="${escapeHtml(previewPath)}" title="下载任务结果文本">
          <span aria-hidden="true">⇩</span><strong>下载文本</strong>
        </button>
      ` : ""}
      ${actions.map(([label, path, mode]) => `
        <button type="button" data-file-action="${escapeHtml(mode)}" data-file-path="${escapeHtml(path)}" title="${escapeHtml(label)}">
          <span aria-hidden="true">${mode === "folder" ? "□" : "⌖"}</span><strong>${escapeHtml(label)}</strong>
        </button>
      `).join("")}
    </div>
    <div id="taskFilePreview" class="task-file-preview" ${shouldShowPreview ? "" : "hidden"}>
      ${shouldShowPreview ? taskFilePreviewHtml(preview.data, preview.path, preview.error) : ""}
    </div>
  `;
}

function settingScanActionLabel(value) {
  return {
    created: "新增",
    updated: "更新",
    unchanged: "未变",
    protected: "锁定保护",
  }[value] || "记录";
}

function settingScanReportHtml(job) {
  const report = job?.result?.report;
  if (!report || typeof report !== "object") return "";
  const metrics = [
    ["候选", report.candidate_count],
    ["入库", report.saved_count],
    ["新增", report.created_count],
    ["更新", report.updated_count],
    ["未变", report.unchanged_count],
    ["保护", report.protected_count],
  ];
  if (report.ai_requested) {
    metrics.push(["AI增强", report.ai_used_count]);
    metrics.push(["AI失败", report.ai_error_count]);
  }
  const typeRows = Object.entries(report.by_type || {})
    .map(([type, count]) => `<span><b>${escapeHtml(settingTypeLabel(type))}</b><em>${Number(count || 0)}</em></span>`)
    .join("");
  const statusRows = Object.entries(report.by_status || {})
    .map(([status, count]) => `<span><b>${escapeHtml(reviewStatusLabel(status))}</b><em>${Number(count || 0)}</em></span>`)
    .join("");
  const actionRows = Array.isArray(report.actions) ? report.actions.slice(0, 12).map((item) => {
    const changes = Array.isArray(item.changes) && item.changes.length
      ? ` · ${item.changes.slice(0, 3).join("、")}`
      : "";
    return `
      <li class="scan-action-${escapeHtml(item.action || "record")}">
        <strong>${escapeHtml(settingScanActionLabel(item.action))}</strong>
        <span>${escapeHtml(item.name || "未命名设定")}</span>
        <small>${escapeHtml(settingTypeLabel(item.item_type || ""))} · ${escapeHtml(reviewStatusLabel(item.review_status || ""))}${item.locked ? " · 已锁定" : ""}${escapeHtml(changes)}</small>
      </li>
    `;
  }).join("") : "";
  const protectedRows = Array.isArray(report.protected_items) ? report.protected_items.slice(0, 8).map((item) => `
    <li>
      <strong>${escapeHtml(item.name || "未命名设定")}</strong>
      <span>${escapeHtml(settingTypeLabel(item.item_type || ""))} · ${escapeHtml(reviewStatusLabel(item.review_status || ""))} · 已锁定</span>
    </li>
  `).join("") : "";
  const notes = Array.isArray(report.notes) ? report.notes.map((note) => `<li>${escapeHtml(note)}</li>`).join("") : "";
  return `
    <section class="task-detail-block setting-scan-report">
      <h3>扫描报告</h3>
      <div class="scan-report-metrics">
        ${metrics.map(([label, value]) => `
          <article>
            <span>${escapeHtml(label)}</span>
            <strong>${Number(value || 0)}</strong>
          </article>
        `).join("")}
      </div>
      <div class="scan-report-split">
        <div>
          <h4>类型分布</h4>
          <p class="scan-report-chips">${typeRows || "<span><b>无</b><em>0</em></span>"}</p>
        </div>
        <div>
          <h4>审核状态</h4>
          <p class="scan-report-chips">${statusRows || "<span><b>无</b><em>0</em></span>"}</p>
        </div>
      </div>
      ${protectedRows ? `
        <div class="scan-report-protected">
          <h4>锁定保护</h4>
          <ul>${protectedRows}</ul>
        </div>
      ` : ""}
      ${actionRows ? `
        <div class="scan-report-actions">
          <h4>本次处理</h4>
          <ul>${actionRows}</ul>
          ${report.truncated ? `<p>仅显示前 12 条，完整内容可预览任务结果。</p>` : ""}
        </div>
      ` : ""}
      ${notes ? `<ul class="scan-report-notes">${notes}</ul>` : ""}
    </section>
  `;
}

function renderTaskDetail(job) {
  const box = $("taskDetail");
  const badge = $("taskDetailBadge");
  if (!box) return;
  if (!job) {
    if (badge) badge.textContent = "未选择";
    box.className = "task-detail-empty";
    box.innerHTML = "当前筛选下没有任务。";
    return;
  }
  if (badge) badge.textContent = statusText(job.status);
  box.className = "task-detail";
  const targetLabel = jobTargetDisplay(job);
  const resultSummary = job.result?.summary ? stripInternalIdsFromText(JSON.stringify(job.result.summary, null, 2)) : "";
  const commandText = Array.isArray(job.command) ? job.command.join(" ") : String(job.command || "");
  const diagnostics = jobDiagnosticsHtml(job);
  const importSummary = importSummaryHtml(job, { compact: true });
  const scanReport = settingScanReportHtml(job);
  const fileActions = taskFileActionsHtml(job);
  const progress = jobProgressHtml(job);
  const taskActions = [
    canRetryJob(job)
      ? `<button class="job-retry" data-job-retry="${escapeHtml(job.id || "")}" type="button" title="使用原任务参数重新启动"><span aria-hidden="true">↻</span><strong>重试任务</strong></button>`
      : "",
    canCancelJob(job)
      ? `<button class="job-cancel" data-job-cancel="${escapeHtml(job.id || "")}" type="button" title="取消正在运行的任务"><span aria-hidden="true">×</span><strong>取消任务</strong></button>`
      : "",
  ].filter(Boolean).join("");
  const metaRows = [
    ["状态", statusText(job.status)],
    ["阶段", stageLabel(job.stage)],
    ["章节", job.episode_number ? `第 ${job.episode_number} 章` : "未指定"],
    ["退出码", job.exit_code === null || job.exit_code === undefined ? "未记录" : String(job.exit_code)],
    ["目标", targetLabel || "未记录"],
    ["开始", job.started || "未记录"],
    ["结束", job.finished || "未完成"],
  ];
  box.innerHTML = `
    <div class="task-detail-title">
      <strong>${escapeHtml(job.label || "未命名任务")}</strong>
      <span>${escapeHtml(job.id || "")}</span>
    </div>
    ${progress}
    <dl class="task-detail-grid">
      ${metaRows.map(([label, value]) => `
        <div>
          <dt>${escapeHtml(label)}</dt>
          <dd>${escapeHtml(value)}</dd>
        </div>
      `).join("")}
    </dl>
    <section class="task-detail-block">
      <h3>结果路径</h3>
      <p>${escapeHtml(displayPath(job.result_path || "未记录"))}</p>
      ${job.backup_path ? `<p>备份：${escapeHtml(displayPath(job.backup_path))}</p>` : ""}
      ${job.generation_context_path ? `<p>上下文：${escapeHtml(displayPath(job.generation_context_path))}</p>` : ""}
      ${fileActions}
    </section>
    ${taskActions ? `<div class="task-detail-actions">${taskActions}</div>` : ""}
    ${scanReport}
    ${diagnostics ? `<section class="task-detail-block"><h3>诊断</h3>${diagnostics}</section>` : ""}
    ${importSummary ? `<section class="task-detail-block"><h3>导入摘要</h3>${importSummary}</section>` : ""}
    ${commandText ? `<section class="task-detail-block"><h3>执行命令</h3><pre>${escapeHtml(stripInternalIdsFromText(commandText))}</pre></section>` : ""}
    ${resultSummary ? `<section class="task-detail-block"><h3>结果摘要</h3><pre>${escapeHtml(resultSummary)}</pre></section>` : ""}
    ${job.stdout_tail ? `<section class="task-detail-block"><h3>输出日志</h3><pre>${escapeHtml(stripInternalIdsFromText(job.stdout_tail))}</pre></section>` : ""}
    ${job.stderr_tail ? `<section class="task-detail-block"><h3>错误日志</h3><pre>${escapeHtml(stripInternalIdsFromText(job.stderr_tail))}</pre></section>` : ""}
  `;
  bindTaskFileActions(box);
  box.querySelectorAll("[data-job-cancel]").forEach((button) => {
    button.addEventListener("click", () => cancelJob(button.dataset.jobCancel || ""));
  });
  box.querySelectorAll("[data-job-retry]").forEach((button) => {
    button.addEventListener("click", () => retryJob(button.dataset.jobRetry || ""));
  });
}

function bindTaskFileActions(scope) {
  scope.querySelectorAll("[data-file-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const path = button.dataset.filePath || "";
      const mode = button.dataset.fileAction || "select";
      if (!path) return;
      const original = button.innerHTML;
      button.disabled = true;
      button.innerHTML = `<span aria-hidden="true">…</span><strong>打开中</strong>`;
      try {
        await api("/api/file-action", {
          method: "POST",
          body: JSON.stringify({ path, mode }),
        });
      } catch (error) {
        window.alert(error.message || "打开文件失败");
      } finally {
        button.disabled = false;
        button.innerHTML = original;
      }
    });
  });
  scope.querySelectorAll("[data-file-preview]").forEach((button) => {
    button.addEventListener("click", async () => {
      await previewTaskFile(button.dataset.filePreview || "");
    });
  });
  scope.querySelectorAll("[data-file-download]").forEach((button) => {
    button.addEventListener("click", async () => {
      await downloadTaskFile(button.dataset.fileDownload || "");
    });
  });
}

async function loadTaskFilePreview(path) {
  return api("/api/file-preview", {
    method: "POST",
    body: JSON.stringify({ path, max_bytes: 120000, max_lines: 300 }),
  });
}

function taskFilePreviewHtml(data, path, error = "") {
  if (error) return `<p>${escapeHtml(error)}</p>`;
  return `
    <header>
      <strong>${escapeHtml(data?.name || displayPath(path))}</strong>
      <span>${Number(data?.size || 0)} bytes${data?.truncated ? " / 已截断" : ""}</span>
    </header>
    <pre>${escapeHtml(stripInternalIdsFromText(data?.content || ""))}</pre>
  `;
}

async function previewTaskFile(path) {
  if (!path) return;
  const preview = $("taskFilePreview");
  if (!preview) return;
  preview.hidden = false;
  preview.innerHTML = `<p>读取中...</p>`;
  try {
    const data = await loadTaskFilePreview(path);
    state.taskFilePreview = { jobId: state.selectedTaskJobId || "", path, data, error: "" };
    preview.innerHTML = taskFilePreviewHtml(data, path);
  } catch (error) {
    const message = error.message || "文件预览失败";
    state.taskFilePreview = { jobId: state.selectedTaskJobId || "", path, data: null, error: message };
    preview.innerHTML = taskFilePreviewHtml(null, path, message);
  }
}

async function downloadTaskFile(path) {
  if (!path) return;
  try {
    const data = await loadTaskFilePreview(path);
    const blob = new Blob([data.content || ""], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = data.name || "task-result.txt";
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    window.alert(error.message || "下载文件失败");
  }
}

function jobDiagnosticsHtml(job) {
  const diagnostics = job.diagnostics || {};
  const issues = Array.isArray(diagnostics.issues) ? diagnostics.issues : [];
  const waitingCount = Number(diagnostics.waiting_for_panels || job.result?.waiting_for_panels || 0);
  if (!issues.length && !waitingCount) return "";
  const title = diagnostics.title || (diagnostics.domain === "text_model" ? "小说处理诊断" : "生成诊断");
  const subtitle = diagnostics.waiting_reason ? `原因：${diagnosticTypeLabel(diagnostics.waiting_reason)}` : "按建议动作处理";
  const issueRows = issues.slice(0, 4).map((issue) => `
    <li class="diagnostic-${escapeHtml(issue.severity || "retryable")}">
      <div>
        <strong>${escapeHtml(issue.panel_id ? fullPanelDisplayName(issue.panel_id) : diagnosticTypeLabel(issue.type))}</strong>
        <em>${escapeHtml(diagnosticSeverityLabel(issue.severity))}</em>
      </div>
      <span>${escapeHtml(stripInternalIdsFromText(issue.message || issue.raw || ""))}</span>
      ${issue.action ? `<small>建议：${escapeHtml(stripInternalIdsFromText(issue.action))}</small>` : ""}
      <footer>
        <b>${escapeHtml(issue.retry_hint || "查看日志后处理")}</b>
        ${Number(issue.cooldown_seconds || 0) ? `<b>冷却 ${Number(issue.cooldown_seconds)} 秒</b>` : ""}
      </footer>
    </li>
  `).join("");
  return `
    <div class="job-diagnostics">
      <header>
        <strong>${escapeHtml(waitingCount ? `待补分镜 ${waitingCount} 个` : title)}</strong>
        <span>${escapeHtml(waitingCount ? (diagnostics.waiting_reason ? `原因：${diagnosticTypeLabel(diagnostics.waiting_reason)}` : "按建议动作处理") : subtitle)}</span>
      </header>
      <ul>${issueRows || `<li class="diagnostic-retryable"><span>仍有分镜没有生成，请继续补生成。</span></li>`}</ul>
    </div>
  `;
}

function diagnosticTypeLabel(value) {
  return {
    empty_image_response: "接口无图",
    rate_limited: "接口限流",
    auth_failed: "鉴权失败",
    model_unavailable: "模型不可用",
    workflow_missing: "工作流缺失",
    panel_failed: "分镜失败",
    timeout: "等待超时",
    backend_unreachable: "后端不可达",
    waiting_for_panels: "待补分镜",
    text_model_rate_limited: "小说模型限流",
    text_model_unavailable: "小说模型不可用",
    text_model_auth_failed: "小说模型鉴权失败",
    text_model_timeout: "小说模型超时",
    text_model_error: "小说处理失败",
    unknown: "生成诊断",
  }[value] || "生成诊断";
}

function diagnosticSeverityLabel(value) {
  return {
    blocked: "需先修复",
    cooldown: "等待冷却",
    retryable: "可重试",
    info: "提示",
  }[value] || "可重试";
}

async function runStage(stage) {
  const maxPages = getInt("maxPages", 2);
  const payload = {
    stage,
    episode_number: state.selectedEpisode,
    pages: getInt("pages", 8),
    max_panels: getInt("maxPanels", 1),
    max_pages: stage === "close_reading" ? maxPages : maxPages,
    dry_run: $("dryRun").checked,
    force: $("forceRun").checked,
    allow_draft_warnings: $("allowWarnings").checked,
  };
  setButtons(true);
  try {
    const result = await api("/api/run", { method: "POST", body: JSON.stringify(payload) });
    state.selectedTaskJobId = result.id || result.job_id || "";
    if ($("statusLine")) {
      $("statusLine").textContent = `${stageLabel(stage)} 已启动，正在刷新任务和章节结果。`;
    }
    await loadJobs();
    if (stage === "breakdown" || stage === "close_reading") {
      await loadEpisode(state.selectedEpisode, { skipAgent: true });
      switchTab("breakdown");
    } else if (stage === "generate") {
      await loadEpisode(state.selectedEpisode, { skipAgent: true });
      switchTab("media");
    } else if (stage === "status" || stage === "review" || stage === "draft_review") {
      await loadEpisode(state.selectedEpisode, { skipAgent: true });
    }
    if (["breakdown", "close_reading", "generate"].includes(stage)) {
      switchTab("jobs");
    }
    await loadAgent();
  } catch (error) {
    window.alert(error.message || "任务启动失败");
  } finally {
    setButtons(false);
    updateStageActions();
  }
}

async function runCloseReading() {
  const stats = closeReadingStats(state.detail?.pages || []);
  const batchSize = Math.max(1, getInt("maxPages", 2));
  const willUpdate = Math.min(stats.safe, batchSize);
  const ok = window.confirm(`细读拆解本次会更新 ${willUpdate}/${stats.safe} 个待细读页面，并保护 ${stats.protected} 个已有输出页面。完成后需要重新审核拆解；如仍有剩余页面，可继续点击下一轮。继续吗？`);
  if (!ok) return;
  await runStage("close_reading");
}

async function retryCloseReading(episodeNumber) {
  if (episodeNumber && Number(episodeNumber) !== Number(state.selectedEpisode)) {
    state.selectedEpisode = Number(episodeNumber);
    await loadEpisodeDetail();
  }
  await runCloseReading();
  switchTab("jobs");
}

async function regeneratePanel(pageId, panelId) {
  const panel = (state.detail?.media?.panels || []).find((item) => item.panel_id === panelId);
  const missing = panel && !panel.exists;
  const action = missing ? "补生成" : "重新生成";
  const detail = missing ? "当前分镜没有真实输出，完成后会自动尝试重新组装页面。" : "旧图会先备份，完成后自动尝试重新组装页面。";
  const ok = window.confirm(`${action}${fullPanelDisplayName(panelId, pageId)}？${detail}`);
  if (!ok) return;
  setButtons(true);
  try {
    await api("/api/regenerate", {
      method: "POST",
      body: JSON.stringify({
        episode_number: state.selectedEpisode,
        page_id: pageId,
        panel_id: panelId,
      }),
    });
    await loadJobs();
    switchTab("jobs");
  } finally {
    setButtons(false);
  }
}

async function regeneratePage(pageId) {
  const blockers = mediaReviewBlockers(pageId);
  if (blockers.count) {
    window.alert(mediaReviewBlockerMessage(blockers));
    switchTab("media");
    state.mediaFilter = "pages";
    renderMedia();
    return;
  }
  const panels = (state.detail?.media?.panels || []).filter((item) => item.page_id === pageId);
  const missing = panels.filter((item) => !item.exists);
  const ok = window.confirm(`补齐${pageDisplayName(pageId)}？将依次生成 ${missing.length} 个缺失分镜，完成后自动合成页面并同步入库。`);
  if (!ok) return;
  setButtons(true);
  try {
    await api("/api/regenerate-page", {
      method: "POST",
      body: JSON.stringify({
        episode_number: state.selectedEpisode,
        page_id: pageId,
      }),
    });
    await loadJobs();
    switchTab("jobs");
  } finally {
    setButtons(false);
  }
}

async function retryGenerate(episodeNumber) {
  const ok = window.confirm(`继续尝试第 ${episodeNumber} 章缺失分镜生成？`);
  if (!ok) return;
  setButtons(true);
  try {
    await api("/api/run", {
      method: "POST",
      body: JSON.stringify({
        stage: "generate",
        episode_number: episodeNumber,
        pages: getInt("pages", 8),
        max_panels: getInt("maxPanels", 1),
        max_pages: getInt("maxPages", 1),
        dry_run: false,
        force: false,
        allow_draft_warnings: true,
      }),
    });
    await loadJobs();
    switchTab("jobs");
  } catch (error) {
    window.alert(error.message || "重试生成失败");
  } finally {
    setButtons(false);
  }
}

async function cancelJob(jobId) {
  if (!jobId) return;
  const ok = window.confirm("确认取消当前正在运行的任务？已完成的输出不会自动删除。");
  if (!ok) return;
  try {
    await api(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST", body: JSON.stringify({}) });
    state.taskFilePreview = null;
    await loadJobs();
  } catch (error) {
    window.alert(error.message || "取消任务失败");
  }
}

async function retryJob(jobId) {
  if (!jobId) return;
  const ok = window.confirm("使用原任务参数重新启动？新任务会单独记录，原任务历史不会被覆盖。");
  if (!ok) return;
  try {
    const result = await api(`/api/jobs/${encodeURIComponent(jobId)}/retry`, { method: "POST", body: JSON.stringify({}) });
    state.selectedTaskJobId = result.id || result.job_id || "";
    state.taskFilePreview = null;
    await loadJobs();
  } catch (error) {
    window.alert(error.message || "重试任务失败");
  }
}

async function regenerateAsset(asset) {
  const ok = window.confirm(`重新生成素材 ${asset.alias}？旧素材会先备份，新图会输出到同一资产路径。`);
  if (!ok) return;
  setButtons(true);
  try {
    await api("/api/regenerate", {
      method: "POST",
      body: JSON.stringify({
        episode_number: state.selectedEpisode,
        asset_id: asset.id || 0,
        asset_alias: asset.alias,
        asset_path: asset.path,
        asset_category: asset.category,
      }),
    });
    await loadJobs();
    switchModule("workflow");
    switchTab("jobs");
  } finally {
    setButtons(false);
  }
}

async function switchModule(module) {
  state.activeModule = module;
  document.querySelectorAll("[data-module]").forEach((button) => {
    button.classList.toggle("active", button.dataset.module === module);
  });
  document.querySelectorAll("[data-module-view]").forEach((view) => {
    view.classList.toggle("active", view.dataset.moduleView === module);
  });
  if (module === "home") renderHome();
  if (module === "workflow") {
    const targetEpisode = mainEpisodeFromDashboard();
    if ((!state.detail || Number(state.selectedEpisode) !== targetEpisode) && targetEpisode) {
      await loadEpisode(targetEpisode);
    }
    renderReader();
    if (!state.activeTab) switchTab("source");
    document.querySelector(".main-pane")?.scrollTo({ top: 0, left: 0 });
  }
  if (module === "settingsLibrary") loadSettingsLibrary().catch((error) => window.alert(error.message || "设定库加载失败"));
  if (module === "reviewCenter") loadReviewCenter().catch((error) => window.alert(error.message || "审核中心加载失败"));
  if (module === "taskCenter") renderTaskCenter();
  if (module === "assets") {
    const targetEpisode = mainEpisodeFromDashboard() || state.selectedEpisode || 4;
    const box = $("assetView");
    if (box) box.innerHTML = `<div class="empty">正在读取作品级素材库...</div>`;
    if (!state.detail || Number(state.selectedEpisode) !== Number(targetEpisode) || !state.detail.assets) {
      try {
        await loadAssets(targetEpisode);
      } catch (error) {
        if (box) box.innerHTML = `<div class="empty">素材库加载失败：${escapeHtml(error.message || "请检查控制台服务")}</div>`;
      }
    } else {
      renderAssets();
    }
  }
  if (module === "settings") updateSettingsBadges();
}

function settingsSourceRows() {
  const configPath = state.config?.config_path || "config/.env";
  const textPath = state.config?.text_env_path || "config/text.env";
  const imagePath = state.config?.image_env_path || "config/image.env";
  const database = state.config?.database || state.health?.database || {};
  const activeProject = state.projects?.find?.((item) => item.slug === state.activeProject) || {};
  return [
    {
      title: "控制台运行配置",
      path: configPath,
      detail: "ComfyUI 地址、目录、小说路径、数据库地址、默认页数、当前小说项目。",
      state: state.config ? "已读取" : "未读取",
      ok: Boolean(state.config),
    },
    {
      title: "小说处理密钥",
      path: textPath,
      detail: "小说处理 API Key 和文本模型接口地址。用于导入增强、细读拆解和设定扫描。",
      state: state.config?.text?.OPENAI_API_KEY_CONFIGURED ? "已配置" : "未配置",
      ok: Boolean(state.config?.text?.OPENAI_API_KEY_CONFIGURED),
    },
    {
      title: "图片生成密钥",
      path: imagePath,
      detail: "图片生成 API Key 和图片模型接口地址。用于 ComfyUI 图片生成节点。",
      state: state.config?.image?.OPENAI_API_KEY_CONFIGURED ? "已配置" : "未配置",
      ok: Boolean(state.config?.image?.OPENAI_API_KEY_CONFIGURED),
    },
    {
      title: "PostgreSQL 数据",
      path: $("databaseUrl")?.value || state.config?.config?.COMIC_PIPELINE_DATABASE_URL || "-",
      detail: "作品、章节、拆解、设定、素材、生成结果、审核记录、任务状态。",
      state: database.schema_ready ? "已连接" : "未连接",
      ok: Boolean(database.schema_ready),
    },
    {
      title: "当前小说项目",
      path: activeProject.title || state.activeProject || "-",
      detail: "小说内容、章节工作台、设定库、素材库和审核任务均按小说项目隔离。",
      state: state.activeProject ? "已选择" : "未选择",
      ok: Boolean(state.activeProject),
    },
  ];
}

function renderSettingsSources() {
  const box = $("settingsSourceList");
  if (!box) return;
  box.innerHTML = settingsSourceRows().map((item, index) => `
    <article class="settings-source-item">
      <span class="settings-source-index">${String(index + 1).padStart(2, "0")}</span>
      <div>
        <header>
          <strong>${escapeHtml(item.title)}</strong>
          <em class="${item.ok ? "ok" : "bad"}">${escapeHtml(item.state)}</em>
        </header>
        <p>${escapeHtml(item.detail)}</p>
        <code>${escapeHtml(item.path)}</code>
      </div>
    </article>
  `).join("");
}

function settingsCheckAction(name) {
  return {
    postgres: "检查 PostgreSQL 服务、账号密码和端口。",
    comfyui: "确认 8188 服务已启动，或使用“启动后端”。",
    text_api_key: "在小说处理配置中填写有效 API Key 后保存。",
    image_api_key: "在图片生成配置中填写有效 API Key 后保存。",
    output_root: "确认输出目录存在，并且当前用户有写入权限。",
    novel_model: "在小说处理模型中填写可用模型名称。",
    image_model: "在图片生成模型中填写可用模型名称。",
    pipeline_example: "同步 config/.env.example，让示例配置包含全部 UI 设置项且没有过期项。",
    text_example: "同步 config/text.env.example，让示例配置包含 OPENAI_API_KEY 和 OPENAI_BASE_URL。",
    image_example: "同步 config/image.env.example，让示例配置包含 OPENAI_API_KEY 和 OPENAI_BASE_URL。",
  }[name] || "检查对应配置项后重新测试。";
}

function renderSettingsHealth() {
  const badge = $("settingsHealthBadge");
  const box = $("settingsHealthList");
  if (!box) return;
  const data = state.settingsHealth;
  if (!data) {
    if (badge) {
      badge.textContent = "未测试";
      badge.className = "mini-badge";
    }
    box.innerHTML = `<div class="settings-empty">点击“连接测试”检查 PostgreSQL、ComfyUI、API Key、输出目录、模型配置和示例配置一致性。</div>`;
    return;
  }
  const checks = Array.isArray(data.checks) ? data.checks : [];
  const passed = checks.filter((item) => item.ok).length;
  if (badge) {
    badge.textContent = data.ok ? "全部通过" : `${passed}/${checks.length} 通过`;
    badge.className = `mini-badge ${data.ok ? "agent-state-complete" : "agent-state-blocked"}`;
  }
  box.innerHTML = checks.map((item) => `
    <article class="settings-health-item ${item.ok ? "ok" : "bad"}">
      <span class="status-dot"></span>
      <div>
        <header>
          <strong>${escapeHtml(item.label || item.name || "检查项")}</strong>
          <em>${item.ok ? "通过" : "需处理"}</em>
        </header>
        <p>${escapeHtml(item.message || "-")}</p>
        ${item.source ? `<small>来源：${escapeHtml(sourceLabel(item.source))}</small>` : ""}
        ${item.ok ? "" : `<small>${escapeHtml(settingsCheckAction(item.name))}</small>`}
      </div>
    </article>
  `).join("") || `<div class="settings-empty">没有返回检查项。</div>`;
}

function updateSettingsBadges() {
  renderSettingsSources();
  renderSettingsHealth();
  renderEffectiveProjectConfig();
  const backendBadge = $("settingsBackendBadge");
  if (backendBadge) {
    const ready = Boolean(state.health?.checks?.root?.ok);
    backendBadge.textContent = ready ? "可访问" : "不可访问";
    backendBadge.className = `mini-badge ${ready ? "agent-state-complete" : "agent-state-blocked"}`;
  }
  const textKeyBadge = $("settingsTextKeyBadge");
  if (textKeyBadge) {
    const configured = Boolean(state.config?.text?.OPENAI_API_KEY_CONFIGURED || state.health?.text_api_key_configured);
    textKeyBadge.textContent = configured ? "已配置" : "未配置";
    textKeyBadge.className = `mini-badge ${configured ? "agent-state-complete" : "agent-state-blocked"}`;
  }
  const imageKeyBadge = $("settingsImageKeyBadge");
  if (imageKeyBadge) {
    const configured = Boolean(state.config?.image?.OPENAI_API_KEY_CONFIGURED || state.health?.image_api_key_configured);
    imageKeyBadge.textContent = configured ? "已配置" : "未配置";
    imageKeyBadge.className = `mini-badge ${configured ? "agent-state-complete" : "agent-state-blocked"}`;
  }
  const dbBadge = $("settingsDatabaseBadge");
  if (dbBadge) {
    const ready = Boolean(state.config?.database?.schema_ready || state.health?.database?.schema_ready);
    dbBadge.textContent = ready ? "已连接" : "未连接";
    dbBadge.className = `mini-badge ${ready ? "agent-state-complete" : "agent-state-blocked"}`;
  }
  const dbDetail = $("databaseDetail");
  if (dbDetail) {
    const database = state.config?.database || state.health?.database || {};
    dbDetail.textContent = database.schema_ready
      ? "PostgreSQL 已连接，作品、章节、审核状态和任务索引会写入数据库。"
      : (database.error || "PostgreSQL 未就绪。");
  }
  const textApiKeyDetail = $("textApiKeyDetail");
  if (textApiKeyDetail) {
    const configured = Boolean(state.config?.text?.OPENAI_API_KEY_CONFIGURED || state.health?.text_api_key_configured);
    textApiKeyDetail.textContent = configured
      ? "小说处理密钥已配置。留空保存不会覆盖现有密钥。"
      : "小说处理密钥未配置。填写后保存到 text.env，页面不会回显明文。";
  }
  const imageApiKeyDetail = $("imageApiKeyDetail");
  if (imageApiKeyDetail) {
    const configured = Boolean(state.config?.image?.OPENAI_API_KEY_CONFIGURED || state.health?.image_api_key_configured);
    imageApiKeyDetail.textContent = configured
      ? "图片生成密钥已配置。留空保存不会覆盖现有密钥。"
      : "图片生成密钥未配置。填写后保存到 image.env，页面不会回显明文。";
  }
  renderGenerationBackendDiagnostics();
}

function sourceLabel(value) {
  return value === "project" ? "当前小说项目" : "全局设置";
}

function renderEffectiveProjectConfig() {
  const box = $("effectiveProjectConfig");
  if (!box) return;
  const summary = state.settingsSummary || {};
  const models = summary.models || {};
  const paths = summary.paths || {};
  const project = summary.project || {};
  const modelSources = models.sources || {};
  const pathSources = paths.sources || {};
  const rows = [
    ["小说处理模型", models.novel_model || "-", sourceLabel(modelSources.novel_model)],
    ["图片生成模型", models.image_model || "-", sourceLabel(modelSources.image_model)],
    ["输出目录", paths.output_root || "-", sourceLabel(pathSources.output_root)],
  ];
  box.innerHTML = `
    <div class="effective-config-head">
      <strong>当前生效配置</strong>
      <span>${escapeHtml(project.title || project.slug || "当前小说")}</span>
    </div>
    ${rows.map(([label, value, source]) => `
      <div class="effective-config-row">
        <span>${escapeHtml(label)}</span>
        <code>${escapeHtml(value)}</code>
        <em>${escapeHtml(source)}</em>
      </div>
    `).join("")}
  `;
}

function renderGenerationBackendDiagnostics(data = state.generationBackend) {
  const box = $("backendDiagnostics");
  if (!box) return;
  const source = data?.diagnostics || data;
  if (!source) {
    const rootOk = Boolean(state.health?.paths?.comfy_root?.exists);
    const rootState = rootOk ? "ComfyUI 根目录存在" : "ComfyUI 根目录未确认";
    box.textContent = `${rootState}。点击“检查后端”获取端口、启动入口、模型目录和日志状态。`;
    return;
  }
  const paths = source.paths || {};
  const logs = source.logs || {};
  const stderrTail = source.ok
    ? "后端已运行，健康检查通过。"
    : (logs.stderr?.tail || "").trim().split(/\r?\n/).slice(-4).join(" / ");
  const modelSummary = ["checkpoints", "loras", "vae", "clip", "controlnet"]
    .map((key) => `${key}:${Number(paths[key]?.files || 0)}`)
    .join(" · ");
  box.innerHTML = `
    <dl>
      <div><dt>状态</dt><dd>${source.ok ? "健康检查通过" : "不可访问或检查未通过"}</dd></div>
      <div><dt>地址</dt><dd>${escapeHtml(source.comfy_url || "-")} / 端口 ${source.port_open ? "已打开" : "未打开"}</dd></div>
      <div><dt>入口</dt><dd>${paths.main_py?.exists ? "main.py 存在" : "main.py 缺失"} · ${paths.python?.exists ? "Python 可用" : "Python 不可用"}</dd></div>
      <div><dt>模型</dt><dd>${escapeHtml(modelSummary)}</dd></div>
      <div><dt>日志</dt><dd>${escapeHtml(stderrTail || "暂无错误日志")}</dd></div>
    </dl>
  `;
}

function switchTab(tab) {
  state.activeTab = tab;
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === tab);
  });
  document.querySelectorAll(".tab-view").forEach((view) => {
    view.classList.toggle("active", view.id === `tab-${tab}`);
  });
}

function setButtons(disabled) {
  const selectors = [
    "[data-stage]",
    "[data-regenerate]",
    "[data-regenerate-page]",
    "[data-output-review]",
    "[data-output-batch]",
    "[data-asset-regenerate]",
    "#agentPrimaryButton",
    "#agentRefreshButton",
    "#assetSyncButton",
    "#outputSyncButton",
    "#checkBackendButton",
    "#startBackendButton",
    "#saveConfigButton",
    "#testTextModelButton",
    "#testImageModelButton",
    "#importWizardButton",
    "#importOpenSettingsButton",
    "#processNovelButton",
    "#novelFile",
    "#settingScanButton",
    "#settingScanExtractionMode",
    "#settingRefreshButton",
    "#settingRefreshPromptButton",
    "#settingSaveButton",
    "#settingApproveButton",
    "#settingNeedsWorkButton",
    "#settingLockButton",
    "#breakdownSaveNoteButton",
    "#breakdownApproveButton",
    "#breakdownNeedsWorkButton",
  ];
  document.querySelectorAll(selectors.join(",")).forEach((button) => {
    button.disabled = disabled;
  });
  if (!disabled) updateStageActions();
}

function updateStageActions() {
  const approvals = state.agent?.approvals || {};
  const metrics = state.agent?.metrics || {};
  const hasDraft = Boolean(metrics.draft_exists);
  const globalReady = Boolean(metrics.global_assets_ready_for_close_reading);
  const globalBlocker = metrics.global_assets_blocker || "需要先完成全局设定和全局素材确认";
  const generationComplete =
    Number(metrics.real_pages_ready ?? metrics.pages_ready ?? 0) >= Math.max(Number(metrics.pages_total || 0), 1) &&
    Number(metrics.panels_ready || 0) >= Math.max(Number(metrics.panels_total || 0), 1);
  const qaReady = Boolean(metrics.qa_exists);
  const rules = {
    preflight: { disabled: false, title: "检查配置、路径和生成后端状态" },
    breakdown: {
      disabled: !globalReady,
      title: globalReady ? "生成章节页面计划和初始分镜骨架" : globalBlocker,
    },
    close_reading: {
      disabled: !hasDraft || !globalReady,
      title: !globalReady
        ? globalBlocker
        : !hasDraft
          ? "需要先生成章节页面计划"
          : "按任务队列细读当前章节的未生成页面",
    },
    draft_review: { disabled: !hasDraft, title: hasDraft ? "重新生成拆解审稿包" : "需要先完成章节骨架" },
    generate: {
      disabled: !hasDraft || !approvals.draft || !approvals.assets,
      title: !hasDraft
        ? "需要先完成章节细读和拆解审核"
        : !approvals.draft || !approvals.assets
          ? "需要先通过章节拆解审核和全局素材确认"
          : "小批量生成当前章节漫画",
    },
    review: {
      disabled: !generationComplete || !approvals.generation,
      title: !generationComplete
        ? "需要先生成完整页面和分镜"
        : !approvals.generation
          ? "需要先通过生成审核"
          : "生成页面组装与质检报告",
    },
    status: { disabled: false, title: qaReady ? "刷新状态报告" : "生成或刷新状态报告" },
  };
  document.querySelectorAll("[data-stage]").forEach((button) => {
    const rule = rules[button.dataset.stage] || { disabled: false, title: "" };
    button.disabled = Boolean(rule.disabled);
    button.title = rule.title;
    button.classList.toggle("locked", Boolean(rule.disabled));
  });
}

function stateLabel(value) {
  return {
    generated: "已生成",
    generated_v001: "已生成",
    draft_ready: "有拆解",
    not_started: "未开始",
    needs_close_reading: "待细读拆解",
    skeleton_needs_close_reading: "待细读拆解",
    close_reading_refined_needs_review: "细读完成，待审核",
    brief_applied_needs_panel_close_reading: "待细化分镜",
    planned_from_beats: "已规划",
    ready: "已就绪",
    pending: "待处理",
    review: "待审核",
    done: "已完成",
    blocked: "阻塞",
  }[value] || value || "未知";
}

function stageLabel(value) {
  return {
    preflight: "预检",
    breakdown: "AI 拆解",
    draft_review: "拆解审稿",
    generate: "生成漫画",
    review: "生成审核",
    status: "状态刷新",
    asset: "素材",
    process_novel: "处理小说",
    regenerate: "重生成",
    regenerate_page: "按页补生成",
    close_reading: "细读拆解",
  }[value] || stripInternalIdsFromText(value || "");
}

function statusText(value) {
  return {
    running: "运行中",
    queued: "排队中",
    starting: "启动中",
    waiting: "等待重试",
    partial: "部分完成",
    passed: "已通过",
    failed: "失败",
    cancelled: "已取消",
    interrupted: "已中断",
  }[value] || value || "-";
}

function agentStateText(value) {
  return {
    blocked: "阻塞",
    ready: "可执行",
    review: "待审核",
    complete: "可循环",
  }[value] || "检查中";
}

function approvalGateLabel(value) {
  return {
    draft: "拆解审核",
    assets: "素材确认",
    generation: "生成审核",
    qa: "质检审核",
    next_episode: "下一章确认",
  }[value] || value || "审核";
}

function compactTime(value) {
  const text = String(value || "");
  const match = text.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/);
  return match ? `${match[2]}-${match[3]} ${match[4]}:${match[5]}` : text || "-";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

document.addEventListener("DOMContentLoaded", () => {
  $("refreshButton").addEventListener("click", loadAll);
  $("homeImportButton").addEventListener("click", () => switchModule("importNovel"));
  $("importWizardButton").addEventListener("click", () => switchModule("importNovel"));
  $("importOpenSettingsButton").addEventListener("click", () => switchModule("settings"));
  $("homeSettingsButton").addEventListener("click", () => switchModule("settings"));
  $("reviewCenterRefreshButton").addEventListener("click", loadReviewCenter);
  $("taskCenterRefreshButton").addEventListener("click", loadJobs);
  $("taskCenterFilter").addEventListener("change", (event) => {
    state.taskCenterFilter = event.target.value;
    renderTaskCenter();
  });
  $("reviewCenterFilter").addEventListener("change", (event) => {
    state.reviewCenterFilter = event.target.value;
    renderReviewCenter();
  });
  $("reviewTimelineFilter").addEventListener("change", (event) => {
    state.reviewTimelineFilter = event.target.value;
    state.selectedReviewTimelineId = "";
    loadReviewCenter().catch((error) => window.alert(error.message || "审核时间线加载失败"));
  });
  $("reviewTimelineRange").addEventListener("change", (event) => {
    state.reviewTimelineRange = event.target.value;
    state.selectedReviewTimelineId = "";
    loadReviewCenter().catch((error) => window.alert(error.message || "审核时间线加载失败"));
  });
  $("reviewTimelineLimit").addEventListener("change", (event) => {
    state.reviewTimelineLimit = event.target.value;
    state.selectedReviewTimelineId = "";
    loadReviewCenter().catch((error) => window.alert(error.message || "审核时间线加载失败"));
  });
  $("readerSourceTabButton").addEventListener("click", () => switchTab("source"));
  $("readerBreakdownTabButton").addEventListener("click", () => switchTab("breakdown"));
  $("closeReadingButton").addEventListener("click", runCloseReading);
  document.addEventListener("click", (event) => {
    const stageButton = event.target.closest("[data-stage]");
    if (stageButton && !stageButton.disabled) {
      event.preventDefault();
      if (stageButton.dataset.stage === "close_reading") {
        runCloseReading();
      } else {
        runStage(stageButton.dataset.stage);
      }
      return;
    }
    const taskButton = event.target.closest("[data-open-task-center]");
    if (taskButton) {
      event.preventDefault();
      switchModule("taskCenter");
    }
  });
  $("breakdownSaveNoteButton").addEventListener("click", saveBreakdownNote);
  $("breakdownApproveButton").addEventListener("click", () => reviewBreakdown("approve"));
  $("breakdownNeedsWorkButton").addEventListener("click", () => reviewBreakdown("needs_work"));
  $("agentFocusButton").addEventListener("click", () => {
    document.querySelector(".inspector")?.classList.add("assistant-expanded");
    $("agentPanel").classList.remove("is-secondary-hidden");
    $("agentPanel").open = true;
    $("agentPanel").scrollIntoView({ block: "nearest", behavior: "smooth" });
  });
  $("agentRefreshButton").addEventListener("click", loadAgent);
  $("agentPrimaryButton").addEventListener("click", runAgentPrimary);
  $("agentCompactButton").addEventListener("click", runAgentPrimary);
  $("saveConfigButton").addEventListener("click", saveConfig);
  $("checkSettingsButton").addEventListener("click", checkSettingsHealth);
  $("testTextModelButton").addEventListener("click", () => testModel("text"));
  $("testImageModelButton").addEventListener("click", () => testModel("image"));
  $("checkBackendButton").addEventListener("click", checkGenerationBackend);
  $("startBackendButton").addEventListener("click", startGenerationBackend);
  $("projectSelect").addEventListener("change", () => switchProject($("projectSelect").value));
  $("processNovelButton").addEventListener("click", processNovel);
  $("previewNovelButton").addEventListener("click", previewNovelImport);
  $("novelFile").addEventListener("change", (event) => uploadNovelFile(event.target.files?.[0]));
  ["projectTitle", "projectSlug", "novelPath", "defaultPages", "encoding"].forEach((id) => {
    $(id)?.addEventListener("input", () => {
      state.importPreview = null;
      renderImportPreview();
      renderChapterImportPreview();
    });
  });
  $("episodeSearch").addEventListener("input", renderEpisodes);
  $("episodeFilter").addEventListener("change", renderEpisodes);
  $("assetSearch").addEventListener("input", renderAssets);
  $("assetUsageFilter").addEventListener("change", () => {
    state.assetUsageFilter = $("assetUsageFilter").value;
    renderAssets();
  });
  $("assetRefreshButton").addEventListener("click", () => loadEpisode(state.selectedEpisode));
  $("assetSyncButton").addEventListener("click", syncAssetsToDatabase);
  $("outputSyncButton").addEventListener("click", syncOutputsToDatabase);
  document.querySelectorAll("[data-output-batch]").forEach((button) => {
    button.addEventListener("click", () => reviewVisibleOutputs(button.dataset.outputBatch));
  });
  $("settingScanButton").addEventListener("click", scanSettingsLibrary);
  $("settingRefreshButton").addEventListener("click", loadSettingsLibrary);
  $("settingSearch").addEventListener("input", renderSettingsLibrary);
  $("settingTypeFilter").addEventListener("change", renderSettingsLibrary);
  $("settingStatusFilter").addEventListener("change", renderSettingsLibrary);
  $("settingSuggestButton").addEventListener("click", suggestSettingFromInstruction);
  $("settingSuggestClearButton").addEventListener("click", () => {
    setValue("settingSuggestInstruction", "");
    renderSettingSuggestions([]);
  });
  $("settingNewButton").addEventListener("click", () => fillSettingEditor(null));
  $("settingRefreshPromptButton").addEventListener("click", refreshSelectedSettingPrompt);
  $("settingApplyRefreshButton").addEventListener("click", applySettingPromptRefresh);
  $("settingSaveButton").addEventListener("click", saveSetting);
  $("settingApproveButton").addEventListener("click", () => reviewSetting("approve"));
  $("settingNeedsWorkButton").addEventListener("click", () => reviewSetting("needs_work"));
  $("settingLockButton").addEventListener("click", toggleSettingLock);
  document.querySelectorAll("[data-module]").forEach((button) => {
    button.addEventListener("click", () => switchModule(button.dataset.module));
  });
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => switchTab(button.dataset.tab));
  });
  document.querySelectorAll("[data-qa-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      state.qaTab = button.dataset.qaTab;
      document.querySelectorAll("[data-qa-tab]").forEach((item) => item.classList.toggle("active", item === button));
      renderQaText();
    });
  });
  document.querySelectorAll("[data-media-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      state.mediaFilter = button.dataset.mediaFilter;
      document.querySelectorAll("[data-media-filter]").forEach((item) => item.classList.toggle("active", item === button));
      renderMedia();
    });
  });
  loadAll().catch((error) => {
    $("statusLine").textContent = error.message;
  });
  scheduleJobPoll(7000);
  document.addEventListener("visibilitychange", () => {
    scheduleJobPoll(document.hidden ? 60000 : 0);
  });
});
