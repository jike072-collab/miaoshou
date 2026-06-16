#!/usr/bin/env node

const port = Number(process.argv[2] || 9222);
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

async function inspectPage(target) {
  const client = new CDP(target.webSocketDebuggerUrl);
  await client.open();
  await client.send("Runtime.enable");
  try {
    const result = await client.send("Runtime.evaluate", {
      expression: `({
        title: document.title,
        url: location.href,
        text: (document.body && document.body.innerText || "").slice(0, 8000)
      })`,
      returnByValue: true,
    });
    return result.result.value;
  } finally {
    client.close();
  }
}

async function main() {
  const version = await (await fetch(`${base}/json/version`)).json();
  const targets = await (await fetch(`${base}/json/list`)).json();
  const pages = [];
  for (const target of targets) {
    if (target.type !== "page" || !target.webSocketDebuggerUrl) continue;
    try {
      pages.push(await inspectPage(target));
    } catch (error) {
      pages.push({ title: target.title || "", url: target.url || "", error: error.message });
    }
  }
  console.log(JSON.stringify({
    browser: version.Browser || "",
    targets: targets.map((target) => ({ type: target.type, title: target.title || "", url: target.url || "" })),
    pages,
  }));
}

main().catch((error) => {
  console.log(JSON.stringify({ error: error.message, targets: [], pages: [] }));
  process.exitCode = 1;
});
