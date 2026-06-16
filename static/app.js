const state = { candidates: [], products: [], shops: [], batches: [], runs: [], publishResults: { overview: {}, failures: [], waiting: [], recent: [] }, imageJobs: [], imageSummary: { overview: {}, items: [] }, collectionQueue: { queues: [], items: [] }, batchPreview: null, workflow: [], settings: {}, browserStatus: {}, platformStatus: {}, currentCandidate: null, candidateQueue: "need_data", collectionQueueStatus: "pending", imageQueue: "all", currentAssetProductId: null, currentCollectionTask: null, localStatus: {}, workbenchToken: "" };
const markets = { MY: "马来西亚", PH: "菲律宾", SG: "新加坡", TH: "泰国", VN: "越南" };
const workflowTargets = {
  import_candidates: "candidates",
  complete_product_data: "candidates",
  five_market_scoring: "candidates",
  collect_qualified: "candidates",
  generate_images: "products",
  review_images: "products",
  create_batches: "publish",
  dry_run_check: "publish",
  live_confirm: "publish",
  publish_results: "publish",
};
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const toast = $("#toast");

function notify(message, type = "success") {
  toast.textContent = message;
  toast.className = `toast show ${type === "error" ? "error" : ""}`;
  clearTimeout(notify.timer);
  notify.timer = setTimeout(() => { toast.className = "toast"; }, 3400);
}

async function api(url, options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (method !== "GET" && state.workbenchToken) headers["X-Workbench-Token"] = state.workbenchToken;
  const response = await fetch(url, { headers, ...options });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || `请求失败（${response.status}）`);
    Object.assign(error, data);
    throw error;
  }
  return data;
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char]));
}

function scoreClass(score) {
  if (score >= 70) return "score-good";
  if (score >= 55) return "score-mid";
  return "score-low";
}

function getEvaluation(candidate, market) {
  return (candidate.evaluations || []).find((item) => item.market === market);
}

function marketChip(candidate, market) {
  const summary = candidate.marketSummary?.markets?.[market];
  if (!summary || summary.status === "missing") {
    return `<div class="market-score-card score-review"><strong>${market}</strong><span>需人工复核</span><small>未评分 · ${esc(summary?.reason || "缺少目标售价和市场样本")}</small></div>`;
  }
  const labelMap = {
    collectable: "可采集",
    review: "需人工复核",
    rejected: "不建议采集",
  };
  const classMap = {
    collectable: "score-collectable",
    review: "score-review",
    rejected: "score-rejected",
  };
  return `<div class="market-score-card ${classMap[summary.decision] || "score-review"}" title="${esc(summary.reason || "")}">
    <strong>${Number(summary.score || 0).toFixed(0)}</strong>
    <span>${labelMap[summary.decision] || summary.decisionLabel || "需人工复核"}</span>
    <small>置信 ${Number(summary.confidence || 0).toFixed(0)}% · 毛利 ${summary.marginPct === null || summary.marginPct === undefined ? "--" : `${Number(summary.marginPct).toFixed(1)}%`}</small>
    <small>${summary.hasHardBlock ? "Hard block" : "无 hard block"}</small>
    <em>${esc(summary.reason || "暂无原因")}</em>
    <b>${esc(summary.suggestedAction || "人工复核")}</b>
  </div>`;
}

function renderMissingHints(item) {
  const hints = item.missingHints || [];
  if (!hints.length) return '<span class="candidate-ready">基础数据已齐</span>';
  const visible = hints.slice(0, 3).map((hint) => `<span>${esc(hint.message || hint.label)}</span>`).join("");
  const more = hints.length > 3 ? `<small>另 ${hints.length - 3} 项</small>` : "";
  const detail = hints.map((hint) => `${hint.message || hint.label}：${hint.hint}`).join("；");
  return `<div class="missing-hints" title="${esc(detail)}">${visible}${more}</div>`;
}

function renderCompleteness(item) {
  const completeness = item.dataCompleteness || { completed: 0, required: 9, percent: 0 };
  const percent = Math.max(0, Math.min(100, Number(completeness.percent || 0)));
  return `<div class="data-completeness">
    <span>${Number(completeness.completed || 0)}/${Number(completeness.required || 0)} 项</span>
    <strong>${percent}%</strong>
    <i><b style="width:${percent}%"></b></i>
  </div>`;
}

function candidateQueueCounts() {
  return {
    all: state.candidates.length,
    need_data: state.candidates.filter((item) => item.queue === "need_data").length,
    ready_to_score: state.candidates.filter((item) => item.queue === "ready_to_score").length,
  };
}

function filteredCandidates() {
  if (state.candidateQueue === "all") return state.candidates;
  return state.candidates.filter((item) => item.queue === state.candidateQueue);
}

function renderCandidateQueues() {
  const counts = candidateQueueCounts();
  $("#queue-need-data").textContent = counts.need_data;
  $("#queue-ready-score").textContent = counts.ready_to_score;
  $("#queue-all").textContent = counts.all;
  $$(".candidate-queue-tab").forEach((button) => button.classList.toggle("active", button.dataset.candidateQueue === state.candidateQueue));
}

function renderFieldStatus(item) {
  const completeness = item.dataCompleteness || {};
  const missing = new Set(completeness.missingFields || []);
  const fields = [
    ["source_url", "链接", Boolean(item.source_url)],
    ["title", "标题", Boolean(String(item.title || "").trim())],
    ["source_price", "成本", Number(item.source_price || 0) > 0],
    ["weight_g", "重量", Number(item.weight_g || 0) > 0],
    ["sku_complete", "SKU", Boolean(item.sku_complete)],
    ["image_count", "图片", Boolean(item.image_count || (item.images || []).length)],
    ["category", "类目", Boolean(String(item.category || "").trim())],
    ["risk_flags", "风险", !(item.risk_flags || []).length],
    ["market_data", "市场", Boolean(completeness.marketDataComplete)],
  ];
  return `<div class="field-status-grid">${fields.map(([key, label, ok]) => `<span class="${ok ? "ok" : "missing"}" title="${esc(ok ? "已完整" : (missing.has(key) ? "缺失" : "待补充"))}">${esc(label)}</span>`).join("")}</div>`;
}

function renderCandidateAccess(item) {
  return `<div class="candidate-access">
    <span class="${item.isReadyToScore ? "ok" : "bad"}">可评分：${item.isReadyToScore ? "是" : "否"}</span>
    <span class="${item.canCollect ? "ok" : "bad"}">可采集：${item.canCollect ? "是" : "否"}</span>
    <small>缺失 ${Number(item.missingFieldCount || 0)} 项</small>
  </div>`;
}

function renderLocalStatus(status = {}) {
  $("#local-mode").textContent = status.mode || "real";
  $("#local-dry-run").textContent = status.dryRunCollect ? "true" : "false";
  $("#local-no-publish").textContent = status.noPublish ? "true" : "false";
  $("#local-max-items").textContent = Number(status.maxItemsPerRun || 0);
  $("#local-allow-collect").textContent = status.allowCollect ? "true" : "false";
  $("#local-publish-forbidden").textContent = status.publishForbidden ? "true" : "false";
}

async function loadAll() {
  const [localStatus, browserStatus, platformStatus, dashboard, workflow, candidates, products, shops, batches, runs, publishResults, imageJobs, imageSummary, collectionQueue, settings, selfcheck] = await Promise.all([
    api("/api/local/status"), api("/api/browser/status"), api("/api/platform/status"), api("/api/dashboard"), api("/api/workflow/summary"), api("/api/candidates"), api("/api/products"), api("/api/shops"), api("/api/batches"), api("/api/runs"), api("/api/publish/results"), api("/api/images/jobs"), api("/api/images/summary"), api(`/api/collections/queue?status=${encodeURIComponent(state.collectionQueueStatus)}`), api("/api/settings"), api("/api/selfcheck"),
  ]);
  state.localStatus = localStatus;
  state.workbenchToken = localStatus.token || "";
  state.browserStatus = browserStatus;
  state.platformStatus = platformStatus;
  state.workflow = workflow.steps || [];
  state.candidates = candidates.items;
  state.products = products.items;
  state.shops = shops.items;
  state.batches = batches.items;
  state.runs = runs.items;
  state.publishResults = publishResults;
  state.imageJobs = imageJobs.items;
  state.imageSummary = imageSummary;
  state.collectionQueue = collectionQueue;
  state.settings = settings;
  $("#metric-candidates").textContent = dashboard.candidates;
  $("#metric-qualified").textContent = dashboard.qualified;
  $("#metric-products").textContent = dashboard.products;
  $("#runtime-badge").innerHTML = `<i></i> ${localStatus.mode === "real" ? "真实模式" : "演练模式"}`;
  renderLocalStatus(localStatus);
  renderWorkflow();
  renderQualifiedPool();
  renderCollectionQueue();
  renderCandidates();
  renderImageSummary();
  renderProducts();
  renderShops();
  renderBatchOptions();
  renderBatches();
  renderPublishResults();
  renderRuns();
  populateSettings();
  renderEnvironmentStatus(browserStatus, platformStatus, localStatus);
  renderPreflight(dashboard.preflight);
  renderSelfcheck(selfcheck);
}

function activateView(view) {
  const button = $(`.module-tab[data-view="${view}"]`);
  if (!button) return;
  $$('.module-tab').forEach((item) => item.classList.toggle("active", item === button));
  $$('.module-view').forEach((item) => item.classList.add("hidden"));
  $(`#view-${view}`)?.classList.remove("hidden");
}

function renderWorkflow() {
  const wrap = $("#workflow-steps");
  if (!wrap) return;
  wrap.innerHTML = state.workflow.map((step, index) => {
    const total = Number(step.pending || 0) + Number(step.done || 0) + Number(step.failed || 0);
    const doneRate = total ? Math.round(Number(step.done || 0) / total * 100) : 0;
    const target = workflowTargets[step.key] || "settings";
    return `<button class="workflow-card ${step.blocked ? "is-blocked" : ""}" type="button" data-workflow-target="${target}">
      <span class="workflow-index">${String(index + 1).padStart(2, "0")}</span>
      <span class="workflow-status">${step.blocked ? "阻塞" : "正常"}</span>
      <strong>${esc(step.name)}</strong>
      <span class="workflow-counts"><i>待 ${Number(step.pending || 0)}</i><i>成 ${Number(step.done || 0)}</i><i>异 ${Number(step.failed || 0)}</i></span>
      <span class="workflow-bar"><i style="width:${doneRate}%"></i></span>
      <span class="workflow-action">${esc(step.action || "查看")}</span>
    </button>`;
  }).join("");
  $$("[data-workflow-target]", wrap).forEach((button) => button.addEventListener("click", () => {
    activateView(button.dataset.workflowTarget);
    $(".module-tabs")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
}

function renderQualifiedPool() {
  const wrap = $("#qualified-pool");
  if (!wrap) return;
  const qualifiedCandidates = state.candidates.filter((item) => item.canCollect);
  const reviewCandidates = state.candidates.filter((item) => (item.marketSummary?.reviewCount || 0) > 0);
  const rejectedCandidates = state.candidates.filter((item) => (item.marketSummary?.rejectedCount || 0) > 0);
  const qualifiedMarkets = qualifiedCandidates.reduce((sum, item) => sum + (item.marketSummary?.collectableMarkets?.length || 0), 0);
  const items = qualifiedCandidates.map((item) => {
    const collectable = item.marketSummary?.collectableMarkets || [];
    const rejected = item.marketSummary?.rejectedMarkets || [];
    const review = item.marketSummary?.reviewMarkets || [];
    const best = collectable.map((market) => item.marketSummary?.markets?.[market]).filter(Boolean)[0];
    return `<article class="qualified-item" data-qualified-candidate="${esc(item.id)}">
      <label><input class="qualified-check" type="checkbox" value="${esc(item.id)}"> <strong>${esc(item.title || item.source_product_id || "未命名候选")}</strong></label>
      <div class="qualified-market-row">${Object.keys(markets).map((market) => {
        const status = item.marketSummary?.markets?.[market]?.decision || "review";
        const checked = collectable.includes(market) ? "checked" : "";
        const disabled = collectable.includes(market) ? "" : "disabled";
        return `<label class="market-select ${status}"><input type="checkbox" data-qualified-market="${market}" ${checked} ${disabled}>${market}</label>`;
      }).join("")}</div>
      <p>${esc(best?.reason || "至少一个国家达到采集门槛")}</p>
      <small>可采集：${collectable.join("、") || "无"} · 复核：${review.join("、") || "无"} · 阻断：${rejected.join("、") || "无"}</small>
    </article>`;
  }).join("");
  wrap.innerHTML = `
    <div class="pool-metrics">
      <article><span>可采集候选</span><strong>${qualifiedCandidates.length}</strong></article>
      <article><span>需人工复核</span><strong>${reviewCandidates.length}</strong></article>
      <article><span>不建议采集</span><strong>${rejectedCandidates.length}</strong></article>
      <article><span>达标国家总数</span><strong>${qualifiedMarkets}</strong></article>
    </div>
    <div class="qualified-list">${items || '<p class="muted-line">暂无可采集候选。完成五国评分后，至少一个国家可采集的商品会进入这里。</p>'}</div>
  `;
}

function selectedCollectionTasks() {
  return $$(".collection-task-check:checked").map((input) => input.value);
}

function collectionSelectionPayload(ids = selectedCollectionTasks()) {
  const candidateIds = [];
  const runIds = [];
  ids.forEach((id) => {
    if (id.startsWith("candidate:")) candidateIds.push(id.slice("candidate:".length));
    else runIds.push(id);
  });
  return { candidateIds, runIds };
}

function renderCollectionQueue() {
  const tabs = $("#collection-queue-tabs");
  const wrap = $("#collection-queue");
  if (!tabs || !wrap) return;
  const queues = state.collectionQueue.queues || [];
  tabs.innerHTML = queues.map((queue) => `<button class="candidate-queue-tab ${queue.key === state.collectionQueueStatus ? "active" : ""}" data-collection-queue="${esc(queue.key)}" type="button"><span>${esc(queue.name)}</span><strong>${Number(queue.count || 0)}</strong></button>`).join("");
  const items = state.collectionQueue.items || [];
  wrap.innerHTML = items.length ? `
    <div class="collection-task-head"><span></span><span>商品</span><span>国家</span><span>当前步骤</span><span>状态</span><span>诊断</span><span></span></div>
    ${items.map((item) => {
      const reason = item.reason || item.error || "";
      const canOpen = item.queue === "failed" || reason || item.screenshot || item.currentUrl;
      return `<article class="collection-task-row status-${esc(item.queue)}">
        <input class="collection-task-check" type="checkbox" value="${esc(item.id)}">
        <div><strong>${esc(item.product || "未命名候选")}</strong><a href="${esc(item.sourceUrl || "#")}" target="_blank" rel="noreferrer">${esc(item.sourceProductId || "来源链接")}</a></div>
        <span>${esc((item.markets || []).join("、") || item.market || "-")}</span>
        <span>${esc(item.currentStep || "-")}</span>
        <span><b>${esc(item.statusLabel || item.queueLabel || item.status || "-")}</b><small>${Number(item.attempts || 0)} 次 · ${item.lastRunAt ? new Date(item.lastRunAt * 1000).toLocaleString() : "-"}</small></span>
        <span>${reason ? esc(reason) : esc((item.suggestedActions || [])[0] || "-")}</span>
        <button class="table-action" data-collection-detail="${esc(item.id)}" type="button">${canOpen ? "详情" : "查看"}</button>
      </article>`;
    }).join("")}
  ` : '<div class="table-empty">当前队列暂无采集任务。</div>';
  $$("[data-collection-queue]", tabs).forEach((button) => button.addEventListener("click", async () => {
    state.collectionQueueStatus = button.dataset.collectionQueue;
    await refreshCollectionQueue();
  }));
  $$("[data-collection-detail]", wrap).forEach((button) => button.addEventListener("click", () => openCollectionDetail(button.dataset.collectionDetail)));
}

async function refreshCollectionQueue() {
  const data = await api(`/api/collections/queue?status=${encodeURIComponent(state.collectionQueueStatus)}`);
  state.collectionQueue = data;
  renderCollectionQueue();
}

async function collectionBulkAction(action) {
  const ids = selectedCollectionTasks();
  const payload = { action, ...collectionSelectionPayload(ids) };
  try {
    const data = await api("/api/collections/bulk-action", { method: "POST", body: JSON.stringify(payload) });
    const changed = Number((data.created || []).length + (data.updated || []).length);
    const blocked = Number((data.blocked || []).length);
    notify(blocked ? `已处理 ${changed} 个，${blocked} 个被拦截` : `已处理 ${changed} 个采集任务`, blocked ? "error" : "success");
    await loadAll();
  } catch (error) {
    notify(error.message, "error");
  }
}

async function openCollectionDetail(taskId) {
  try {
    const item = await api(`/api/collections/tasks/${encodeURIComponent(taskId)}`);
    state.currentCollectionTask = item;
    const suggestions = (item.suggestedActions || []).map((action) => `<li>${esc(action)}</li>`).join("");
    const clickable = (item.clickableText || []).slice(0, 12).map((text) => `<span>${esc(text)}</span>`).join("");
    $("#collection-detail-content").innerHTML = `
      <div class="failure-detail-grid collection-detail-grid">
        <span>失败商品：${esc(item.product || item.title || "-")}</span>
        <span>失败国家：${esc((item.markets || []).join("、") || item.market || "-")}</span>
        <span>失败步骤：${esc(item.currentStep || "-")}</span>
        <span>错误原因：${esc(item.reason || item.error || "-")}</span>
        <span>尝试次数：${Number(item.attempts || 0)}</span>
        <span>最近执行：${item.lastRunAt ? new Date(item.lastRunAt * 1000).toLocaleString() : "-"}</span>
        <span>当前 URL：${item.currentUrl ? `<a href="${esc(item.currentUrl)}" target="_blank" rel="noreferrer">${esc(item.currentUrl)}</a>` : "-"}</span>
        <span>截图：${item.screenshot ? `<a href="${esc(item.screenshot)}" target="_blank" rel="noreferrer">打开截图</a>` : "-"}</span>
      </div>
      <section class="collection-detail-section"><h3>建议修复动作</h3>${suggestions ? `<ul>${suggestions}</ul>` : '<p class="muted-line">暂无建议。</p>'}</section>
      <section class="collection-detail-section"><h3>可点击文本摘要</h3>${clickable ? `<div class="clickable-summary">${clickable}</div>` : '<p class="muted-line">暂无页面文本摘要。</p>'}</section>
    `;
    $("#collection-detail-retry").disabled = !item.canRetry && item.source !== "candidate";
    $("#collection-detail-skip").disabled = !item.canSkip;
    $("#collection-detail-dialog").showModal();
  } catch (error) {
    notify(error.message, "error");
  }
}

function renderCandidates() {
  const body = $("#candidate-table");
  body.innerHTML = "";
  renderCandidateQueues();
  const items = filteredCandidates();
  $("#candidate-empty").classList.toggle("hidden", items.length > 0);
  for (const item of items) {
    const tr = document.createElement("tr");
    const scores = Object.keys(markets).map((market) => `<td>${marketChip(item, market)}</td>`).join("");
    const images = Number(item.image_count || (item.images || []).length || 0);
    const riskFlags = (item.risk_flags || []).join("、") || "无";
    tr.innerHTML = `
      <td><input class="candidate-check" type="checkbox" value="${esc(item.id)}"></td>
      <td><div class="candidate-name"><strong>${esc(item.title || `1688商品 ${item.source_product_id || "待识别"}`)}</strong><a href="${esc(item.source_url)}" target="_blank" rel="noreferrer">${esc(item.source_product_id || "查看来源")}</a></div></td>
      <td><span>${esc(item.category || "待补充")}</span><small>¥${Number(item.source_price || 0).toFixed(2)} · ${Number(item.weight_g || 0)}g · SKU${item.sku_complete ? "完整" : "缺失"} · 图${images}</small>${renderCompleteness(item)}<small>风险：${esc(riskFlags)}</small></td>
      <td>${renderFieldStatus(item)}</td>
      <td>${renderMissingHints(item)}<button class="inline-next" data-candidate-next="${esc(item.id)}" type="button">${esc(item.nextAction || "补数据")}</button><small class="market-summary-line">${esc(item.marketSummary?.nextAction || "")}${item.dataCompleteness?.marketDataComplete ? " · 市场数据完整" : " · 市场数据待补"}${item.marketSummary?.qualifiedCount ? ` · 达标 ${item.marketSummary.qualifiedCount} 国` : ""}</small></td>
      ${scores}
      <td>${renderCandidateAccess(item)}</td>
      <td><span class="status-chip status-${esc(item.status)}">${esc(item.status)}</span></td>
      <td><button class="table-action" data-edit-candidate="${esc(item.id)}" type="button">补数据</button></td>`;
    body.appendChild(tr);
  }
  $$('[data-edit-candidate]').forEach((button) => button.addEventListener("click", () => openCandidate(button.dataset.editCandidate)));
  $$('[data-candidate-next]').forEach((button) => button.addEventListener("click", () => handleCandidateNext(button)));
}

async function handleCandidateNext(button) {
  const item = state.candidates.find((candidate) => candidate.id === button.dataset.candidateNext);
  if (!item) return;
  if (item.nextAction === "从来源补全") {
    button.disabled = true;
    try {
      const refreshed = await api(`/api/candidates/${item.id}/refresh-source`, { method: "POST", body: "{}" });
      notify("已从来源补全候选数据");
      await loadAll();
      state.currentCandidate = refreshed;
    } catch (error) {
      notify(error.message, "error");
      openCandidate(item.id);
    } finally {
      button.disabled = false;
    }
    return;
  }
  openCandidate(item.id);
}

function selectedCandidates() {
  return $$(".candidate-check:checked").map((input) => input.value);
}

function selectedQualifiedCandidates() {
  return $$(".qualified-check:checked").map((input) => input.value);
}

function selectedQualifiedMarkets() {
  const marketsByCandidate = {};
  $$(".qualified-check:checked").forEach((input) => {
    const card = input.closest("[data-qualified-candidate]");
    const selected = $$("[data-qualified-market]:checked", card).map((item) => item.dataset.qualifiedMarket);
    marketsByCandidate[input.value] = selected;
  });
  const merged = new Set(Object.values(marketsByCandidate).flat());
  return [...merged];
}

function populateCandidateForm(item) {
  if (!item) return;
  const form = $("#candidate-form");
  ["id", "title", "category", "source_price", "weight_g", "monthly_sales", "repurchase_rate", "rating", "supplier_years", "dispatch_hours", "image_count"].forEach((name) => {
    if (form.elements[name]) form.elements[name].value = item[name] ?? "";
  });
  form.elements.sku_complete.checked = Boolean(item.sku_complete);
  const marketInputs = $("#market-inputs");
  marketInputs.innerHTML = Object.entries(markets).map(([code, name]) => {
    const evaluation = getEvaluation(item, code);
    const metrics = evaluation?.metrics || {};
    return `<fieldset data-market="${code}"><legend>${name}</legend>
      <label><span>90天趋势</span><input name="${code}-trend" type="number" min="0" max="100" value="${metrics.trend ?? ""}"></label>
      <label><span>销量信号</span><input name="${code}-sales" type="number" min="0" max="100" value="${metrics.sales_signal ?? ""}"></label>
      <label><span>竞争强度</span><input name="${code}-competition" type="number" min="0" max="100" value="${metrics.competition ?? ""}"></label>
      <label><span>目标售价 CNY</span><input name="${code}-price" type="number" step="0.01" value="${metrics.target_price_cny ?? ""}"></label>
      <label class="switch-row"><input name="${code}-complete" type="checkbox" ${metrics.market_data_complete ? "checked" : ""}> 已取得真实市场样本</label>
    </fieldset>`;
  }).join("");
}

function openCandidate(id) {
  const item = state.candidates.find((candidate) => candidate.id === id);
  if (!item) return;
  state.currentCandidate = item;
  populateCandidateForm(item);
  $("#candidate-dialog").showModal();
}

const imageStatusText = {
  needs_generation: "待生成",
  missing_source_image: "缺主图",
  generating: "生成中",
  generation_success: "生成成功",
  awaiting_approval: "待审核",
  approved: "已通过",
  generation_failed: "生成失败",
  rejected: "审核不通过",
};
const defaultRejectionReasons = ["鞋子变形", "颜色不一致", "文字错误", "Logo 错误", "背景杂乱", "主体不清晰", "风格不符合平台", "其他"];
const batchRiskLabels = {
  missing_image: "缺图商品",
  blocked_market: "被拦截国家版本",
  duplicate: "重复铺货风险",
  price: "价格异常",
  inventory: "库存异常",
  warehouse: "仓库异常",
  missing_version: "缺国家版本",
  missing_product: "缺商品",
  missing_shop: "缺店铺",
  missing_title: "缺本地标题",
  selection: "选择不完整",
  shop_disabled: "店铺不可用",
  environment: "妙手环境",
  margin: "毛利偏低",
  short_title: "标题较短",
  image_count: "图片偏少",
  confidence: "置信度不足",
};

function imageSummaryForProduct(productId) {
  return (state.imageSummary.items || []).find((item) => item.productId === productId) || {};
}

function renderImageSummary() {
  const wrap = $("#image-workbench");
  if (!wrap) return;
  const overview = state.imageSummary.overview || {};
  const failedItems = (state.imageSummary.items || []).filter((item) => item.status === "generation_failed");
  wrap.innerHTML = `
    <div class="image-workbench-metrics">
      <article><span>正式商品</span><strong>${Number(overview.totalProducts || 0)}</strong></article>
      <article><span>待生成/缺图</span><strong>${Number(overview.needsGeneration || 0)}</strong></article>
      <article><span>生成中</span><strong>${Number(overview.generating || 0)}</strong></article>
      <article><span>待审核</span><strong>${Number(overview.awaitingApproval || 0)}</strong></article>
      <article><span>已通过</span><strong>${Number(overview.approved || 0)}</strong></article>
      <article class="${Number(overview.failed || 0) ? "metric-danger" : ""}"><span>失败</span><strong>${Number(overview.failed || 0)}</strong></article>
    </div>
    ${failedItems.length ? `<div class="image-failure-strip">${failedItems.slice(0, 4).map((item) => `<button type="button" data-focus-product="${esc(item.productId)}"><strong>${esc(item.title || "未命名商品")}</strong><span>${esc(item.failure?.error || "生图失败")}</span></button>`).join("")}</div>` : ""}
  `;
  $$("[data-focus-product]", wrap).forEach((button) => button.addEventListener("click", () => {
    document.querySelector(`[data-product-card="${CSS.escape(button.dataset.focusProduct)}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }));
}

function productImageStatusMarkup(product, summary, imageJob) {
  const status = summary.status || (imageJob ? "generating" : "needs_generation");
  const jobText = imageJob ? `${imageJob.completed_count || 0}/${imageJob.requested_count || 0}` : "";
  const error = summary.failure?.error || imageJob?.error || "";
  const suggestions = summary.failure?.suggestedActions || [];
  const details = [
    `通过 ${Number(summary.approvedCount || 0)}`,
    `待审 ${Number(summary.pendingReviewCount || 0)}`,
    `素材 ${Number(summary.assetCount || 0)}`,
  ].join(" · ");
  return `<div class="image-status-panel status-${esc(status)}">
    <div><span>${esc(imageStatusText[status] || "待处理")}</span><strong>${esc(summary.action || "查看图片")}${jobText ? ` · ${esc(jobText)}` : ""}</strong></div>
    <small>${esc(details)}</small>
    ${error ? `<p>${esc(error)}</p>` : ""}
    ${suggestions.length ? `<ul>${suggestions.slice(0, 2).map((item) => `<li>${esc(item)}</li>`).join("")}</ul>` : ""}
  </div>`;
}

function renderProducts() {
  const wrap = $("#product-cards");
  wrap.innerHTML = "";
  $("#product-empty").classList.toggle("hidden", state.products.length > 0);
  for (const product of state.products) {
    const card = document.createElement("article");
    card.className = "product-studio-card";
    card.dataset.productCard = product.id;
    const image = product.mainImage ? (product.mainImage.startsWith("/assets/") ? product.mainImage : `/api/image?url=${encodeURIComponent(product.mainImage)}`) : "";
    const imageJob = state.imageJobs.find((job) => job.product_id === product.id);
    const imageSummary = imageSummaryForProduct(product.id);
    const failedJob = imageSummary.latestJob?.status === "failed" ? imageSummary.latestJob : null;
    const workflow = product.workflowStatus || {};
    const workflowDetail = workflow.detail || workflow.nextAction || product.status || "";
    card.innerHTML = `
      <div class="studio-image">${image ? `<img src="${esc(image)}" alt="">` : "<span>NO IMAGE</span>"}</div>
      <div class="studio-body"><div class="studio-chip-row"><span class="status-chip">${esc(workflow.label || product.status || "流程待判断")}</span>${workflow.failed ? '<span class="status-chip danger">失败处理</span>' : ""}${imageJob ? `<span class="status-chip">生图：${esc(imageJob.status)}</span>` : ""}</div><h3>${esc(product.title || "未命名商品")}</h3><p>${esc(product.category || "待分类")} · ${Number(product.weightG || 0)}g</p>
      ${productImageStatusMarkup(product, imageSummary, imageJob)}
      <small class="workflow-status-line">${esc(workflowDetail)}</small>
      <div class="studio-actions"><button class="button outline small" data-localize="${product.id}" type="button">AI本地化</button><button class="button outline small" data-market="${product.id}" type="button">五国资料</button><button class="button outline small" data-generate="${product.id}" type="button">AI生图</button><label class="button outline small upload-button">上传图片<input data-upload="${product.id}" type="file" accept="image/png,image/jpeg,image/webp"></label><button class="button dark small" data-assets="${product.id}" type="button">图片审核</button>${failedJob ? `<button class="button accent small" data-retry-image-job="${failedJob.id}" type="button">重试生图</button>` : ""}</div></div>`;
    wrap.appendChild(card);
  }
  $$('[data-generate]').forEach((button) => button.addEventListener("click", () => openGeneration(button.dataset.generate)));
  $$('[data-assets]').forEach((button) => button.addEventListener("click", () => showAssets(button.dataset.assets)));
  $$('[data-market]').forEach((button) => button.addEventListener("click", () => openMarkets(button.dataset.market)));
  $$('[data-localize]').forEach((button) => button.addEventListener("click", async () => {
    button.disabled = true;
    try { await api(`/api/products/${button.dataset.localize}/localize`, { method: "POST", body: "{}" }); notify("英语、泰语和越南语版本已生成"); } catch (error) { notify(error.message, "error"); } finally { button.disabled = false; }
  }));
  $$('[data-upload]').forEach((input) => input.addEventListener("change", () => uploadProductImage(input)));
  $$('[data-retry-image-job]').forEach((button) => button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await api(`/api/images/jobs/${button.dataset.retryImageJob}/retry`, { method: "POST", body: "{}" });
      notify("生图任务已重新排队");
      await loadAll();
    } catch (error) {
      notify(error.message, "error");
    } finally {
      button.disabled = false;
    }
  }));
}

function openGeneration(productId) {
  $("#generation-form").elements.productId.value = productId;
  $("#image-dialog").showModal();
}

async function showAssets(productId) {
  const data = await api(`/api/assets?productId=${encodeURIComponent(productId)}`);
  if (!data.items.length) return notify("该商品还没有生成图片", "error");
  $("#asset-review-grid").innerHTML = data.items.map((asset) => `<article class="asset-review-card"><img src="${esc(asset.url)}" alt="待审核商品图片"><div><span class="status-chip">${asset.approved ? "已审核" : "待审核"}</span><p>${esc(asset.prompt || asset.kind)}</p>${asset.approved ? "" : `<button class="button accent small" data-approve-asset="${asset.id}" type="button">审核通过</button>`}</div></article>`).join("");
  $$('[data-approve-asset]').forEach((button) => button.addEventListener("click", async () => {
    try { await api(`/api/images/${button.dataset.approveAsset}/approve`, { method: "POST", body: "{}" }); await showAssets(productId); notify("图片已审核通过"); } catch (error) { notify(error.message, "error"); }
  }));
  if (!$("#asset-dialog").open) $("#asset-dialog").showModal();
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("无法读取图片"));
    reader.readAsDataURL(file);
  });
}

async function uploadProductImage(input) {
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  try {
    await api("/api/assets", { method: "POST", body: JSON.stringify({ productId: input.dataset.upload, dataUrl: await fileToDataUrl(file), approved: true, kind: "uploaded" }) });
    notify("本地图片已上传并登记为审核通过");
  } catch (error) { notify(error.message, "error"); }
}

async function openMarkets(productId) {
  try {
    const data = await api(`/api/products/${productId}/markets`);
    $("#market-form").elements.productId.value = productId;
    $("#market-version-fields").innerHTML = data.items.map((item) => `<div class="market-version-row" data-version-market="${item.market}"><strong>${esc(markets[item.market])}</strong><label><span>本地标题</span><input name="title" value="${esc(item.title)}"></label><label><span>售价 ${esc(item.currency)}</span><input name="sale_price" type="number" step="0.01" value="${item.sale_price}"></label><label><span>仓库</span><input name="warehouse" value="${esc(item.warehouse)}"></label><label><span>库存</span><input name="inventory" type="number" value="${item.inventory}"></label><label class="switch-row"><input name="blocked" type="checkbox" ${item.blocked ? "checked" : ""}> 风险拦截</label></div>`).join("");
    $("#market-dialog").showModal();
  } catch (error) { notify(error.message, "error"); }
}

function renderShops() {
  $("#shop-list").innerHTML = state.shops.map((shop) => `<div class="shop-row"><span>${esc(markets[shop.market])}</span><strong>${esc(shop.shop_name)}</strong><small>${esc(shop.account_name)} · ${esc(shop.warehouse || "未设仓库")} · 售价×${Number(shop.price_multiplier || 1).toFixed(2)}</small></div>`).join("") || '<p class="muted-line">尚未配置店铺。</p>';
}

function renderBatchOptions() {
  $("#batch-products").innerHTML = state.products.map((product) => `<label><input type="checkbox" value="${product.id}">${esc(product.title || "未命名商品")} · ${esc(product.workflowStatus?.label || "未判断")}</label>`).join("") || "暂无商品";
  $("#batch-shops").innerHTML = state.shops.map((shop) => `<label><input type="checkbox" value="${shop.id}">${esc(shop.shop_name)} · ${esc(shop.market)}</label>`).join("") || "暂无店铺";
  $$("#batch-products input, #batch-shops input, #batch-form [name=dryRun]").forEach((input) => input.addEventListener("change", () => {
    state.batchPreview = null;
    renderBatchPreview();
  }));
  renderBatchPreview();
}

function renderBatchPreview() {
  const wrap = $("#batch-preview");
  if (!wrap) return;
  const preview = state.batchPreview;
  if (!preview) {
    wrap.innerHTML = '<p class="muted-line">选择商品和店铺后点击“预检批次”。</p>';
    return;
  }
  const riskGroups = Object.entries(preview.counts || {}).filter(([, count]) => count > 0).map(([key, count]) => `<span>${esc(batchRiskLabels[key] || key)} ${Number(count)}</span>`).join("") || '<span>暂无风险</span>';
  const risks = (preview.risks || []).slice(0, 12).map((item) => `<li class="risk-${esc(item.severity || "warning")}"><strong>${item.severity === "error" ? "阻塞" : "警告"} · ${esc(item.message)}</strong>${item.detail ? `<small>${esc(item.detail)}</small>` : ""}</li>`).join("") || '<li class="risk-ok"><strong>无风险</strong></li>';
  wrap.innerHTML = `
    <div class="batch-preview-summary">
      <article><span>商品</span><strong>${Number(preview.productCount || 0)}</strong></article>
      <article><span>店铺</span><strong>${Number(preview.shopCount || 0)}</strong></article>
      <article><span>国家版本</span><strong>${Number(preview.versionCount || 0)}</strong></article>
      <article><span>任务</span><strong>${Number(preview.taskCount || 0)}</strong></article>
      <article class="${Number(preview.blockingCount || preview.errors || 0) ? "preview-bad" : "preview-ok"}"><span>阻塞</span><strong>${Number(preview.blockingCount || preview.errors || 0)}</strong></article>
      <article><span>警告</span><strong>${Number(preview.warningCount || preview.warnings || 0)}</strong></article>
      <article><span>重复风险</span><strong>${Number(preview.duplicateRiskCount || preview.counts?.duplicate || 0)}</strong></article>
      <article class="${preview.ready ? "preview-ok" : "preview-bad"}"><span>状态</span><strong>${esc(preview.statusLabel || (preview.ready ? "可执行" : "阻塞"))}</strong></article>
    </div>
    <div class="batch-risk-pills">${riskGroups}</div>
    <ul class="batch-risk-list">${risks}</ul>
    <div class="batch-preview-actions"><button class="button outline small" data-copy-precheck type="button">复制预检结果</button><button class="button outline small" data-export-precheck type="button">导出JSON</button></div>
  `;
  $("[data-copy-precheck]", wrap)?.addEventListener("click", copyBatchPrecheck);
  $("[data-export-precheck]", wrap)?.addEventListener("click", exportBatchPrecheck);
}

function batchPrecheckText(preview = state.batchPreview) {
  if (!preview) return "";
  const lines = [
    `状态：${preview.statusLabel || (preview.ready ? "可执行" : "阻塞")}`,
    `商品：${preview.productCount || 0}，店铺：${preview.shopCount || 0}，国家版本：${preview.versionCount || 0}，任务：${preview.taskCount || 0}`,
    `阻塞：${preview.blockingCount || preview.errors || 0}，警告：${preview.warningCount || preview.warnings || 0}，重复风险：${preview.duplicateRiskCount || preview.counts?.duplicate || 0}`,
    ...((preview.risks || []).map((item) => `${item.severity === "error" ? "阻塞" : "警告"}｜${batchRiskLabels[item.category] || item.category}｜${item.message}${item.detail ? `｜${item.detail}` : ""}`)),
  ];
  return lines.join("\n");
}

async function copyBatchPrecheck() {
  if (!state.batchPreview) return notify("请先预检批次", "error");
  try {
    await navigator.clipboard.writeText(batchPrecheckText());
    notify("预检结果已复制");
  } catch (error) {
    notify("浏览器不允许复制，请使用导出JSON", "error");
  }
}

function exportBatchPrecheck() {
  if (!state.batchPreview) return notify("请先预检批次", "error");
  const blob = new Blob([JSON.stringify(state.batchPreview, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `batch-precheck-${Date.now()}.json`;
  link.click();
  URL.revokeObjectURL(url);
}

function renderBatchConfirmation(data) {
  const wrap = $("#batch-confirm-content");
  const summary = data.summary || {};
  const risks = data.preflight?.risks || [];
  const report = data.dryRunReport || {};
  const gate = data.liveGate || {};
  const riskList = risks.length
    ? risks.slice(0, 8).map((item) => `<li class="risk-${esc(item.severity || "warning")}"><strong>${esc(item.message)}</strong>${item.detail ? `<small>${esc(item.detail)}</small>` : ""}</li>`).join("")
    : "<li><strong>预检无异常</strong></li>";
  const phrase = data.phrase || "";
  wrap.innerHTML = `
    <div class="confirm-mode ${data.batch?.dry_run ? "is-dry" : "is-live"}">
      <strong>${esc(data.mode || "确认")}</strong>
      <span>${data.batch?.dry_run ? "演练只执行到发布前一步，不会点击最终发布" : "真实发布会进入妙手最终发布动作"}</span>
    </div>
    <div class="batch-preview-summary">
      <article><span>商品</span><strong>${Number(summary.products || 0)}</strong></article>
      <article><span>店铺</span><strong>${Number(summary.shops || 0)}</strong></article>
      <article><span>国家版本</span><strong>${Number(summary.versions || 0)}</strong></article>
      <article><span>任务</span><strong>${Number(summary.publishTasks || 0)}</strong></article>
      <article class="${data.canConfirm ? "preview-ok" : "preview-bad"}"><span>门禁</span><strong>${data.canConfirm ? "可确认" : "不可确认"}</strong></article>
    </div>
    <div class="confirm-risk-grid">
      <span>缺图 ${Number(summary.missingImages || 0)}</span>
      <span>国家拦截 ${Number(summary.blockedMarkets || 0)}</span>
      <span>重复 ${Number(summary.duplicateRisks || 0)}</span>
      <span>价格 ${Number(summary.priceIssues || 0)}</span>
      <span>库存 ${Number(summary.inventoryIssues || 0)}</span>
      <span>仓库 ${Number(summary.warehouseIssues || 0)}</span>
      <span>未处理失败 ${Number(summary.unhandledFailures || 0)}</span>
    </div>
    <div class="dry-run-report">
      <div><span>演练报告</span><strong>${report.batchId ? esc(report.batchId) : "未匹配"}</strong></div>
      <div><span>成功步骤</span><strong>${Number(report.successSteps || 0)}</strong></div>
      <div><span>失败步骤</span><strong>${Number(report.failedSteps || 0)}</strong></div>
      <div><span>建议真实发布</span><strong>${report.suggestLivePublish ? "是" : "否"}</strong></div>
    </div>
    ${!data.batch?.dry_run && !gate.dryRunReport ? `<label class="switch-row live-skip-row"><input id="skip-dry-run" type="checkbox"> 明确跳过演练并承担真实发布风险</label>` : ""}
    ${gate.blockedReasons?.length ? `<ul class="batch-risk-list">${gate.blockedReasons.map((item) => `<li class="risk-error"><strong>${esc(item)}</strong></li>`).join("")}</ul>` : ""}
    <ul class="batch-risk-list">${riskList}</ul>
    <div class="confirm-phrase"><span>需要输入</span><strong>${esc(phrase)}</strong></div>
  `;
  $("#batch-confirm-hint").textContent = data.batch?.dry_run
    ? "演练确认会完成全流程检查，但不会点击最终发布。"
    : "真实发布必须输入固定确认文本，且通过后端门禁。";
  $("#batch-confirm-form").elements.confirmation.value = "";
  $("#batch-confirm-form").elements.confirmation.placeholder = phrase;
}

async function openBatchConfirmation(batchId) {
  try {
    const data = await api(`/api/batches/${batchId}/confirmation`);
    $("#batch-confirm-form").elements.batchId.value = batchId;
    renderBatchConfirmation(data);
    $("#batch-confirm-dialog").showModal();
  } catch (error) {
    notify(error.message, "error");
  }
}

async function refreshBatchPreview() {
  const productIds = $$("#batch-products input:checked").map((input) => input.value);
  const shopIds = $$("#batch-shops input:checked").map((input) => input.value);
  try {
    const preview = await api("/api/batches/precheck", { method: "POST", body: JSON.stringify({ productIds, shopIds, dryRun: $("#batch-form").elements.dryRun.checked }) });
    state.batchPreview = preview;
    renderBatchPreview();
    notify(preview.ready ? "批次预检通过" : "批次存在风险", preview.ready ? "success" : "error");
  } catch (error) {
    state.batchPreview = error.preflight || null;
    renderBatchPreview();
    notify(error.message, "error");
  }
}

function renderBatches() {
  $("#batch-list").innerHTML = state.batches.map((batch) => {
    const summary = batch.summary || {};
    const riskCounts = summary.riskCounts || {};
    const riskText = Object.entries(riskCounts).filter(([, count]) => count > 0).slice(0, 4).map(([key, count]) => `${batchRiskLabels[key] || key} ${count}`).join(" · ");
    const run = state.runs.find((item) => item.batch_id === batch.id && item.kind === "publish" && item.status === "waiting_confirmation");
    return `<div class="run-row"><div><strong>${esc(batch.name)}</strong><span>${summary.products || 0}款 · ${summary.shops || 0}店 · ${batch.dry_run ? "演练" : "真实"}${riskText ? ` · ${esc(riskText)}` : ""}</span></div><div class="run-progress"><span style="width:${batch.status === "draft" ? 15 : batch.status === "preparing" ? 70 : 100}%"></span></div><span class="status-chip">${esc(batch.status)}</span>${batch.status === "draft" ? `<button class="table-action" data-prepare-batch="${batch.id}" type="button">准备</button>` : ""}${run && run.status === "waiting_confirmation" ? `<button class="table-action" data-confirm-batch="${batch.id}" type="button">强确认</button>` : ""}</div>`;
  }).join("") || '<div class="table-empty">暂无铺货批次。</div>';
  $$('[data-prepare-batch]').forEach((button) => button.addEventListener("click", async () => {
    try { await api(`/api/batches/${button.dataset.prepareBatch}/prepare`, { method: "POST", body: "{}" }); notify("批次准备完成，等待确认"); await loadAll(); } catch (error) { notify(error.message, "error"); }
  }));
  $$('[data-confirm-batch]').forEach((button) => button.addEventListener("click", () => openBatchConfirmation(button.dataset.confirmBatch)));
}

function renderPublishResults() {
  const wrap = $("#publish-results-center");
  if (!wrap) return;
  const data = state.publishResults || { overview: {}, failures: [], waiting: [] };
  const overview = data.overview || {};
  const failures = data.failures || [];
  const waiting = data.waiting || [];
  const failureRows = failures.slice(0, 20).map((item) => `<details class="failure-card">
    <summary>
      <div><strong>${esc(item.type || item.label || "失败任务")}</strong><span>${esc([item.product, item.market, item.shop].filter(Boolean).join(" · ") || item.batch || "未关联商品")}</span></div>
      <small>${esc(item.currentStep || "未记录步骤")}</small>
      <b>${Number(item.attempts || 0)}次</b>
    </summary>
    <div class="failure-detail-grid">
      <span>批次：${esc(item.batch || item.batchId || "-")}</span>
      <span>原因：${esc(item.reason || item.error || "未记录")}</span>
      <span>最近失败：${item.lastFailedAt ? new Date(item.lastFailedAt * 1000).toLocaleString() : "-"}</span>
      <span>URL：${item.currentUrl ? `<a href="${esc(item.currentUrl)}" target="_blank" rel="noreferrer">${esc(item.currentUrl)}</a>` : "-"}</span>
      <span>截图：${item.screenshot ? `<a href="${esc(item.screenshot)}" target="_blank" rel="noreferrer">打开截图</a>` : "-"}</span>
      <span>建议：${esc((item.suggestedActions || []).join("；") || "检查后处理")}</span>
    </div>
    <div class="failure-actions">
      ${(item.actions || []).includes("retry") ? `<button class="table-action" data-failure-action="retry" data-failure-source="${esc(item.source)}" data-failure-id="${esc(item.id)}" type="button">重试</button>` : ""}
      ${(item.actions || []).includes("skip") ? `<button class="table-action" data-failure-action="skip" data-failure-source="${esc(item.source)}" data-failure-id="${esc(item.id)}" type="button">跳过</button>` : ""}
      ${(item.actions || []).includes("mark_handled") ? `<button class="table-action" data-failure-action="mark_handled" data-failure-source="${esc(item.source)}" data-failure-id="${esc(item.id)}" type="button">已处理</button>` : ""}
      ${(item.actions || []).includes("manual") ? `<button class="table-action" data-failure-action="manual" data-failure-source="${esc(item.source)}" data-failure-id="${esc(item.id)}" type="button">转人工</button>` : ""}
      <button class="table-action" data-copy-error="${esc(`${item.type || ""} ${item.currentStep || ""} ${item.reason || item.error || ""}`)}" type="button">复制错误</button>
    </div>
  </details>`).join("") || '<p class="muted-line">暂无失败任务。</p>';
  const waitingRows = waiting.slice(0, 5).map((item) => `<div class="result-task-row">
    <div><strong>${esc(item.batchName || item.label || "任务")}</strong><span>${esc(item.status)} · ${esc(item.currentStep || "等待处理")}</span></div>
    <small>${esc((item.suggestedActions || []).join("；") || "等待人工确认或认领")}</small>
  </div>`).join("") || '<p class="muted-line">暂无待处理任务。</p>';
  const shopRows = (data.shopStats || []).slice(0, 6).map((item) => `<span>${esc(item.name)} ${Number(item.successRate || 0)}%</span>`).join("") || "<span>暂无店铺数据</span>";
  const marketRows = (data.marketStats || []).slice(0, 6).map((item) => `<span>${esc(item.name)} ${Number(item.successRate || 0)}%</span>`).join("") || "<span>暂无国家数据</span>";
  wrap.innerHTML = `
    <div class="result-metrics">
      <article><span>总任务</span><strong>${Number(overview.totalTasks || overview.totalRuns || 0)}</strong></article>
      <article><span>成功</span><strong>${Number(overview.successTasks || overview.completedRuns || 0)}</strong></article>
      <article><span>失败</span><strong>${Number(overview.failedTasks || overview.failedRuns || 0)}</strong></article>
      <article><span>跳过</span><strong>${Number(overview.skippedTasks || 0)}</strong></article>
      <article><span>重复拦截</span><strong>${Number(overview.duplicateBlocked || 0)}</strong></article>
      <article><span>成功率</span><strong>${Number(overview.successRate || 0)}%</strong></article>
    </div>
    <div class="result-rate-grid"><section><h3>店铺成功率</h3>${shopRows}</section><section><h3>国家成功率</h3>${marketRows}</section></div>
    <div class="result-metrics secondary">
      <article><span>运行中</span><strong>${Number(overview.activeRuns || 0)}</strong></article>
      <article><span>待确认</span><strong>${Number(overview.waitingRuns || 0)}</strong></article>
      <article><span>已发布</span><strong>${Number(overview.publishedTasks || 0)}</strong></article>
      <article><span>演练完成</span><strong>${Number(overview.dryRunTasks || 0)}</strong></article>
    </div>
    <div class="result-columns">
      <section class="failure-center"><h3>失败任务中心</h3>${failureRows}</section>
      <section><h3>待处理任务</h3>${waitingRows}</section>
    </div>
  `;
  $$('[data-failure-action]', wrap).forEach((button) => button.addEventListener("click", async () => {
    try {
      const action = button.dataset.failureAction;
      await api("/api/failures/action", { method: "POST", body: JSON.stringify({ source: button.dataset.failureSource, id: button.dataset.failureId, action }) });
      notify(action === "retry" ? "任务已重新排队" : "失败任务状态已更新");
      await loadAll();
    } catch (error) {
      notify(error.message, "error");
    }
  }));
  $$('[data-copy-error]', wrap).forEach((button) => button.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(button.dataset.copyError || ""); notify("错误信息已复制"); } catch (error) { notify("复制失败", "error"); }
  }));
}

function renderRuns() {
  const wrap = $("#run-list");
  wrap.innerHTML = state.runs.map((run) => {
    const steps = Array.isArray(run.steps) ? run.steps : [];
    const completed = steps.filter((step) => typeof step === "object" && step.status === "completed").length;
    const diagnostics = run.diagnostics || {};
    const hasDiagnostics = diagnostics.error || diagnostics.failedStep || run.screenshot || run.error;
    const detail = hasDiagnostics ? `<details class="run-diagnostics"><summary>诊断</summary>
      <div><span>失败步骤</span><strong>${esc(diagnostics.failedStep || run.current_step || "未记录")}</strong></div>
      <div><span>错误信息</span><strong>${esc(diagnostics.error || run.error || "未记录")}</strong></div>
      <div><span>当前URL</span><strong>${esc(diagnostics.currentUrl || "未记录")}</strong></div>
      <div><span>截图路径</span><strong>${esc(diagnostics.screenshot || run.screenshot || "未记录")}</strong></div>
      <div><span>建议动作</span><strong>${esc((diagnostics.suggestedActions || []).join("；") || "检查配置后重试")}</strong></div>
      ${(diagnostics.clickableText || []).length ? `<div><span>可点击文本</span><strong>${esc((diagnostics.clickableText || []).slice(0, 8).join(" / "))}</strong></div>` : ""}
    </details>` : "";
    return `<div class="run-row"><div><strong>${run.kind === "collection" ? "妙手采集" : run.kind === "publish" ? "铺货批次" : "关键词找品"}</strong><span>${esc(run.current_step || "等待执行")}</span></div><div class="run-progress"><span style="width:${steps.length ? completed / steps.length * 100 : 0}%"></span></div><span class="status-chip">${esc(run.status)}</span>${run.error ? `<small class="run-error">${esc(run.error)}</small>` : ""}${["failed", "blocked", "waiting_browser"].includes(run.status) ? `<button class="table-action" data-retry="${run.id}" type="button">重试</button>` : ""}${detail}</div>`;
  }).join("") || '<div class="table-empty">暂无自动化任务。</div>';
  $$('[data-retry]').forEach((button) => button.addEventListener("click", async () => {
    try { await api(`/api/runs/${button.dataset.retry}/retry`, { method: "POST", body: "{}" }); await refreshRuns(); } catch (error) { notify(error.message, "error"); }
  }));
}

function populateSettings() {
  for (const form of [$("#image-settings"), $("#automation-settings"), $("#evaluation-settings")]) {
    for (const element of form.elements) {
      if (element.name && Object.hasOwn(state.settings, element.name) && element.name !== "image.api_key") element.value = state.settings[element.name];
      if (element.name && ["automation.collection_recipe", "automation.link_collection_recipe", "automation.publish_recipe", "image.request_template"].includes(element.name)) element.value = JSON.stringify(state.settings[element.name] || (element.name === "image.request_template" ? {} : []), null, 2);
    }
  }
  $("#image-settings").elements["image.api_key"].placeholder = state.settings["image.has_api_key"] ? "已保存，留空则不修改" : "尚未配置";
}

function renderPreflight(data) {
  const checks = [
    ["正版Chrome", data.chromeInstalled], ["调试端口", data.cdpConnected], ["插件安装包", data.pluginPackageReady], ["妙手插件校准", data.pluginVerified], ["妙手登录校准", data.miaoshouLoginVerified],
  ];
  $("#preflight-list").innerHTML = checks.map(([label, ok]) => `<div><span>${esc(label)}</span><strong class="${ok ? "check-ok" : "check-warn"}">${ok ? "已通过" : "待处理"}</strong></div>`).join("");
}

function envBadge(ok, trueLabel = "正常", falseLabel = "待处理") {
  return `<strong class="${ok ? "check-ok" : "check-warn"}">${ok ? trueLabel : falseLabel}</strong>`;
}

async function refreshEnvironmentStatus(message = "") {
  const [localStatus, browserStatus, platformStatus] = await Promise.all([
    api("/api/local/status"), api("/api/browser/status"), api("/api/platform/status"),
  ]);
  state.localStatus = localStatus;
  state.workbenchToken = localStatus.token || state.workbenchToken;
  state.browserStatus = browserStatus;
  state.platformStatus = platformStatus;
  renderLocalStatus(localStatus);
  renderEnvironmentStatus(browserStatus, platformStatus, localStatus);
  if (message) notify(message, platformStatus.waiting_for_manual ? "error" : "success");
  return { localStatus, browserStatus, platformStatus };
}

function renderEnvironmentStatus(browser = state.browserStatus, platform = state.platformStatus, local = state.localStatus) {
  const grid = $("#environment-status-grid");
  if (!grid) return;
  const manual = platform.waiting_for_manual || platform.requires_manual;
  grid.innerHTML = `
    <article><span>Chrome</span>${envBadge(browser.chrome_ready, "可用", "未就绪")}</article>
    <article><span>CDP</span>${envBadge(browser.cdp_ready, "已连接", "未连接")}</article>
    <article><span>1688 登录</span>${envBadge(platform.alibaba_logged_in, "已登录", "待登录")}</article>
    <article><span>妙手登录</span>${envBadge(platform.miaoshou_logged_in, "已登录", "待登录")}</article>
    <article><span>人工验证</span>${envBadge(!manual, "无需处理", "等待人工")}</article>
    <article><span>no_publish</span>${envBadge(local.noPublish, "true", "false")}</article>
  `;
  $("#environment-detail").innerHTML = `
    <span>Profile：${esc(browser.profile_dir || "-")}</span>
    <span>端口：${Number(browser.debug_port || 0)}</span>
    <span>当前URL：${browser.current_url ? `<a href="${esc(browser.current_url)}" target="_blank" rel="noreferrer">${esc(browser.current_url)}</a>` : "-"}</span>
  `;
  const alert = $("#environment-alert");
  alert.classList.toggle("hidden", !manual);
  alert.textContent = platform.manual_message || "请在专用 Chrome 中手动完成登录或验证后重新检测。";
  const start = $("#browser-start");
  if (start) start.disabled = Boolean(browser.cdp_ready);
}

function renderSelfcheck(data) {
  const nextSteps = data.nextSteps || {};
  const manual = (nextSteps.manual || []).map((item) => `<div title="${esc(item.detail)}"><span>${esc(item.label)}</span><small>${esc(item.guidance)}</small><strong class="${item.status === "pass" ? "check-ok" : item.status === "fail" ? "run-error" : "check-warn"}">${item.status === "pass" ? "通过" : item.status === "fail" ? "失败" : "待配置"}</strong></div>`).join("");
  const automatic = (nextSteps.automatic || []).map((item) => `<div title="${esc(item.detail)}"><span>${esc(item.label)}</span><small>${esc(item.guidance)}</small><strong class="${item.status === "pass" ? "check-ok" : item.status === "fail" ? "run-error" : "check-warn"}">${item.status === "pass" ? "通过" : item.status === "fail" ? "失败" : "待配置"}</strong></div>`).join("");
  $("#selfcheck-list").innerHTML = `<div class="selfcheck-groups"><section><h3>可自动推进</h3>${automatic || '<p class="muted-line">暂无</p>'}</section><section><h3>需人工完成</h3>${manual || '<p class="muted-line">暂无</p>'}</section></div>`;
}

async function refreshRuns() {
  const data = await api("/api/runs");
  state.runs = data.items;
  renderRuns();
}

async function pollRuntime() {
  if (document.hidden) return;
  try {
    const [localStatus, browserStatus, platformStatus, dashboard, workflow, candidates, products, batches, runs, publishResults, imageJobs, imageSummary, collectionQueue] = await Promise.all([
      api("/api/local/status"), api("/api/browser/status"), api("/api/platform/status"), api("/api/dashboard"), api("/api/workflow/summary"), api("/api/candidates"), api("/api/products"), api("/api/batches"), api("/api/runs"), api("/api/publish/results"), api("/api/images/jobs"), api("/api/images/summary"), api(`/api/collections/queue?status=${encodeURIComponent(state.collectionQueueStatus)}`),
    ]);
    const selected = new Set(selectedCandidates());
    const selectedProducts = new Set($$("#batch-products input:checked").map((input) => input.value));
    const selectedShops = new Set($$("#batch-shops input:checked").map((input) => input.value));
    state.localStatus = localStatus;
    state.workbenchToken = localStatus.token || state.workbenchToken;
    state.browserStatus = browserStatus;
    state.platformStatus = platformStatus;
    state.workflow = workflow.steps || [];
    state.candidates = candidates.items;
    state.products = products.items;
    state.batches = batches.items;
    state.runs = runs.items;
    state.publishResults = publishResults;
    state.imageJobs = imageJobs.items;
    state.imageSummary = imageSummary;
    state.collectionQueue = collectionQueue;
    $("#metric-candidates").textContent = dashboard.candidates;
    $("#metric-qualified").textContent = dashboard.qualified;
    $("#metric-products").textContent = dashboard.products;
    $("#runtime-badge").innerHTML = `<i></i> ${localStatus.mode === "real" ? "真实模式" : "演练模式"}`;
    renderLocalStatus(localStatus);
    renderEnvironmentStatus(browserStatus, platformStatus, localStatus);
    renderWorkflow();
    renderQualifiedPool();
    renderCollectionQueue();
    renderCandidates();
    renderImageSummary();
    $$(".candidate-check").forEach((input) => { input.checked = selected.has(input.value); });
    renderProducts();
    renderBatchOptions();
    $$("#batch-products input").forEach((input) => { input.checked = selectedProducts.has(input.value); });
    $$("#batch-shops input").forEach((input) => { input.checked = selectedShops.has(input.value); });
    renderBatches();
    renderPublishResults();
    renderRuns();
  } catch (error) {
    console.warn("后台状态刷新失败", error);
  }
}

$$('.module-tab').forEach((button) => button.addEventListener("click", () => activateView(button.dataset.view)));
$$('.candidate-queue-tab').forEach((button) => button.addEventListener("click", () => {
  state.candidateQueue = button.dataset.candidateQueue;
  $("#select-all-candidates").checked = false;
  renderCandidates();
}));

$$('[data-close-dialog]').forEach((button) => button.addEventListener("click", () => button.closest("dialog").close()));
$$('[data-keyword]').forEach((button) => button.addEventListener("click", () => { $("#search-keyword").value = button.dataset.keyword; }));

$("#import-links").addEventListener("click", async () => {
  try {
    const result = await api("/api/candidates/import-links", { method: "POST", body: JSON.stringify({ urls: $("#candidate-links").value }) });
    $("#candidate-links").value = "";
    notify(`已导入 ${result.items.length} 个候选商品`);
    await loadAll();
  } catch (error) { notify(error.message, "error"); }
});

$("#create-search").addEventListener("click", async () => {
  try {
    const data = await api("/api/candidates/search", { method: "POST", body: JSON.stringify({ keyword: $("#search-keyword").value }) });
    $("#search-result").innerHTML = `已创建任务。<a href="${esc(data.searchUrl)}" target="_blank">打开1688搜索页</a>`;
    notify("关键词找品任务已创建");
    await refreshRuns();
  } catch (error) { notify(error.message, "error"); }
});

$("#select-all-candidates").addEventListener("change", (event) => $$(".candidate-check").forEach((input) => { input.checked = event.target.checked; }));

$("#bulk-check-candidates").addEventListener("click", async () => {
  const ids = selectedCandidates();
  try {
    const data = await api("/api/candidates/bulk-check", { method: "POST", body: JSON.stringify({ candidateIds: ids }) });
    notify(`已检查 ${data.checked} 个候选：${data.needData.length} 个待补，${data.readyToScore.length} 个可评分`);
    await loadAll();
  } catch (error) { notify(error.message, "error"); }
});

$("#refresh-selected").addEventListener("click", async () => {
  const ids = selectedCandidates();
  if (!ids.length) return notify("请先选择候选商品", "error");
  try {
    const data = await api("/api/candidates/refresh-sources", { method: "POST", body: JSON.stringify({ candidateIds: ids }) });
    const message = data.errors.length
      ? `已补全 ${data.items.length} 个，${data.errors.length} 个失败`
      : `已补全 ${data.items.length} 个候选`;
    notify(message, data.errors.length ? "error" : "success");
    await loadAll();
  } catch (error) { notify(error.message, "error"); }
});

$("#evaluate-selected").addEventListener("click", async () => {
  const ids = selectedCandidates();
  if (!ids.length) return notify("请先选择候选商品", "error");
  try {
    const data = await api("/api/candidates/evaluate", { method: "POST", body: JSON.stringify({ candidateIds: ids }) });
    const blocked = data.blocked?.length || 0;
    notify(blocked ? `评估完成 ${data.items.length} 个，拦截 ${blocked} 个缺数据候选` : "评估完成", blocked ? "error" : "success");
    await loadAll();
  } catch (error) {
    notify(error.blocked?.length ? `已拦截 ${error.blocked.length} 个缺数据候选` : error.message, "error");
    await loadAll();
  }
});

$("#skip-selected").addEventListener("click", async () => {
  const ids = selectedCandidates();
  if (!ids.length) return notify("请先选择候选商品", "error");
  try {
    const data = await api("/api/candidates/bulk-skip", { method: "POST", body: JSON.stringify({ candidateIds: ids }) });
    notify(`已标记跳过 ${data.items.length} 个候选`);
    await loadAll();
  } catch (error) { notify(error.message, "error"); }
});

$("#delete-invalid").addEventListener("click", async () => {
  const ids = selectedCandidates();
  if (!ids.length) return notify("请先选择候选商品", "error");
  try {
    const data = await api("/api/candidates/bulk-delete", { method: "POST", body: JSON.stringify({ candidateIds: ids }) });
    notify(`已删除 ${data.deleted.length} 个无效候选`);
    await loadAll();
  } catch (error) { notify(error.message, "error"); }
});

$("[data-refresh-source]").addEventListener("click", async () => {
  const id = $("#candidate-form").elements.id.value;
  if (!id) return;
  try {
    const item = await api(`/api/candidates/${id}/refresh-source`, { method: "POST", body: "{}" });
    state.currentCandidate = item;
    await loadAll();
    populateCandidateForm(item);
    notify("已从来源补全");
  } catch (error) { notify(error.message, "error"); }
});

$("#collect-qualified").addEventListener("click", async () => {
  try {
    const ids = selectedCandidates();
    const data = await api("/api/candidates/collect-qualified", { method: "POST", body: JSON.stringify({ candidateIds: ids }) });
    const blocked = data.blocked?.length || 0;
    notify(data.items.length ? `已创建 ${data.items.length} 个妙手采集任务${blocked ? `，拦截 ${blocked} 个缺数据候选` : ""}` : "没有符合自动采集条件的候选", data.items.length && !blocked ? "success" : "error");
    await loadAll();
  } catch (error) { notify(error.blocked?.length ? `已拦截 ${error.blocked.length} 个缺数据候选` : error.message, "error"); }
});

$("#collection-start").addEventListener("click", () => collectionBulkAction("start"));
$("#collection-retry").addEventListener("click", () => collectionBulkAction("retry_failed"));
$("#collection-skip").addEventListener("click", () => collectionBulkAction("skip"));
$("#collection-manual").addEventListener("click", () => collectionBulkAction("manual"));

$("#collection-detail-retry").addEventListener("click", async () => {
  const item = state.currentCollectionTask;
  if (!item) return;
  const payload = item.source === "candidate"
    ? { action: "start", candidateIds: [item.candidateId] }
    : { action: "retry_failed", runIds: [item.id] };
  try {
    await api("/api/collections/bulk-action", { method: "POST", body: JSON.stringify(payload) });
    $("#collection-detail-dialog").close();
    notify(item.source === "candidate" ? "采集任务已创建" : "采集任务已重新排队");
    await loadAll();
  } catch (error) {
    notify(error.message, "error");
  }
});

$("#collection-detail-skip").addEventListener("click", async () => {
  const item = state.currentCollectionTask;
  if (!item) return;
  const payload = item.source === "candidate"
    ? { action: "skip", candidateIds: [item.candidateId] }
    : { action: "skip", runIds: [item.id] };
  try {
    await api("/api/collections/bulk-action", { method: "POST", body: JSON.stringify(payload) });
    $("#collection-detail-dialog").close();
    notify("采集任务已跳过");
    await loadAll();
  } catch (error) {
    notify(error.message, "error");
  }
});

$("#select-qualified").addEventListener("click", () => {
  const qualifiedIds = new Set(state.candidates.filter((item) => item.canCollect).map((item) => item.id));
  $$(".candidate-check").forEach((input) => { input.checked = qualifiedIds.has(input.value); });
  notify(`已选中 ${qualifiedIds.size} 个达标候选`);
});

$("#collect-pool").addEventListener("click", async () => {
  const ids = selectedQualifiedCandidates().length ? selectedQualifiedCandidates() : state.candidates.filter((item) => item.canCollect).map((item) => item.id);
  if (!ids.length) return notify("当前没有可采集的达标候选", "error");
  try {
    const data = await api("/api/products/collect-qualified", { method: "POST", body: JSON.stringify({ candidateIds: ids }) });
    notify(data.items.length ? `已创建 ${data.items.length} 个采集任务` : "达标池暂时没有新任务", data.items.length ? "success" : "error");
    await loadAll();
  } catch (error) {
    notify(error.message, "error");
  }
});

$("#collect-selected-markets").addEventListener("click", async () => {
  const ids = selectedQualifiedCandidates();
  const markets = selectedQualifiedMarkets();
  if (!ids.length || !markets.length) return notify("请先勾选候选及国家", "error");
  try {
    const data = await api("/api/products/collect-qualified", { method: "POST", body: JSON.stringify({ candidateIds: ids, markets }) });
    notify(data.items.length ? `已按国家创建 ${data.items.length} 个采集任务` : "没有可采集的国家", data.items.length ? "success" : "error");
    await loadAll();
  } catch (error) {
    notify(error.message, "error");
  }
});

$("#review-qualified").addEventListener("click", async () => {
  const ids = selectedQualifiedCandidates();
  if (!ids.length) return notify("请先勾选候选", "error");
  try {
    const data = await api("/api/products/collect-qualified", { method: "POST", body: JSON.stringify({ candidateIds: ids, review: true }) });
    notify(data.blocked?.length ? `已转 ${data.blocked.length} 个候选人工复核` : "已转人工复核");
    await loadAll();
  } catch (error) {
    notify(error.message, "error");
  }
});

$("#skip-qualified").addEventListener("click", async () => {
  const ids = selectedQualifiedCandidates();
  if (!ids.length) return notify("请先勾选候选", "error");
  try {
    const data = await api("/api/candidates/bulk-skip", { method: "POST", body: JSON.stringify({ candidateIds: ids }) });
    notify(`已跳过 ${data.items.length} 个候选`);
    await loadAll();
  } catch (error) {
    notify(error.message, "error");
  }
});

$("#candidate-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const id = form.elements.id.value;
  const numeric = ["source_price", "weight_g", "monthly_sales", "repurchase_rate", "rating", "supplier_years", "dispatch_hours", "image_count"];
  const values = { title: form.elements.title.value, category: form.elements.category.value, sku_complete: form.elements.sku_complete.checked };
  numeric.forEach((name) => { values[name] = Number(form.elements[name].value || 0); });
  const marketData = {};
  Object.keys(markets).forEach((code) => {
    marketData[code] = {
      trend: Number(form.elements[`${code}-trend`].value || 0), salesSignal: Number(form.elements[`${code}-sales`].value || 0),
      competition: Number(form.elements[`${code}-competition`].value || 0), targetPriceCny: Number(form.elements[`${code}-price`].value || 0),
      dataComplete: form.elements[`${code}-complete`].checked,
    };
  });
  try {
    await api(`/api/candidates/${id}`, { method: "POST", body: JSON.stringify(values) });
    await api("/api/candidates/evaluate", { method: "POST", body: JSON.stringify({ candidateIds: [id], inputs: { [id]: { markets: marketData } } }) });
    $("#candidate-dialog").close();
    notify("供应数据已保存并完成五国评估");
    await loadAll();
  } catch (error) { notify(error.message, "error"); }
});

$("#create-demo-product").addEventListener("click", async () => {
  const candidate = state.candidates.find((item) => item.qualifiedMarkets?.length);
  if (!candidate) return notify("请先补齐数据并取得达标候选", "error");
  try {
    await api("/api/products", { method: "POST", body: JSON.stringify({ candidateId: candidate.id, sourceProductId: candidate.source_product_id, sourceUrl: candidate.source_url, title: candidate.title || `1688商品 ${candidate.source_product_id}`, category: candidate.category, sourcePrice: candidate.source_price, costPrice: candidate.source_price, weightG: candidate.weight_g, images: candidate.images, mainImage: candidate.images?.[0] || "", status: "待图片审核" }) });
    notify("演示商品已创建"); await loadAll();
  } catch (error) { notify(error.message, "error"); }
});

$("#generation-form").elements.preset.addEventListener("change", (event) => $("#custom-kinds").classList.toggle("hidden", event.target.value !== "custom"));
$("#generation-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const preset = form.elements.preset.value;
  const kinds = preset === "custom" ? $$("#custom-kinds input:checked").map((input) => input.value) : undefined;
  try {
    await api("/api/images/generate", { method: "POST", body: JSON.stringify({ productId: form.elements.productId.value, preset, kinds, extraPrompt: form.elements.extraPrompt.value }) });
    $("#image-dialog").close(); notify("生图任务已创建");
  } catch (error) { notify(error.message, "error"); }
});

$("#market-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const productId = event.currentTarget.elements.productId.value;
  try {
    for (const row of $$("[data-version-market]", event.currentTarget)) {
      const market = row.dataset.versionMarket;
      await api(`/api/products/${productId}/markets/${market}`, { method: "POST", body: JSON.stringify({ title: $("[name=title]", row).value, sale_price: Number($("[name=sale_price]", row).value || 0), warehouse: $("[name=warehouse]", row).value, inventory: Number($("[name=inventory]", row).value || 0), blocked: $("[name=blocked]", row).checked }) });
    }
    $("#market-dialog").close(); notify("五国资料已保存");
  } catch (error) { notify(error.message, "error"); }
});

$("#shop-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = Object.fromEntries(new FormData(event.currentTarget).entries());
  try { await api("/api/shops", { method: "POST", body: JSON.stringify(payload) }); event.currentTarget.reset(); notify("店铺已添加"); await loadAll(); } catch (error) { notify(error.message, "error"); }
});

$("#batch-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const productIds = $$("#batch-products input:checked").map((input) => input.value);
  const shopIds = $$("#batch-shops input:checked").map((input) => input.value);
  try {
    const response = await api("/api/batches/create", { method: "POST", body: JSON.stringify({ name: form.elements.name.value, productIds, shopIds, dryRun: form.elements.dryRun.checked }) });
    state.batchPreview = response.preflight || null;
    notify("铺货批次已创建"); await loadAll();
  } catch (error) {
    state.batchPreview = error.preflight || state.batchPreview;
    renderBatchPreview();
    notify(error.message, "error");
  }
});

$("#batch-confirm-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const batchId = form.elements.batchId.value;
  try {
    await api(`/api/batches/${batchId}/confirm`, { method: "POST", body: JSON.stringify({ confirmation: form.elements.confirmation.value, skipDryRun: !!$("#skip-dry-run")?.checked }) });
    $("#batch-confirm-dialog").close();
    notify("批次已强确认并进入执行");
    await loadAll();
  } catch (error) {
    notify(error.message, "error");
  }
});

for (const formId of ["image-settings", "automation-settings", "evaluation-settings"]) {
  $(`#${formId}`).addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(event.currentTarget).entries());
    for (const key of ["automation.collection_recipe", "automation.link_collection_recipe", "automation.publish_recipe", "image.request_template"]) {
      if (key in payload) {
        try { payload[key] = JSON.parse(payload[key] || "[]"); } catch { return notify(`${key} 不是有效JSON`, "error"); }
      }
    }
    ["image.timeout", "image.retries", "image.concurrency", "image.poll_interval", "automation.cdp_port", "evaluation.threshold", "evaluation.min_confidence", "evaluation.min_margin"].forEach((key) => { if (key in payload) payload[key] = Number(payload[key]); });
    Object.keys(payload).filter((key) => key.startsWith("market.")).forEach((key) => { payload[key] = Number(payload[key]); });
    try { await api("/api/settings", { method: "POST", body: JSON.stringify(payload) }); notify("设置已保存"); await loadAll(); } catch (error) { notify(error.message, "error"); }
  });
}

$("#check-automation").addEventListener("click", async () => { try { renderPreflight(await api("/api/automation/preflight")); } catch (error) { notify(error.message, "error"); } });
$("#launch-chrome").addEventListener("click", async () => { try { await api("/api/browser/start", { method: "POST", body: "{}" }); await refreshEnvironmentStatus("专用Chrome已启动，请在浏览器中完成登录状态确认"); renderPreflight(await api("/api/automation/preflight")); } catch (error) { notify(error.message, "error"); } });
$("#browser-start").addEventListener("click", async () => {
  const button = $("#browser-start");
  button.disabled = true;
  try {
    await api("/api/browser/start", { method: "POST", body: "{}" });
    await refreshEnvironmentStatus("专用Chrome已启动");
  } catch (error) {
    notify(error.message, "error");
  } finally {
    button.disabled = Boolean(state.browserStatus?.cdp_ready);
  }
});
$("#browser-check").addEventListener("click", async () => { try { await refreshEnvironmentStatus("环境检测完成"); } catch (error) { notify(error.message, "error"); } });
$("#browser-recheck").addEventListener("click", async () => { try { await refreshEnvironmentStatus("已重新检测登录与验证状态"); } catch (error) { notify(error.message, "error"); } });
$("#full-selfcheck").addEventListener("click", async () => {
  try {
    const result = await api("/api/selfcheck");
    renderSelfcheck(result);
    const unresolved = (result.checks || []).filter((item) => item.status !== "pass").length;
    $("#selfcheck-result").textContent = result.readyForLive ? "完整自检通过，可进入真实模式。" : `自检完成，仍有 ${unresolved} 项未通过。`;
    notify(result.readyForLive ? "完整自检通过，可进入真实模式" : "基础自检完成，真实模式仍有待配置项", result.ok ? "success" : "error");
  } catch (error) { notify(error.message, "error"); }
});
$("#repair-selfcheck").addEventListener("click", async () => {
  $("#repair-selfcheck").disabled = true;
  try {
    const result = await api("/api/selfcheck/repair", { method: "POST", body: JSON.stringify({ maxRefresh: 5 }) });
    renderSelfcheck(result.after);
    const unresolved = result.unresolved.map((item) => item.label).join("、") || "无";
    const actions = result.actions.join("；") || "没有可自动修复的项目";
    $("#selfcheck-result").textContent = `自动处理：${actions}。待人工处理：${unresolved}。`;
    notify(result.after.readyForLive ? "自检与自动修复已通过" : "自动修复完成，仍有待人工配置项", result.after.ok ? "success" : "error");
    await loadAll();
  } catch (error) {
    notify(error.message, "error");
  } finally {
    $("#repair-selfcheck").disabled = false;
  }
});
$("#preview-batch").addEventListener("click", refreshBatchPreview);
$("#refresh-runs").addEventListener("click", refreshRuns);

loadAll().then(() => window.setInterval(pollRuntime, 3000)).catch((error) => notify(error.message, "error"));
