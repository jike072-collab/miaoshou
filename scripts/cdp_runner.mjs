#!/usr/bin/env node

const input = JSON.parse(process.argv[2] || "{}");
const port = Number(input.port || 9222);
const base = `http://127.0.0.1:${port}`;

class CDP {
  constructor(url) {
    this.ws = new WebSocket(url);
    this.nextId = 1;
    this.pending = new Map();
    this.listeners = new Map();
  }
  async open() {
    await new Promise((resolve, reject) => {
      this.ws.addEventListener("open", resolve, { once: true });
      this.ws.addEventListener("error", reject, { once: true });
    });
    this.ws.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.id && this.pending.has(message.id)) {
        const { resolve, reject } = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (message.error) reject(new Error(message.error.message)); else resolve(message.result || {});
      } else if (message.method) {
        for (const listener of this.listeners.get(message.method) || []) listener(message.params || {});
      }
    });
  }
  send(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  once(method, timeout = 30000) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`等待 ${method} 超时`)), timeout);
      const callback = (params) => {
        clearTimeout(timer);
        const list = this.listeners.get(method) || [];
        this.listeners.set(method, list.filter((item) => item !== callback));
        resolve(params);
      };
      this.listeners.set(method, [...(this.listeners.get(method) || []), callback]);
    });
  }
  on(method, callback) {
    this.listeners.set(method, [...(this.listeners.get(method) || []), callback]);
  }
  close() { this.ws.close(); }
}

async function targetFor(url) {
  const targets = await (await fetch(`${base}/json/list`)).json();
  const page = targets.find((item) => item.type === "page" && item.webSocketDebuggerUrl);
  if (page) return page;
  const created = await fetch(`${base}/json/new?${encodeURIComponent(url || "about:blank")}`, { method: "PUT" });
  if (!created.ok) throw new Error("无法创建Chrome页面");
  return created.json();
}

const deepHelpers = `
function allDeep(root=document) {
  const found=[]; const visit=(node)=>{ if(!node||!node.querySelectorAll)return; for(const el of node.querySelectorAll('*')){found.push(el);if(el.shadowRoot)visit(el.shadowRoot);} }; visit(root); return found;
}
function visible(el){const s=getComputedStyle(el);const r=el.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.height>0;}
function byTexts(texts){return allDeep().find(el=>visible(el)&&texts.some(t=>(el.innerText||el.textContent||'').trim()===t)) || allDeep().find(el=>visible(el)&&texts.some(t=>(el.innerText||el.textContent||'').includes(t)));}
`;

function interpolate(value, variables) {
  if (typeof value !== "string") return value;
  return value.replace(/\{\{([^}]+)\}\}/g, (_, key) => String(variables[key.trim()] ?? ""));
}

function extractOfferId(url) {
  const text = String(url || "");
  for (const pattern of [/offer\/(\d+)/, /offerId=(\d+)/, /[?&]id=(\d+)/]) {
    const match = text.match(pattern);
    if (match) return match[1];
  }
  return "";
}

async function evaluate(cdp, expression, awaitPromise = false, contextId = undefined) {
  const params = { expression, awaitPromise, returnByValue: true, userGesture: true };
  if (contextId) params.contextId = contextId;
  const result = await cdp.send("Runtime.evaluate", params);
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || "页面脚本执行失败");
  return result.result?.value;
}

async function evaluateAll(cdp, contexts, expression) {
  const ids = [...contexts];
  if (!ids.length) return [await evaluate(cdp, expression).catch(() => undefined)];
  const values = [];
  for (const id of ids) values.push(await evaluate(cdp, expression, false, id).catch(() => undefined));
  return values;
}

async function navigate(cdp, url) {
  const loaded = cdp.once("Page.loadEventFired", 30000).catch(() => null);
  await cdp.send("Page.navigate", { url });
  await loaded;
}

async function waitForText(cdp, contexts, texts, timeout = 30000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const values = await evaluateAll(cdp, contexts, `${deepHelpers}; Boolean(byTexts(${JSON.stringify(texts)}))`);
    if (values.some(Boolean)) return true;
    await new Promise((resolve) => setTimeout(resolve, 800));
  }
  throw new Error(`未找到页面文字：${texts.join(" / ")}`);
}

async function clickText(cdp, contexts, texts) {
  const expression = `${deepHelpers}; (()=>{const el=byTexts(${JSON.stringify(texts)});if(!el)return false;el.scrollIntoView({block:'center'});el.click();return true;})()`;
  for (const id of [...contexts]) if (await evaluate(cdp, expression, false, id).catch(() => false)) return;
  if (await evaluate(cdp, expression).catch(() => false)) return;
  throw new Error(`未找到可点击文字：${texts.join(" / ")}`);
}

async function executeAction(cdp, contexts, action, variables) {
  const type = action.type;
  if (type === "navigate") return navigate(cdp, interpolate(action.url, variables));
  if (type === "clickText") return clickText(cdp, contexts, (action.texts || [action.text]).map((item) => interpolate(item, variables)));
  if (type === "waitText" || type === "assertText") return waitForText(cdp, contexts, (action.texts || [action.text]).map((item) => interpolate(item, variables)), Number(action.timeout || 30000));
  if (type === "sleep") return new Promise((resolve) => setTimeout(resolve, Math.min(Number(action.ms || 500), 5000)));
  if (type === "fill") {
    const selector = JSON.stringify(action.selector);
    const value = JSON.stringify(interpolate(action.value, variables));
    const expression = `(()=>{const el=document.querySelector(${selector});if(!el)return false;el.focus();el.value=${value};el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));return true;})()`;
    const values = await evaluateAll(cdp, contexts, expression);
    if (!values.some(Boolean)) throw new Error(`输入控件不存在：${action.selector}`);
    return;
  }
  if (type === "select") {
    const selector = JSON.stringify(action.selector);
    const value = JSON.stringify(interpolate(action.value, variables));
    const values = await evaluateAll(cdp, contexts, `(()=>{const el=document.querySelector(${selector});if(!el)return false;el.value=${value};el.dispatchEvent(new Event('change',{bubbles:true}));return el.value===${value};})()`);
    if (!values.some(Boolean)) throw new Error(`下拉选项设置失败：${action.selector}`);
    return;
  }
  if (type === "upload") {
    const documentNode = await cdp.send("DOM.getDocument", { depth: 1, pierce: true });
    const selected = await cdp.send("DOM.querySelector", { nodeId: documentNode.root.nodeId, selector: action.selector });
    if (!selected.nodeId) throw new Error(`文件控件不存在：${action.selector}`);
    const files = (action.files || [action.value]).map((item) => interpolate(item, variables)).filter(Boolean);
    await cdp.send("DOM.setFileInputFiles", { nodeId: selected.nodeId, files });
    return;
  }
  throw new Error(`不支持的动作类型：${type}`);
}

async function runRecipe(cdp, contexts, recipe, variables, events) {
  for (const action of recipe || []) {
    const label = action.label || action.type;
    events.push({ label, status: "running" });
    await executeAction(cdp, contexts, action, variables);
    events[events.length - 1].status = "completed";
  }
}

async function main() {
  const events = [];
  const target = await targetFor(input.url || input.miaoshouUrl);
  const cdp = new CDP(target.webSocketDebuggerUrl);
  await cdp.open();
  const contexts = new Set();
  cdp.on("Runtime.executionContextCreated", ({ context }) => contexts.add(context.id));
  cdp.on("Runtime.executionContextDestroyed", ({ executionContextId }) => contexts.delete(executionContextId));
  cdp.on("Runtime.executionContextsCleared", () => contexts.clear());
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  try {
    if (input.kind === "keyword_search") {
      events.push({ label: "打开1688搜索页", status: "running" });
      await navigate(cdp, input.url);
      await new Promise((resolve) => setTimeout(resolve, 2500));
      events[events.length - 1].status = "completed";
      events.push({ label: "读取商品卡片", status: "running" });
      const expression = `(()=> {
        const offerId = (url) => {
          const text = String(url || '');
          for (const pattern of [/offer\\/(\\d+)/, /offerId=(\\d+)/, /[?&]id=(\\d+)/]) {
            const match = text.match(pattern);
            if (match) return match[1];
          }
          return '';
        };
        const cleanTitle = (text) => String(text || '').split('\\n').map((item) => item.trim()).filter(Boolean).find((line) => {
          if (line.length < 6) return false;
          if (/^(¥|新人价|首单减|全网|\\d+件起购|退货包运费|先采后付|点此)/.test(line)) return false;
          return /[\\u4e00-\\u9fa5A-Za-z]/.test(line);
        }) || '';
        return Array.from(document.querySelectorAll('a[href]')).slice(0,1000).map((a) => {
          const id = offerId(a.href);
          if (!id) return null;
          const card = a.closest('.search-offer-wrapper');
          if (!card) return null;
          const img = card.querySelector('img');
          const title = cleanTitle(card.innerText || a.innerText || a.getAttribute('title')).slice(0,300);
          const image = img ? (img.currentSrc || img.src || '') : '';
          if (!title || !image) return null;
          return {
            url: 'https://detail.1688.com/offer/' + id + '.html',
            title,
            image
          };
        }).filter(Boolean);
      })()`;
      const groups = await evaluateAll(cdp, contexts, expression);
      const map = new Map();
      for (const group of groups) {
        for (const item of Array.isArray(group) ? group : []) {
          const id = extractOfferId(item.url);
          if (id && !map.has(id)) map.set(id, item);
        }
      }
      events[events.length - 1].status = "completed";
      events.push({ label: "写入待评估候选池", status: "completed" });
      console.log(JSON.stringify({ ok: true, events, candidates: [...map.values()] }));
      return;
    } else if (input.kind === "collection") {
      events.push({ label: "打开1688商品页", status: "running" });
      await navigate(cdp, input.url);
      await new Promise((resolve) => setTimeout(resolve, 500));
      events[events.length - 1].status = "completed";
      if (input.productId) {
        const current = await evaluate(cdp, "location.href");
        if (!String(current).includes(input.productId)) throw new Error("1688商品ID与候选记录不一致");
      }
      events.push({ label: "调用妙手插件采集", status: "running" });
      await clickText(cdp, contexts, input.collectTexts || ["采集此产品", "妙手采集"]);
      events[events.length - 1].status = "completed";
      events.push({ label: "核对插件成功提示", status: "running" });
      await waitForText(cdp, contexts, input.successTexts || ["采集成功", "已采集"], 30000);
      events[events.length - 1].status = "completed";
      await runRecipe(cdp, contexts, input.recipe, input.variables || {}, events);
    } else {
      const phase = input.phase || "prepare";
      const actions = (input.recipe || []).filter((item) => (item.phase || "prepare") === phase);
      const batchActions = actions.filter((item) => (item.scope || "job") === "batch");
      const jobActions = actions.filter((item) => (item.scope || "job") === "job");
      await runRecipe(cdp, contexts, batchActions, input.variables || {}, events);
      for (const job of input.jobs || [{}]) await runRecipe(cdp, contexts, jobActions, { ...(input.variables || {}), ...job }, events);
    }
    console.log(JSON.stringify({ ok: true, events }));
  } finally {
    cdp.close();
  }
}

main().catch((error) => {
  console.log(JSON.stringify({ ok: false, error: error.message }));
  process.exitCode = 1;
});
