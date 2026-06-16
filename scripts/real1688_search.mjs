#!/usr/bin/env node

const input = JSON.parse(process.argv[2] || "{}");
const port = Number(input.port || 9222);
const base = `http://127.0.0.1:${port}`;

class CDP {
  constructor(url) {
    this.ws = new WebSocket(url);
    this.id = 1;
    this.pending = new Map();
  }

  async open() {
    await new Promise((resolve, reject) => {
      this.ws.addEventListener("open", resolve, { once: true });
      this.ws.addEventListener("error", reject, { once: true });
    });
    this.ws.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (!message.id || !this.pending.has(message.id)) return;
      const callbacks = this.pending.get(message.id);
      this.pending.delete(message.id);
      if (message.error) callbacks.reject(new Error(message.error.message));
      else callbacks.resolve(message.result || {});
    });
  }

  send(method, params = {}) {
    const id = this.id++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  close() {
    this.ws.close();
  }
}

async function targetFor(url) {
  const targets = await (await fetch(`${base}/json/list`)).json();
  const existing = targets.find((item) => item.type === "page" && item.webSocketDebuggerUrl && String(item.url || "").includes("1688.com"));
  if (existing) return existing;
  const created = await fetch(`${base}/json/new?${encodeURIComponent(url || "https://www.1688.com/")}`, { method: "PUT" });
  if (!created.ok) throw new Error("无法创建 1688 搜索页面");
  return created.json();
}

async function evaluate(cdp, expression, awaitPromise = false) {
  const result = await cdp.send("Runtime.evaluate", {
    expression,
    awaitPromise,
    returnByValue: true,
    userGesture: true,
  });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || "页面脚本执行失败");
  return result.result?.value;
}

async function navigate(cdp, url) {
  const loaded = new Promise((resolve) => {
    const timer = setTimeout(resolve, 20000);
    const onMessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.method === "Page.loadEventFired") {
        clearTimeout(timer);
        cdp.ws.removeEventListener("message", onMessage);
        resolve();
      }
    };
    cdp.ws.addEventListener("message", onMessage);
  });
  await cdp.send("Page.navigate", { url });
  await loaded;
}

function extractionExpression(input) {
  return `(() => {
    const keyword = ${JSON.stringify(input.keyword || "")};
    const page = Number(${JSON.stringify(input.page || 1)});
    const limit = Math.max(1, Number(${JSON.stringify(input.limit || 10)}));
    const text = document.body && document.body.innerText || "";
    const lowerUrl = location.href.toLowerCase();
    const verificationMarkers = ["验证码", "短信验证", "人机验证", "滑块", "安全验证", "captcha", "verify", "security check"];
    const loginMarkers = ["请登录", "立即登录", "登录后更多精彩", "账号登录"];
    const verificationRequired = verificationMarkers.some((item) => text.toLowerCase().includes(item.toLowerCase()) || lowerUrl.includes(item.toLowerCase()));
    const loginRequired = !verificationRequired && loginMarkers.some((item) => text.includes(item));
    const offerId = (url) => {
      const value = String(url || "");
      for (const pattern of [/offer\\/(\\d+)/, /offerId=(\\d+)/, /[?&]id=(\\d+)/]) {
        const match = value.match(pattern);
        if (match) return match[1];
      }
      return "";
    };
    const absolute = (url) => {
      try { return new URL(url, location.href).href; } catch { return ""; }
    };
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const parsePrice = (value) => {
      const normalized = clean(value).replace(/¥\\s*(\\d+)\\s*\\.\\s*(\\d+)/g, "¥ $1.$2");
      const match = normalized.match(/(?:¥|￥)?\\s*(\\d+(?:\\.\\d+)?)/);
      return match ? Number(match[1]) : 0;
    };
    const parseMinOrder = (value) => {
      const match = clean(value).match(/(\\d+)\\s*(?:件|双|个|套)?\\s*起(?:批|订|购)/);
      return match ? Number(match[1]) : 0;
    };
    const parseMonthlySales = (value) => {
      const normalized = clean(value);
      const matches = Array.from(normalized.matchAll(/(?:已售|成交|销量|全网)?\\s*(\\d+(?:\\.\\d+)?)\\s*(万)?\\+?\\s*(?:件|单|笔)?/g));
      for (const match of matches) {
        const around = normalized.slice(Math.max(0, match.index - 12), Math.min(normalized.length, match.index + match[0].length + 12));
        if (/起批|起订|起购/.test(around)) continue;
        if (/已售|成交|销量|全网/.test(around)) return Math.round(Number(match[1]) * (match[2] ? 10000 : 1));
      }
      return 0;
    };
    const salesText = (value) => {
      const match = clean(value).match(/((?:已售|成交|销量|全网)[^\\s]{0,18})/);
      return match ? match[1] : "";
    };
    const inferCategory = (title) => {
      if (/凉鞋/.test(title)) return "凉鞋";
      if (/防滑鞋/.test(title)) return "防滑鞋";
      if (/透气鞋/.test(title)) return "透气鞋";
      if (/运动鞋|跑步鞋|鞋/.test(title)) return "运动鞋";
      if (/包/.test(title)) return "运动包";
      if (/套装/.test(title)) return "运动套装";
      return "";
    };
    const titleFrom = (card, anchor) => {
      const candidates = [
        anchor.getAttribute("title"),
        anchor.getAttribute("aria-label"),
        anchor.innerText,
        card.querySelector("[title]")?.getAttribute("title"),
        card.querySelector(".title, .offer-title, .search-offer-title")?.innerText,
      ];
      for (const item of candidates) {
        const lines = String(item || "").split("\\n").map(clean).filter(Boolean);
        for (const line of lines) {
          if (line.length >= 6 && /[\\u4e00-\\u9fa5A-Za-z]/.test(line) && !/^(¥|￥|\\d+|已售|成交|起批|起订)/.test(line)) return line.slice(0, 300);
        }
      }
      return "";
    };
    const cardFor = (anchor) => {
      let node = anchor;
      for (let depth = 0; node && depth < 8; depth += 1, node = node.parentElement) {
        const text = clean(node.innerText || "");
        const links = node.querySelectorAll ? node.querySelectorAll("a[href]").length : 0;
        const images = node.querySelectorAll ? node.querySelectorAll("img").length : 0;
        if (text.length > 20 && text.length < 1800 && links >= 1 && images >= 1 && /¥|￥|起批|起订|已售|成交/.test(text)) return node;
      }
      return anchor.closest(".search-offer-wrapper, .offer, .item, li, div") || anchor;
    };
    const anchors = Array.from(document.querySelectorAll("a[href]")).filter((anchor) => offerId(anchor.href));
    const seen = new Set();
    const items = [];
    for (const anchor of anchors) {
      const id = offerId(anchor.href);
      if (!id || seen.has(id)) continue;
      const card = cardFor(anchor);
      const cardText = clean(card.innerText || anchor.innerText || "");
      const title = titleFrom(card, anchor);
      const img = card.querySelector("img[src], img[data-src], img[data-lazy-src]");
      const image = img ? absolute(img.currentSrc || img.src || img.getAttribute("data-src") || img.getAttribute("data-lazy-src")) : "";
      if (!title || !image) continue;
      const supplierAnchor = Array.from(card.querySelectorAll("a[href]")).find((link) => /shop|company|page/.test(link.href) && !offerId(link.href));
      const supplierName = clean(supplierAnchor?.innerText || card.querySelector(".company, .supplier, .shop-name")?.innerText || "");
      seen.add(id);
      items.push({
        title,
        url: "https://detail.1688.com/offer/" + id + ".html",
        offer_id: id,
        main_image_url: image,
        price: parsePrice(cardText),
        min_order: parseMinOrder(cardText),
        sales_text: salesText(cardText),
        monthly_sales: parseMonthlySales(cardText),
        supplier_name: supplierName,
        shop_url: supplierAnchor ? absolute(supplierAnchor.href) : "",
        origin_place: clean((cardText.match(/(?:发货地|产地)[:：]?\\s*([^\\s]+(?:\\s*[^\\s]+)?)/) || [])[1] || ""),
        category: inferCategory(title),
        keyword,
        search_page: page,
        search_rank: items.length + 1,
      });
      if (items.length >= limit) break;
    }
    return {
      ok: true,
      url: location.href,
      title: document.title,
      verification_required: verificationRequired,
      login_required: loginRequired,
      error: verificationRequired ? "1688 出现验证码/人机/短信验证" : loginRequired ? "1688 需要登录" : "",
      items,
    };
  })()`;
}

async function main() {
  const target = await targetFor(input.url);
  const cdp = new CDP(target.webSocketDebuggerUrl);
  await cdp.open();
  try {
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await navigate(cdp, input.url);
    await new Promise((resolve) => setTimeout(resolve, 2500));
    await evaluate(cdp, "window.scrollTo(0, Math.max(600, Math.floor(document.body.scrollHeight * 0.35)))");
    await new Promise((resolve) => setTimeout(resolve, 1200));
    const result = await evaluate(cdp, extractionExpression(input));
    console.log(JSON.stringify(result));
  } finally {
    cdp.close();
  }
}

main().catch((error) => {
  console.log(JSON.stringify({ ok: false, error: error.message, items: [] }));
  process.exitCode = 1;
});
