#!/usr/bin/env node

import { writeFile } from "node:fs/promises";

const port = Number(process.argv[2] || 9222);
const output = process.argv[3] || "";
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

async function main() {
  if (!output) throw new Error("Missing output path");
  const targets = await (await fetch(`${base}/json/list`)).json();
  const target = targets.find((item) => item.type === "page" && item.webSocketDebuggerUrl);
  if (!target) throw new Error("No debuggable page found");
  const client = new CDP(target.webSocketDebuggerUrl);
  await client.open();
  try {
    await client.send("Page.enable");
    const result = await client.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
    await writeFile(output, Buffer.from(result.data || "", "base64"));
    console.log(JSON.stringify({ ok: true, path: output }));
  } finally {
    client.close();
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
