const state = { candidates: [], products: [], shops: [], batches: [], runs: [], imageJobs: [], settings: {}, currentCandidate: null };
const markets = { MY: "马来西亚", PH: "菲律宾", SG: "新加坡", TH: "泰国", VN: "越南" };
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
  const response = await fetch(url, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `请求失败（${response.status}）`);
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

async function loadAll() {
  const [dashboard, candidates, products, shops, batches, runs, imageJobs, settings, selfcheck] = await Promise.all([
    api("/api/dashboard"), api("/api/candidates"), api("/api/products"), api("/api/shops"), api("/api/batches"), api("/api/runs"), api("/api/images/jobs"), api("/api/settings"), api("/api/selfcheck"),
  ]);
  state.candidates = candidates.items;
  state.products = products.items;
  state.shops = shops.items;
  state.batches = batches.items;
  state.runs = runs.items;
  state.imageJobs = imageJobs.items;
  state.settings = settings;
  $("#metric-candidates").textContent = dashboard.candidates;
  $("#metric-qualified").textContent = dashboard.qualified;
  $("#metric-products").textContent = dashboard.products;
  $("#runtime-badge").innerHTML = `<i></i> ${settings["automation.mode"] === "live" ? "真实模式" : "演练模式"}`;
  renderCandidates();
  renderProducts();
  renderShops();
  renderBatchOptions();
  renderBatches();
  renderRuns();
  populateSettings();
  renderPreflight(dashboard.preflight);
  renderSelfcheck(selfcheck);
}

function renderCandidates() {
  const body = $("#candidate-table");
  body.innerHTML = "";
  $("#candidate-empty").classList.toggle("hidden", state.candidates.length > 0);
  for (const item of state.candidates) {
    const tr = document.createElement("tr");
    const scores = Object.keys(markets).map((market) => {
      const evaluation = getEvaluation(item, market);
      if (!evaluation) return '<td><span class="score-pill empty-score">--</span></td>';
      const blocked = evaluation.hard_blocks?.length ? "!" : "";
      return `<td><span class="score-pill ${scoreClass(evaluation.total_score)}" title="置信度 ${evaluation.confidence}%${evaluation.hard_blocks?.length ? `；${esc(evaluation.hard_blocks.join("、"))}` : ""}">${evaluation.total_score}${blocked}</span></td>`;
    }).join("");
    tr.innerHTML = `
      <td><input class="candidate-check" type="checkbox" value="${esc(item.id)}"></td>
      <td><div class="candidate-name"><strong>${esc(item.title || `1688商品 ${item.source_product_id || "待识别"}`)}</strong><a href="${esc(item.source_url)}" target="_blank" rel="noreferrer">${esc(item.source_product_id || "查看来源")}</a></div></td>
      <td><span>${esc(item.category || "待补充")}</span><small>¥${Number(item.source_price || 0).toFixed(2)} · ${Number(item.weight_g || 0)}g</small></td>
      ${scores}
      <td><span class="status-chip status-${esc(item.status)}">${esc(item.status)}</span></td>
      <td><button class="table-action" data-edit-candidate="${esc(item.id)}" type="button">补数据</button></td>`;
    body.appendChild(tr);
  }
  $$('[data-edit-candidate]').forEach((button) => button.addEventListener("click", () => openCandidate(button.dataset.editCandidate)));
}

function selectedCandidates() {
  return $$(".candidate-check:checked").map((input) => input.value);
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

function renderProducts() {
  const wrap = $("#product-cards");
  wrap.innerHTML = "";
  $("#product-empty").classList.toggle("hidden", state.products.length > 0);
  for (const product of state.products) {
    const card = document.createElement("article");
    card.className = "product-studio-card";
    const image = product.mainImage ? (product.mainImage.startsWith("/assets/") ? product.mainImage : `/api/image?url=${encodeURIComponent(product.mainImage)}`) : "";
    const imageJob = state.imageJobs.find((job) => job.product_id === product.id);
    card.innerHTML = `
      <div class="studio-image">${image ? `<img src="${esc(image)}" alt="">` : "<span>NO IMAGE</span>"}</div>
      <div class="studio-body"><span class="status-chip">${esc(product.status)}</span>${imageJob ? `<span class="status-chip">生图：${esc(imageJob.status)} ${imageJob.completed_count}/${imageJob.requested_count}</span>` : ""}<h3>${esc(product.title || "未命名商品")}</h3><p>${esc(product.category || "待分类")} · ${Number(product.weightG || 0)}g</p>
      <div class="studio-actions"><button class="button outline small" data-localize="${product.id}" type="button">AI本地化</button><button class="button outline small" data-market="${product.id}" type="button">五国资料</button><button class="button outline small" data-generate="${product.id}" type="button">AI生图</button><label class="button outline small upload-button">上传图片<input data-upload="${product.id}" type="file" accept="image/png,image/jpeg,image/webp"></label><button class="button dark small" data-assets="${product.id}" type="button">图片审核</button></div></div>`;
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
  $("#batch-products").innerHTML = state.products.map((product) => `<label><input type="checkbox" value="${product.id}">${esc(product.title || "未命名商品")}</label>`).join("") || "暂无商品";
  $("#batch-shops").innerHTML = state.shops.map((shop) => `<label><input type="checkbox" value="${shop.id}">${esc(shop.shop_name)} · ${esc(shop.market)}</label>`).join("") || "暂无店铺";
}

function renderBatches() {
  $("#batch-list").innerHTML = state.batches.map((batch) => `<div class="run-row"><div><strong>${esc(batch.name)}</strong><span>${batch.summary.products || 0}款 · ${batch.summary.shops || 0}店 · ${batch.dry_run ? "演练" : "真实"}</span></div><div class="run-progress"><span style="width:${batch.status === "draft" ? 15 : batch.status === "preparing" ? 70 : 100}%"></span></div><span class="status-chip">${esc(batch.status)}</span>${batch.status === "draft" ? `<button class="table-action" data-prepare-batch="${batch.id}" type="button">准备</button>` : ""}${batch.status === "preparing" || batch.status === "confirmed" ? `<button class="table-action" data-confirm-batch="${batch.id}" type="button">确认</button>` : ""}</div>`).join("") || '<div class="table-empty">暂无铺货批次。</div>';
  $$('[data-prepare-batch]').forEach((button) => button.addEventListener("click", async () => {
    try { await api(`/api/batches/${button.dataset.prepareBatch}/prepare`, { method: "POST", body: "{}" }); notify("批次准备完成，等待确认"); await loadAll(); } catch (error) { notify(error.message, "error"); }
  }));
  $$('[data-confirm-batch]').forEach((button) => button.addEventListener("click", async () => {
    const batch = state.batches.find((item) => item.id === button.dataset.confirmBatch);
    if (!window.confirm(`确认执行批次“${batch?.name || ""}”？演练批次不会点击妙手最终发布。`)) return;
    try { await api(`/api/batches/${button.dataset.confirmBatch}/confirm`, { method: "POST", body: "{}" }); notify("批次已确认并执行"); await loadAll(); } catch (error) { notify(error.message, "error"); }
  }));
}

function renderRuns() {
  const wrap = $("#run-list");
  wrap.innerHTML = state.runs.map((run) => {
    const steps = Array.isArray(run.steps) ? run.steps : [];
    const completed = steps.filter((step) => typeof step === "object" && step.status === "completed").length;
    return `<div class="run-row"><div><strong>${run.kind === "collection" ? "妙手采集" : run.kind === "publish" ? "铺货批次" : "关键词找品"}</strong><span>${esc(run.current_step || "等待执行")}</span></div><div class="run-progress"><span style="width:${steps.length ? completed / steps.length * 100 : 0}%"></span></div><span class="status-chip">${esc(run.status)}</span>${run.error ? `<small class="run-error">${esc(run.error)}</small>` : ""}${["failed", "blocked", "waiting_browser"].includes(run.status) ? `<button class="table-action" data-retry="${run.id}" type="button">重试</button>` : ""}</div>`;
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
    const [dashboard, candidates, products, batches, runs, imageJobs] = await Promise.all([
      api("/api/dashboard"), api("/api/candidates"), api("/api/products"), api("/api/batches"), api("/api/runs"), api("/api/images/jobs"),
    ]);
    const selected = new Set(selectedCandidates());
    const selectedProducts = new Set($$("#batch-products input:checked").map((input) => input.value));
    const selectedShops = new Set($$("#batch-shops input:checked").map((input) => input.value));
    state.candidates = candidates.items;
    state.products = products.items;
    state.batches = batches.items;
    state.runs = runs.items;
    state.imageJobs = imageJobs.items;
    $("#metric-candidates").textContent = dashboard.candidates;
    $("#metric-qualified").textContent = dashboard.qualified;
    $("#metric-products").textContent = dashboard.products;
    renderCandidates();
    $$(".candidate-check").forEach((input) => { input.checked = selected.has(input.value); });
    renderProducts();
    renderBatchOptions();
    $$("#batch-products input").forEach((input) => { input.checked = selectedProducts.has(input.value); });
    $$("#batch-shops input").forEach((input) => { input.checked = selectedShops.has(input.value); });
    renderBatches();
    renderRuns();
  } catch (error) {
    console.warn("后台状态刷新失败", error);
  }
}

$$('.module-tab').forEach((button) => button.addEventListener("click", () => {
  $$('.module-tab').forEach((item) => item.classList.toggle("active", item === button));
  $$('.module-view').forEach((view) => view.classList.add("hidden"));
  $(`#view-${button.dataset.view}`).classList.remove("hidden");
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
  try { await api("/api/candidates/evaluate", { method: "POST", body: JSON.stringify({ candidateIds: ids }) }); notify("评估完成"); await loadAll(); } catch (error) { notify(error.message, "error"); }
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
    notify(data.items.length ? `已创建 ${data.items.length} 个妙手采集任务` : "没有符合自动采集条件的候选", data.items.length ? "success" : "error");
    await loadAll();
  } catch (error) { notify(error.message, "error"); }
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
    await api("/api/batches", { method: "POST", body: JSON.stringify({ name: form.elements.name.value, productIds, shopIds, dryRun: form.elements.dryRun.checked }) });
    notify("铺货批次已创建"); await loadAll();
  } catch (error) { notify(error.message, "error"); }
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
$("#launch-chrome").addEventListener("click", async () => { try { renderPreflight(await api("/api/automation/launch", { method: "POST", body: "{}" })); notify("专用Chrome已启动，请完成妙手和1688登录"); } catch (error) { notify(error.message, "error"); } });
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
$("#refresh-runs").addEventListener("click", refreshRuns);

loadAll().then(() => window.setInterval(pollRuntime, 3000)).catch((error) => notify(error.message, "error"));
