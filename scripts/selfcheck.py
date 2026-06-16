#!/usr/bin/env python3
"""Run an isolated end-to-end API check without touching production data."""

import base64
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener, urlopen


ROOT = Path(__file__).resolve().parent.parent
PNG_BYTES = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")


class RelayHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        body = json.dumps({"data": [{"b64_json": base64.b64encode(PNG_BYTES).decode()}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        pass


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(base, method, path, payload=None, expected=200, extra_headers=None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    headers.update(extra_headers or {})
    opener = build_opener(ProxyHandler({})) if base.startswith("http://127.0.0.1") or base.startswith("http://localhost") else None
    try:
        req = Request(base + path, data=data, headers=headers, method=method)
        response = (opener.open(req, timeout=10) if opener else urlopen(req, timeout=10))
        status, body = response.status, response.read()
        content_type = response.headers.get_content_type()
    except HTTPError as exc:
        status, body = exc.code, exc.read()
        content_type = exc.headers.get_content_type()
    if status != expected:
        raise AssertionError("%s %s expected %s, got %s: %s" % (method, path, expected, status, body.decode()))
    return json.loads(body.decode()) if content_type == "application/json" else body.decode()


def wait_for(fetch, predicate, label, timeout=8):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            last = fetch()
            if predicate(last):
                return last
        except Exception as exc:
            last = str(exc)
        time.sleep(0.05)
    raise AssertionError("等待%s超时，最后状态：%s" % (label, last))


def read_log(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")[-4000:]
    except OSError:
        return ""


def main():
    port = free_port()
    relay_port = free_port()
    relay = ThreadingHTTPServer(("127.0.0.1", relay_port), RelayHandler)
    threading.Thread(target=relay.serve_forever, daemon=True).start()
    data_dir = tempfile.mkdtemp(prefix="miaoshou-selfcheck-")
    env = {**os.environ, "PORT": str(port), "WORKBENCH_DATA_DIR": data_dir}
    log_path = Path(data_dir) / "server.log"
    log_file = open(log_path, "w", encoding="utf-8")
    process = subprocess.Popen([sys.executable, "app.py"], cwd=str(ROOT), env=env, stdout=log_file, stderr=subprocess.STDOUT, text=True)
    base = "http://127.0.0.1:%s" % port
    try:
        time.sleep(1.0)
        startup_deadline = time.time() + 15
        last_error = ""
        while time.time() < startup_deadline:
            try:
                if request(base, "GET", "/api/health")["ok"]:
                    break
            except Exception as exc:
                last_error = str(exc)
                time.sleep(0.1)
        else:
            output = read_log(log_path)
            raise AssertionError("服务未在15秒内启动：%s\n%s" % (last_error, output))

        imported = request(base, "POST", "/api/candidates/import-links", {"urls": ["https://detail.1688.com/offer/1234567890.html"]}, 201)
        candidate_id = imported["items"][0]["id"]
        request(base, "POST", "/api/candidates/" + candidate_id, {
            "title": "缓震轻量运动鞋", "category": "运动鞋", "source_price": 30, "weight_g": 800,
            "monthly_sales": 1500, "repurchase_rate": 23, "rating": 4.8, "supplier_years": 6,
            "dispatch_hours": 36, "image_count": 8, "sku_complete": True,
        })
        market = {code: {"trend": 80, "salesSignal": 78, "competition": 35, "targetPriceCny": 145, "dataComplete": True} for code in ("MY", "PH", "SG", "TH", "VN")}
        evaluated = request(base, "POST", "/api/candidates/evaluate", {"candidateIds": [candidate_id], "inputs": {candidate_id: {"markets": market}}})
        assert evaluated["items"][0]["status"] == "已达标"
        collection = request(base, "POST", "/api/candidates/collect-qualified", {"candidateIds": [candidate_id]})
        collection_run = collection["items"][0]["id"]
        collection_done = wait_for(
            lambda: request(base, "GET", "/api/runs/%s/events" % collection_run),
            lambda item: item["status"] == "ready_for_live", "采集演练任务",
        )
        assert collection_done["status"] == "ready_for_live"
        search = request(base, "POST", "/api/candidates/search", {"keyword": "运动鞋"}, 201)
        search_run = search["run"]["id"]
        wait_for(lambda: request(base, "GET", "/api/runs/%s/events" % search_run), lambda item: item["status"] == "waiting_browser", "关键词任务")
        request(base, "POST", "/api/runs/%s/retry" % search_run, {})
        wait_for(lambda: request(base, "GET", "/api/runs/%s/events" % search_run), lambda item: item["status"] == "waiting_browser", "关键词第一次重试")
        request(base, "POST", "/api/runs/%s/retry" % search_run, {})
        wait_for(lambda: request(base, "GET", "/api/runs/%s/events" % search_run), lambda item: item["status"] == "waiting_browser", "关键词第二次重试")
        retry_limit = request(base, "POST", "/api/runs/%s/retry" % search_run, {}, 400)
        assert "最多2次" in retry_limit["error"]

        reference = request(base, "POST", "/api/assets", {"dataUrl": "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode()}, 201)
        product = request(base, "POST", "/api/products", {
            "candidateId": candidate_id, "sourceProductId": "1234567890", "sourceUrl": "https://detail.1688.com/offer/1234567890.html",
            "title": "缓震轻量运动鞋", "sku": "SHOE-001", "category": "运动鞋", "sourcePrice": 30,
            "costPrice": 30, "weightG": 800, "mainImage": reference["url"], "status": "待图片审核",
        }, 201)
        request(base, "POST", "/api/assets", {"productId": product["id"], "dataUrl": "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode(), "approved": True}, 201)
        settings = request(base, "POST", "/api/settings", {
            "image.base_url": "http://127.0.0.1:%s" % relay_port,
            "image.path": "/v1/images/edits", "image.model": "gpt-image-test",
            "image.retries": 1, "text.path": "/v1/chat/completions", "text.model": "gpt-text-test",
        })
        assert settings["ok"]
        generated = request(base, "POST", "/api/images/generate", {"productId": product["id"], "preset": "basic"}, 201)
        generated = wait_for(
            lambda: request(base, "GET", "/api/images/jobs/%s" % generated["id"]),
            lambda item: item["status"] in ("awaiting_approval", "failed"), "AI生图任务",
        )
        assert generated["status"] == "awaiting_approval" and generated["completed_count"] == 1
        assert generated["context"]["prompts"] and "1:1" in generated["context"]["prompts"][0]
        versions = request(base, "GET", "/api/products/%s/markets" % product["id"])["items"]
        assert len(versions) == 5
        for version in versions:
            request(base, "POST", "/api/products/%s/markets/%s" % (product["id"], version["market"]), {
                "title": "Localized Sports Shoes " + version["market"], "sale_price": version["sale_price"],
                "warehouse": "Default Warehouse", "inventory": 20,
            })
        shop = request(base, "POST", "/api/shops", {"accountName": "test-account", "entityName": "test-entity", "shopName": "MY test shop", "market": "MY", "warehouse": "Default Warehouse", "defaultInventory": 20}, 201)
        batch = request(base, "POST", "/api/batches", {"name": "selfcheck", "productIds": [product["id"]], "shopIds": [shop["id"]], "dryRun": True}, 201)
        prepared = request(base, "POST", "/api/batches/%s/prepare" % batch["id"], {})
        prepared = wait_for(
            lambda: request(base, "GET", "/api/runs/%s/events" % prepared["id"]),
            lambda item: item["status"] == "waiting_confirmation", "批次准备",
        )
        confirmed = request(base, "POST", "/api/batches/%s/confirm" % batch["id"], {})
        completed_run = wait_for(
            lambda: request(base, "GET", "/api/runs/%s/events" % confirmed["run"]["id"]),
            lambda item: item["status"] == "completed", "批次确认",
        )
        completed_batch = wait_for(
            lambda: request(base, "GET", "/api/batches/%s" % batch["id"]),
            lambda item: item["status"] == "completed_dry_run", "批次完成状态",
        )
        assert completed_run["context"]["phase"] == "confirm" and completed_batch["status"] == "completed_dry_run"

        duplicate_batch = request(base, "POST", "/api/batches", {"name": "second-dry-run", "productIds": [product["id"]], "shopIds": [shop["id"]], "dryRun": True}, 201)
        duplicate_prepared = request(base, "POST", "/api/batches/%s/prepare" % duplicate_batch["id"], {})
        wait_for(lambda: request(base, "GET", "/api/runs/%s/events" % duplicate_prepared["id"]), lambda item: item["status"] == "waiting_confirmation", "重复演练准备")
        settings = request(base, "POST", "/api/settings", {"automation.collection_recipe": [], "automation.publish_recipe": []})
        assert settings["ok"]
        dashboard = request(base, "GET", "/api/dashboard")
        assert dashboard["candidates"] == 1 and dashboard["qualified"] == 1 and dashboard["products"] == 1
        runtime_check = request(base, "GET", "/api/selfcheck")
        assert runtime_check["ok"] and any(item["id"] == "database" and item["status"] == "pass" for item in runtime_check["checks"])
        rejected = request(base, "POST", "/api/settings", {"evaluation.threshold": 1}, 403, {"Origin": "https://malicious.example"})
        assert "非本机" in rejected["error"]
        html = request(base, "GET", "/")
        assert "妙手智能选品" in html and "铺货控制台" in html

        recovery_job_id = uuid.uuid4().hex
        with sqlite3.connect(str(Path(data_dir) / "workbench.db")) as connection:
            now = int(time.time())
            connection.execute(
                "INSERT INTO generation_jobs(id,product_id,preset,status,requested_count,context,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (recovery_job_id, product["id"], "basic", "running", 1, json.dumps({"prompts": ["Recovery test square 1:1 ecommerce image"]}), now, now),
            )
            connection.execute(
                "UPDATE automation_runs SET status='running',context=? WHERE id=?",
                (json.dumps({"phase": "confirm"}), duplicate_prepared["id"]),
            )
            connection.execute("UPDATE batches SET status='confirmed' WHERE id=?", (duplicate_batch["id"],))

        process.terminate()
        process.wait(timeout=3)
        log_file.close()
        log_file = open(log_path, "a", encoding="utf-8")
        process = subprocess.Popen([sys.executable, "app.py"], cwd=str(ROOT), env=env, stdout=log_file, stderr=subprocess.STDOUT, text=True)
        wait_for(lambda: request(base, "GET", "/api/health"), lambda item: item["ok"], "服务重启")
        recovered_image = wait_for(
            lambda: request(base, "GET", "/api/images/jobs/%s" % recovery_job_id),
            lambda item: item["status"] in ("awaiting_approval", "failed"), "重启后生图恢复",
        )
        recovered_run = wait_for(
            lambda: request(base, "GET", "/api/runs/%s/events" % duplicate_prepared["id"]),
            lambda item: item["status"] in ("completed", "failed"), "重启后发布恢复",
        )
        recovered_batch = request(base, "GET", "/api/batches/%s" % duplicate_batch["id"])
        assert recovered_image["status"] == "awaiting_approval"
        assert recovered_run["status"] == "completed" and recovered_batch["status"] == "completed_dry_run"
        print("SELF-CHECK PASSED: asynchronous evaluation/collection, keyword retry limit, persistent and restart-safe AI generation, five markets, batch prepare/confirm recovery, retry-safe dry run, runtime checks, local-origin protection, dashboard, static UI")
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
        log_file.close()
        relay.shutdown()
        relay.server_close()


if __name__ == "__main__":
    main()
