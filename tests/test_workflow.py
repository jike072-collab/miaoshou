import json
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import app
from lib.database import Database


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.original_db = app.DB
        app.DB = Database(Path(tempfile.mkdtemp()) / "test.db")

    def tearDown(self):
        app.DB = self.original_db

    def step_map(self):
        return {item["key"]: item for item in app.workflow_summary()["steps"]}

    def collectable_candidate(self, url="https://detail.1688.com/offer/700001.html"):
        candidate = app.DB.import_candidates([url])[0]
        app.DB.update_candidate(candidate["id"], {
            "title": "可采集运动鞋",
            "category": "运动鞋",
            "source_price": 30,
            "weight_g": 500,
            "monthly_sales": 1200,
            "repurchase_rate": 20,
            "rating": 4.8,
            "supplier_years": 4,
            "dispatch_hours": 24,
            "image_count": 4,
            "sku_complete": True,
        })
        app.DB.save_evaluations(candidate["id"], [{
            "market": "MY",
            "demand_score": 82,
            "sales_score": 82,
            "profit_score": 82,
            "competition_score": 80,
            "logistics_score": 80,
            "supply_score": 80,
            "media_score": 80,
            "total_score": 82,
            "confidence": 86,
            "hard_blocks": [],
            "reasons": ["达标"],
            "metrics": {"target_price_cny": 150, "market_data_complete": True, "margin_pct": 28},
        }])
        return app.DB.get_candidate(candidate["id"])

    def test_workflow_summary_empty_database_returns_all_steps(self):
        summary = app.workflow_summary()
        keys = [item["key"] for item in summary["steps"]]

        self.assertEqual(keys, [
            "import_candidates",
            "complete_product_data",
            "five_market_scoring",
            "collect_qualified",
            "generate_images",
            "review_images",
            "create_batches",
            "dry_run_check",
            "live_confirm",
            "publish_results",
        ])
        self.assertEqual(len(summary["steps"]), 10)
        self.assertTrue(all(item["pending"] == 0 for item in summary["steps"]))
        self.assertTrue(all(item["done"] == 0 for item in summary["steps"]))
        self.assertTrue(all(item["failed"] == 0 for item in summary["steps"]))
        self.assertTrue(all(not item["blocked"] for item in summary["steps"]))

    def test_workflow_summary_counts_candidates_and_missing_data(self):
        first = app.DB.import_candidates(["https://detail.1688.com/offer/111.html"])[0]
        app.DB.update_candidate(first["id"], {
            "category": "运动鞋",
            "source_price": 39,
            "weight_g": 800,
            "monthly_sales": 1200,
            "rating": 4.7,
            "sku_complete": True,
        })
        app.DB.import_candidates(["https://detail.1688.com/offer/222.html"])[0]

        steps = self.step_map()

        self.assertEqual(steps["import_candidates"]["done"], 2)
        self.assertEqual(steps["complete_product_data"]["done"], 1)
        self.assertEqual(steps["complete_product_data"]["pending"], 1)
        self.assertTrue(steps["complete_product_data"]["blocked"])

    def test_candidate_summary_reports_missing_fields_and_next_action(self):
        candidate = app.DB.import_candidates(["https://detail.1688.com/offer/555.html"])[0]

        summary = app.candidate_summary(app.DB.get_candidate(candidate["id"]))

        self.assertIn("category", summary["missingFields"])
        self.assertIn("source_price", summary["missingFields"])
        self.assertEqual(summary["dataCompleteness"]["completed"], 0)
        self.assertEqual(summary["dataCompleteness"]["required"], 9)
        self.assertEqual(summary["nextAction"], "从来源补全")
        self.assertTrue(any(item["message"] == "缺少成本价" for item in summary["missingHints"]))

    def test_candidate_summary_marks_complete_data_ready_for_scoring(self):
        candidate = app.DB.import_candidates(["https://detail.1688.com/offer/666.html"])[0]
        app.DB.update_candidate(candidate["id"], {
            "title": "透气运动鞋",
            "category": "运动鞋",
            "source_price": 39,
            "weight_g": 800,
            "monthly_sales": 1200,
            "rating": 4.7,
            "dispatch_hours": 48,
            "image_count": 3,
            "sku_complete": True,
        })

        summary = app.candidate_summary(app.DB.get_candidate(candidate["id"]))

        self.assertEqual(summary["dataCompleteness"]["requiredMissingFields"], [])
        self.assertIn("market_data", summary["missingFields"])
        self.assertEqual(summary["dataCompleteness"]["percent"], 100)
        self.assertEqual(summary["nextAction"], "可进入五国评分")
        self.assertTrue(summary["isReadyToScore"])
        self.assertEqual(summary["queue"], "ready_to_score")

    def test_candidate_queue_filter_and_bulk_actions(self):
        ready = app.DB.import_candidates(["https://detail.1688.com/offer/123.html"])[0]
        app.DB.update_candidate(ready["id"], {
            "title": "透气运动鞋",
            "category": "运动鞋",
            "source_price": 39,
            "weight_g": 800,
            "monthly_sales": 1200,
            "rating": 4.7,
            "dispatch_hours": 48,
            "image_count": 3,
            "sku_complete": True,
        })
        need_data = app.DB.import_candidates(["https://detail.1688.com/offer/456.html"])[0]

        need_items = app.filter_candidates_by_status(app.DB.list_candidates(), "need_data")
        ready_items = app.filter_candidates_by_status(app.DB.list_candidates(), "ready_to_score")
        check = app.bulk_check_candidates([ready["id"], need_data["id"]])
        skipped = app.bulk_skip_candidates([need_data["id"]])
        deleted = app.bulk_delete_candidates([need_data["id"]])

        self.assertEqual([item["id"] for item in ready_items], [ready["id"]])
        self.assertEqual([item["id"] for item in need_items], [need_data["id"]])
        self.assertEqual(check["checked"], 2)
        self.assertEqual(check["readyToScore"], [ready["id"]])
        self.assertEqual(check["needData"], [need_data["id"]])
        self.assertEqual(skipped["items"][0]["queue"], "skipped")
        self.assertEqual(deleted["deleted"], [need_data["id"]])
        self.assertIsNone(app.DB.get_candidate(need_data["id"]))

    def test_incomplete_candidate_is_blocked_from_scoring_and_collection(self):
        candidate = app.DB.import_candidates(["https://detail.1688.com/offer/789.html"])[0]
        app.DB.save_evaluations(candidate["id"], [{
            "market": "MY",
            "demand_score": 90,
            "sales_score": 90,
            "profit_score": 90,
            "competition_score": 90,
            "logistics_score": 90,
            "supply_score": 90,
            "media_score": 90,
            "total_score": 90,
            "confidence": 90,
            "hard_blocks": [],
            "reasons": [],
            "metrics": {"target_price_cny": 120, "market_data_complete": True},
        }])

        results, blocked = app.evaluate_candidates([candidate["id"]])
        self.assertEqual(results, [])
        self.assertEqual(blocked[0]["error"], "基础数据不完整，不能进入评分")
        self.assertIn("source_price", blocked[0]["missingFields"])

        summary = app.candidate_summary(app.DB.get_candidate(candidate["id"]))
        collection = app.collect_qualified_candidates([candidate["id"]])

        self.assertFalse(summary["isReadyToScore"])
        self.assertFalse(summary["canCollect"])
        self.assertEqual(collection["items"], [])
        self.assertEqual(collection["blocked"][0]["error"], "基础数据不完整，不能进入自动采集")

    def test_candidate_summary_reports_market_collection_pool_status(self):
        candidate = app.DB.import_candidates(["https://detail.1688.com/offer/777.html"])[0]
        app.DB.update_candidate(candidate["id"], {
            "title": "透气运动鞋",
            "category": "运动鞋",
            "source_price": 30,
            "weight_g": 800,
            "monthly_sales": 1000,
            "repurchase_rate": 20,
            "rating": 4.8,
            "supplier_years": 5,
            "dispatch_hours": 48,
            "image_count": 6,
            "sku_complete": True,
        })
        evaluations = app.evaluate_candidate(app.DB.get_candidate(candidate["id"]), {
            "markets": {
                "MY": {"targetPriceCny": 140, "trend": 80, "salesSignal": 80, "competition": 30, "dataComplete": True},
                "PH": {"targetPriceCny": 35, "trend": 80, "salesSignal": 80, "competition": 30, "dataComplete": True},
            }
        })
        app.DB.save_evaluations(candidate["id"], evaluations)

        summary = app.candidate_summary(app.DB.get_candidate(candidate["id"]))

        self.assertIn("MY", summary["marketSummary"]["qualified"])
        self.assertTrue(summary["marketSummary"]["hasCollectableMarkets"])
        self.assertEqual(summary["marketSummary"]["markets"]["MY"]["decision"], "collectable")
        self.assertEqual(summary["marketSummary"]["markets"]["MY"]["decisionLabel"], "可采集")
        self.assertEqual(summary["marketSummary"]["markets"]["PH"]["decision"], "rejected")
        self.assertEqual(summary["marketSummary"]["markets"]["PH"]["decisionLabel"], "不建议采集")
        self.assertIsNotNone(summary["marketSummary"]["markets"]["MY"]["marginPct"])
        self.assertIn("PH", summary["marketSummary"]["blockedMarkets"])
        self.assertEqual(summary["marketSummary"]["nextAction"], "采集达标商品")

    def test_qualified_evaluations_and_targeted_collection(self):
        candidate = app.DB.import_candidates(["https://detail.1688.com/offer/778.html"])[0]
        app.DB.update_candidate(candidate["id"], {
            "title": "轻量运动鞋",
            "category": "运动鞋",
            "source_price": 28,
            "weight_g": 650,
            "monthly_sales": 1400,
            "repurchase_rate": 22,
            "rating": 4.8,
            "supplier_years": 5,
            "dispatch_hours": 48,
            "image_count": 4,
            "sku_complete": True,
        })
        evaluations = app.evaluate_candidate(app.DB.get_candidate(candidate["id"]), {
            "markets": {
                "MY": {"targetPriceCny": 150, "trend": 85, "salesSignal": 82, "competition": 25, "dataComplete": True},
                "SG": {"targetPriceCny": 160, "trend": 84, "salesSignal": 80, "competition": 30, "dataComplete": True},
                "PH": {"targetPriceCny": 20, "trend": 80, "salesSignal": 80, "competition": 30, "dataComplete": True},
            }
        })
        app.DB.save_evaluations(candidate["id"], evaluations)

        qualified = app.qualified_evaluations_summary()
        with patch("app.AUTOMATION.create_collection_run", side_effect=lambda item: app.DB.create_run("collection", ["采集"], candidate_id=item["id"])), \
             patch("app.enqueue_automation_run", return_value=True):
            collected = app.collect_qualified_candidates([candidate["id"]], markets=["MY"])
            reviewed = app.collect_qualified_candidates([candidate["id"]], review=True)

        self.assertEqual(qualified["count"], 1)
        self.assertIn("MY", qualified["items"][0]["collectableMarkets"])
        self.assertEqual(collected["items"][0]["markets"], ["MY"])
        self.assertEqual(app.DB.get_run(collected["items"][0]["id"])["context"]["markets"], ["MY"])
        self.assertEqual(reviewed["blocked"][0]["error"], "已转人工复核")
        self.assertEqual(app.DB.get_candidate(candidate["id"])["status"], "人工复核")

    def test_collection_queue_includes_collectable_candidates_before_run_exists(self):
        candidate = self.collectable_candidate()

        queue = app.collection_queue_summary("pending")

        self.assertEqual(queue["queues"][0]["key"], "pending")
        item = next(row for row in queue["items"] if row["candidateId"] == candidate["id"])
        self.assertEqual(item["source"], "candidate")
        self.assertEqual(item["queue"], "pending")
        self.assertEqual(item["markets"], ["MY"])
        self.assertEqual(item["currentStep"], "等待创建采集任务")

    def test_collection_queue_excludes_already_collected_candidates(self):
        candidate = self.collectable_candidate("https://detail.1688.com/offer/700004.html")
        app.DB.update_candidate(candidate["id"], {"collected_at": int(time.time())})
        app.ensure_product_from_candidate(candidate["id"])

        queue = app.collection_queue_summary("pending")

        self.assertFalse(any(item["candidateId"] == candidate["id"] for item in queue["items"]))

    def test_collection_queue_failed_task_exposes_diagnostics(self):
        candidate = self.collectable_candidate("https://detail.1688.com/offer/700002.html")
        now = int(time.time())
        app.DB.execute(
            "INSERT INTO automation_runs(id,candidate_id,kind,status,current_step,steps,error,screenshot,diagnostics,attempts,context,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "collect-failed-task", candidate["id"], "collection", "blocked", "点击采集按钮", "[]",
                "插件按钮未找到", "/tmp/collect.png",
                json.dumps({
                    "failedStep": "点击采集按钮",
                    "error": "插件按钮未找到",
                    "currentUrl": "https://detail.1688.com/offer/700002.html",
                    "screenshot": "/tmp/collect.png",
                    "clickableText": ["采集此产品", "加入采集箱"],
                    "suggestedActions": ["检查妙手插件按钮文本"],
                }, ensure_ascii=False),
                1,
                json.dumps({"markets": ["MY", "SG"]}, ensure_ascii=False),
                now,
                now,
            ),
        )

        detail = app.collection_task_detail("collect-failed-task")

        self.assertEqual(detail["queue"], "failed")
        self.assertEqual(detail["product"], "可采集运动鞋")
        self.assertEqual(detail["markets"], ["MY", "SG"])
        self.assertEqual(detail["currentStep"], "点击采集按钮")
        self.assertEqual(detail["currentUrl"], "https://detail.1688.com/offer/700002.html")
        self.assertEqual(detail["screenshot"], "/tmp/collect.png")
        self.assertIn("检查妙手插件", detail["suggestedActions"][0])
        self.assertIn("采集此产品", detail["clickableText"])

    def test_collection_bulk_actions_start_retry_skip_and_manual(self):
        candidate = self.collectable_candidate("https://detail.1688.com/offer/700003.html")
        now = int(time.time())
        app.DB.execute(
            "INSERT INTO automation_runs(id,candidate_id,kind,status,current_step,steps,error,diagnostics,attempts,context,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("collect-retry-task", candidate["id"], "collection", "blocked", "登录检查", "[]", "登录失效", "{}", 0, "{\"markets\":[\"MY\"]}", now, now),
        )
        app.DB.execute(
            "INSERT INTO automation_runs(id,candidate_id,kind,status,current_step,steps,error,diagnostics,context,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("collect-manual-task", candidate["id"], "collection", "queued", "等待采集", "[]", "", "{}", "{\"markets\":[\"MY\"]}", now, now),
        )

        with patch("app.enqueue_automation_run", return_value=True):
            retried = app.bulk_collection_action({"action": "retry_failed", "runIds": ["collect-retry-task"]})
            skipped = app.bulk_collection_action({"action": "skip", "runIds": ["collect-retry-task"]})
            manual = app.bulk_collection_action({"action": "manual", "runIds": ["collect-manual-task"]})

        self.assertEqual(retried["updated"][0]["status"], "queued")
        self.assertEqual(retried["updated"][0]["attempts"], 1)
        self.assertEqual(skipped["updated"][0]["status"], "skipped")
        self.assertEqual(manual["updated"][0]["resolution"], "manual")

    def test_workflow_summary_counts_image_jobs(self):
        product = app.DB.save_product({
            "sourceUrl": "https://detail.1688.com/offer/333.html",
            "sourceProductId": "333",
            "title": "运动包",
        })
        now = int(time.time())
        for status in ("queued", "running", "awaiting_approval", "failed"):
            app.DB.execute(
                "INSERT INTO generation_jobs(id,product_id,preset,status,requested_count,completed_count,error,context,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, product["id"], "standard", status, 3, 1 if status == "awaiting_approval" else 0, "", "{}", now, now),
            )

        step = self.step_map()["generate_images"]

        self.assertEqual(step["pending"], 2)
        self.assertEqual(step["done"], 1)
        self.assertEqual(step["failed"], 1)
        self.assertTrue(step["blocked"])

    def test_image_workbench_summary_empty_database(self):
        summary = app.image_workbench_summary()

        self.assertEqual(summary["overview"]["totalProducts"], 0)
        self.assertEqual(summary["overview"]["needsGeneration"], 0)
        self.assertEqual(summary["items"], [])

    def test_image_workbench_summary_groups_generation_and_review_states(self):
        now = int(time.time())
        source_only = app.DB.save_product({
            "sourceUrl": "https://detail.1688.com/offer/101.html",
            "sourceProductId": "101",
            "title": "待生图运动鞋",
            "mainImage": "https://example.com/source.jpg",
        })
        approved = app.DB.save_product({
            "sourceUrl": "https://detail.1688.com/offer/102.html",
            "sourceProductId": "102",
            "title": "已审核运动包",
            "mainImage": "https://example.com/source2.jpg",
        })
        awaiting = app.DB.save_product({
            "sourceUrl": "https://detail.1688.com/offer/103.html",
            "sourceProductId": "103",
            "title": "待审核套装",
            "mainImage": "https://example.com/source3.jpg",
        })
        failed = app.DB.save_product({
            "sourceUrl": "https://detail.1688.com/offer/104.html",
            "sourceProductId": "104",
            "title": "失败运动鞋",
            "mainImage": "https://example.com/source4.jpg",
        })
        app.DB.execute(
            "INSERT INTO assets(id,product_id,url,kind,approved,prompt,created_at) VALUES (?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, approved["id"], "/assets/approved.jpg", "uploaded", 1, "", now),
        )
        app.DB.execute(
            "INSERT INTO assets(id,product_id,url,kind,approved,prompt,created_at) VALUES (?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, awaiting["id"], "/assets/generated.jpg", "generated", 0, "prompt", now),
        )
        app.DB.execute(
            "INSERT INTO generation_jobs(id,product_id,preset,status,requested_count,completed_count,error,context,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, awaiting["id"], "standard", "awaiting_approval", 3, 3, "", "{}", now, now),
        )
        app.DB.execute(
            "INSERT INTO generation_jobs(id,product_id,preset,status,requested_count,completed_count,error,context,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("failed-job", failed["id"], "standard", "failed", 3, 0, "请先在设置中填写图片中转站 Base URL", "{}", now, now),
        )

        summary = app.image_workbench_summary()
        items = {item["productId"]: item for item in summary["items"]}

        self.assertEqual(summary["overview"]["totalProducts"], 4)
        self.assertEqual(summary["overview"]["needsGeneration"], 1)
        self.assertEqual(summary["overview"]["awaitingApproval"], 1)
        self.assertEqual(summary["overview"]["approved"], 1)
        self.assertEqual(summary["overview"]["failed"], 1)
        self.assertEqual(items[source_only["id"]]["status"], "needs_generation")
        self.assertEqual(items[approved["id"]]["status"], "approved")
        self.assertEqual(items[awaiting["id"]]["pendingReviewCount"], 1)
        self.assertEqual(items[failed["id"]]["latestJob"]["id"], "failed-job")
        self.assertIn("Base URL", items[failed["id"]]["failure"]["suggestedActions"][0])

    def test_retry_failed_image_job_requeues_existing_job(self):
        product = app.DB.save_product({
            "sourceUrl": "https://detail.1688.com/offer/105.html",
            "sourceProductId": "105",
            "title": "失败运动鞋",
            "mainImage": "https://example.com/source.jpg",
        })
        now = int(time.time())
        app.DB.execute(
            "INSERT INTO generation_jobs(id,product_id,preset,status,requested_count,completed_count,error,context,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("retry-job", product["id"], "standard", "failed", 3, 0, "接口超时", "{\"prompts\":[\"a\"]}", now, now),
        )

        with patch("app.enqueue_generation", return_value=True) as enqueue:
            refreshed = app.retry_generation_job("retry-job")

        self.assertEqual(refreshed["status"], "queued")
        self.assertEqual(refreshed["error"], "")
        enqueue.assert_called_once_with("retry-job")

    def test_workflow_summary_counts_batches_and_failed_runs(self):
        now = int(time.time())
        product = app.DB.save_product({
            "sourceUrl": "https://detail.1688.com/offer/444.html",
            "sourceProductId": "444",
            "title": "运动鞋",
        })
        app.DB.execute(
            "INSERT INTO assets(id,product_id,url,kind,approved,prompt,created_at) VALUES (?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, product["id"], "/assets/test.jpg", "uploaded", 1, "", now),
        )
        app.DB.execute(
            "INSERT INTO batches(id,name,status,dry_run,product_ids,shop_ids,summary,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            ("dry-batch", "演练批次", "preparing", 1, "[\"%s\"]" % product["id"], "[]", "{}", now, now),
        )
        app.DB.execute(
            "INSERT INTO batches(id,name,status,dry_run,product_ids,shop_ids,summary,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            ("live-batch", "真实批次", "failed", 0, "[\"%s\"]" % product["id"], "[]", "{}", now, now),
        )
        app.DB.execute(
            "INSERT INTO automation_runs(id,batch_id,kind,status,current_step,steps,error,context,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, "live-batch", "publish", "failed", "发布", "[]", "页面错误", "{}", now, now),
        )

        steps = self.step_map()

        self.assertEqual(steps["create_batches"]["done"], 2)
        self.assertEqual(steps["create_batches"]["failed"], 1)
        self.assertEqual(steps["dry_run_check"]["pending"], 1)
        self.assertTrue(steps["dry_run_check"]["blocked"])
        self.assertEqual(steps["live_confirm"]["failed"], 1)
        self.assertTrue(steps["live_confirm"]["blocked"])
        self.assertEqual(steps["publish_results"]["failed"], 1)
        self.assertTrue(steps["publish_results"]["blocked"])

    def test_publish_results_summary_groups_failed_and_waiting_runs(self):
        now = int(time.time())
        app.DB.execute(
            "INSERT INTO batches(id,name,status,dry_run,product_ids,shop_ids,summary,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            ("batch-live", "真实批次", "confirmed", 0, "[]", "[]", "{}", now, now),
        )
        app.DB.execute(
            "INSERT INTO automation_runs(id,batch_id,kind,status,current_step,steps,error,diagnostics,context,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("run-failed", "batch-live", "publish", "failed", "上传图片", "[]", "页面卡住", "{\"error\":\"页面卡住\",\"suggestedActions\":[\"刷新页面后重试\"]}", "{}", now, now),
        )
        app.DB.execute(
            "INSERT INTO automation_runs(id,batch_id,kind,status,current_step,steps,error,diagnostics,context,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("run-wait", "batch-live", "publish", "waiting_confirmation", "等待确认", "[]", "", "{}", "{}", now, now),
        )
        app.DB.execute(
            "INSERT INTO publish_keys(idempotency_key,batch_id,status,created_at) VALUES (?,?,?,?)",
            ("k1", "batch-live", "published", now),
        )

        summary = app.publish_results_summary()

        self.assertEqual(summary["overview"]["failedRuns"], 1)
        self.assertEqual(summary["overview"]["waitingRuns"], 1)
        self.assertEqual(summary["overview"]["publishedTasks"], 1)
        self.assertEqual(summary["failures"][0]["id"], "run-failed")
        self.assertEqual(summary["failures"][0]["screenshot"], "")
        self.assertIn("刷新页面", summary["failures"][0]["suggestedActions"][0])
        self.assertEqual(summary["waiting"][0]["id"], "run-wait")

    def test_publish_results_summary_includes_retryable_collection_failure(self):
        now = int(time.time())
        app.DB.execute(
            "INSERT INTO automation_runs(id,kind,status,current_step,steps,error,diagnostics,context,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("run-collect", "collection", "blocked", "调用妙手插件采集", "[]", "插件按钮未找到", "{\"failedStep\":\"调用妙手插件采集\",\"suggestedActions\":[\"检查插件按钮\"]}", "{}", now, now),
        )

        summary = app.publish_results_summary()

        self.assertEqual(summary["overview"]["failedRuns"], 1)
        self.assertEqual(summary["failures"][0]["label"], "妙手采集")
        self.assertIn("检查插件按钮", summary["failures"][0]["suggestedActions"][0])

    def test_publish_results_summary_unifies_image_asset_and_publish_failures(self):
        now = int(time.time())
        product = app.DB.save_product({
            "sourceUrl": "https://detail.1688.com/offer/501.html",
            "sourceProductId": "501",
            "title": "失败商品",
            "mainImage": "https://example.com/501.jpg",
        })
        shop_id = uuid.uuid4().hex
        app.DB.execute(
            "INSERT INTO shops(id,account_name,entity_name,shop_name,market,warehouse,default_inventory,price_multiplier,enabled) VALUES (?,?,?,?,?,?,?,?,?)",
            (shop_id, "acc", "entity", "MY Shop", "MY", "WH", 20, 1, 1),
        )
        app.DB.execute(
            "INSERT INTO generation_jobs(id,product_id,preset,status,requested_count,completed_count,error,context,attempts,last_error,last_run_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("job-failed", product["id"], "standard", "failed", 3, 0, "接口超时", "{\"prompts\":[\"p\"]}", 2, "接口超时", now, now, now),
        )
        app.DB.execute(
            "INSERT INTO assets(id,product_id,url,kind,approved,review_status,rejection_reason,prompt,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            ("asset-rejected", product["id"], "/assets/reject.jpg", "generated", 0, "rejected", "Logo 错误", "p", now),
        )
        app.DB.execute(
            "INSERT INTO publish_keys(idempotency_key,batch_id,status,product_id,shop_id,market,result,failure_reason,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            ("pk-failed", "batch-x", "failed", product["id"], shop_id, "MY", "发布失败", "页面结构变化", now),
        )

        summary = app.publish_results_summary()
        types = {item["type"] for item in summary["failures"]}

        self.assertIn("生图失败", types)
        self.assertIn("图片审核不通过", types)
        self.assertIn("真实发布失败", types)
        self.assertEqual(summary["overview"]["failedTasks"], 1)
        self.assertEqual(summary["overview"]["successRate"], 0)
        self.assertTrue(summary["marketStats"])

    def test_failure_action_marks_run_handled_and_retries_generation(self):
        now = int(time.time())
        app.DB.execute(
            "INSERT INTO automation_runs(id,kind,status,current_step,steps,error,diagnostics,context,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("run-failed-action", "publish", "failed", "发布", "[]", "失败", "{}", "{}", now, now),
        )
        product = app.DB.save_product({
            "sourceUrl": "https://detail.1688.com/offer/502.html",
            "sourceProductId": "502",
            "title": "重试商品",
            "mainImage": "https://example.com/502.jpg",
        })
        app.DB.execute(
            "INSERT INTO generation_jobs(id,product_id,preset,status,requested_count,completed_count,error,context,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("job-retry-action", product["id"], "standard", "failed", 1, 0, "接口超时", "{\"prompts\":[\"p\"]}", now, now),
        )

        handled = app.resolve_failure_task({"source": "automation_run", "id": "run-failed-action", "action": "mark_handled"})
        self.assertEqual(handled["resolution"], "handled")
        with patch("app.enqueue_generation", return_value=True):
            retried = app.resolve_failure_task({"source": "generation_job", "id": "job-retry-action", "action": "retry"})
        self.assertEqual(retried["status"], "queued")

    def test_collection_completion_creates_one_product_and_five_markets(self):
        candidate = app.DB.import_candidates(["https://detail.1688.com/offer/998877.html"])[0]
        app.DB.update_candidate(candidate["id"], {
            "source_product_id": "998877", "title": "轻量运动包", "category": "运动包",
            "source_price": 28, "weight_g": 650, "images": ["https://example.com/bag.jpg"],
        })

        first = app.ensure_product_from_candidate(candidate["id"])
        second = app.ensure_product_from_candidate(candidate["id"])

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(app.DB.list_products()), 1)
        self.assertEqual(len(app.DB.market_versions(first["id"])), 5)
        self.assertEqual(first["mainImage"], "https://example.com/bag.jpg")

    def test_refresh_candidate_from_source_populates_core_fields(self):
        candidate = app.DB.import_candidates(["https://detail.1688.com/offer/998877.html"])[0]
        with patch("app.scrape_product", return_value={
            "title": "网面透气运动鞋女2026新款",
            "category": "",
            "sourcePrice": 39.8,
            "weightG": 880,
            "images": ["https://example.com/a.jpg", "https://example.com/b.jpg"],
        }):
            refreshed = app.refresh_candidate_from_source(candidate["id"])

        self.assertEqual(refreshed["title"], "网面透气运动鞋女2026新款")
        self.assertEqual(refreshed["category"], "运动鞋")
        self.assertEqual(refreshed["source_price"], 39.8)
        self.assertEqual(refreshed["weight_g"], 880)
        self.assertEqual(refreshed["image_count"], 2)
        self.assertEqual(refreshed["status"], "待确认")

    def test_refresh_candidate_preserves_existing_images_when_source_has_none(self):
        candidate = app.DB.import_candidates(["https://detail.1688.com/offer/998877.html"])[0]
        app.DB.update_candidate(candidate["id"], {
            "title": "运动鞋",
            "images": ["https://example.com/search.jpg"],
            "image_count": 1,
        })
        with patch("app.scrape_product", return_value={
            "title": "亲，请按照说明进行验证哦",
            "category": "",
            "sourcePrice": 0,
            "weightG": 0,
            "images": [],
        }):
            refreshed = app.refresh_candidate_from_source(candidate["id"])

        self.assertEqual(refreshed["title"], "运动鞋")
        self.assertEqual(refreshed["images"], ["https://example.com/search.jpg"])
        self.assertEqual(refreshed["image_count"], 1)

    def test_system_selfcheck_reports_business_readiness_gaps(self):
        app.DB.import_candidates(["https://detail.1688.com/offer/998877.html"])[0]
        result = app.system_selfcheck()
        checks = {item["id"]: item for item in result["checks"]}

        self.assertEqual(checks["candidate_pool"]["status"], "pass")
        self.assertEqual(checks["candidate_supply_data"]["status"], "warn")
        self.assertEqual(checks["qualified_candidates"]["status"], "warn")
        self.assertEqual(checks["product_pool"]["status"], "warn")
        self.assertTrue(result["nextSteps"]["automatic"])

    def test_bulk_refresh_sources_reports_partial_errors(self):
        first = app.DB.import_candidates(["https://detail.1688.com/offer/111.html"])[0]
        second = app.DB.import_candidates(["https://detail.1688.com/offer/222.html"])[0]

        def fake_refresh(candidate_id):
            if candidate_id == second["id"]:
                raise RuntimeError("验证页")
            app.DB.update_candidate(candidate_id, {"title": "运动鞋", "category": "运动鞋"})
            return app.candidate_summary(app.DB.get_candidate(candidate_id))

        with patch("app.refresh_candidate_from_source", side_effect=fake_refresh):
            result = app.refresh_candidates_from_sources([first["id"], second["id"], "missing"])

        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(len(result["errors"]), 2)
        self.assertEqual(result["items"][0]["title"], "运动鞋")
        self.assertIn("验证页", result["errors"][0]["error"])

    def test_selfcheck_repair_creates_product_and_approved_asset(self):
        candidate = app.DB.import_candidates(["https://detail.1688.com/offer/998877.html"])[0]
        app.DB.update_candidate(candidate["id"], {
            "title": "轻量运动包",
            "category": "运动包",
            "source_price": 28,
            "weight_g": 650,
            "monthly_sales": 1000,
            "repurchase_rate": 20,
            "rating": 4.8,
            "supplier_years": 5,
            "dispatch_hours": 48,
            "image_count": 1,
            "sku_complete": True,
            "images": ["https://example.com/bag.jpg"],
        })
        evaluations = app.evaluate_candidate(app.DB.get_candidate(candidate["id"]), {
            "markets": {"MY": {"targetPriceCny": 140, "trend": 82, "salesSignal": 82, "competition": 30, "dataComplete": True}}
        })
        app.DB.save_evaluations(candidate["id"], evaluations)
        with patch("app.fetch_image", return_value=(b"fake-image-bytes", "image/jpeg")):
            result = app.selfcheck_repair()

        self.assertTrue(result["actions"])
        self.assertTrue(app.DB.list_products())
        self.assertTrue(app.DB.rows("SELECT * FROM assets WHERE approved=1"))
        self.assertFalse(result["after"]["readyForLive"])
        self.assertIn("manual", result["nextSteps"])
        self.assertEqual(app.DB.get_candidate(candidate["id"])["status"], "已达标")

    def test_selfcheck_repair_limits_source_refresh(self):
        candidates = app.DB.import_candidates([
            "https://detail.1688.com/offer/111.html",
            "https://detail.1688.com/offer/222.html",
            "https://detail.1688.com/offer/333.html",
        ])
        calls = []

        def fake_refresh(candidate_id):
            calls.append(candidate_id)
            item = app.DB.update_candidate(candidate_id, {"title": "运动鞋", "category": "运动鞋", "image_count": 1})
            return app.candidate_summary(item)

        with patch("app.refresh_candidate_from_source", side_effect=fake_refresh):
            result = app.selfcheck_repair(max_refresh=2)

        self.assertEqual(len(calls), 2)
        self.assertTrue(any("仍有 1 个候选待批量补全" in action for action in result["actions"]))
        self.assertEqual(calls, [candidates[0]["id"], candidates[1]["id"]])

    def test_full_workflow_integration_keeps_dashboards_in_sync(self):
        now = int(time.time())
        candidate = app.DB.import_candidates(["https://detail.1688.com/offer/888999.html"])[0]
        app.DB.update_candidate(candidate["id"], {
            "source_product_id": "888999",
            "title": "轻量透气运动鞋",
            "category": "运动鞋",
            "source_price": 35,
            "weight_g": 720,
            "monthly_sales": 1800,
            "repurchase_rate": 18,
            "rating": 4.8,
            "supplier_years": 6,
            "dispatch_hours": 48,
            "image_count": 2,
            "sku_complete": True,
            "images": ["https://example.com/shoe.jpg"],
        })
        evaluations = app.evaluate_candidate(app.DB.get_candidate(candidate["id"]), {
            "markets": {
                "MY": {"targetPriceCny": 150, "trend": 85, "salesSignal": 80, "competition": 25, "dataComplete": True},
                "PH": {"targetPriceCny": 160, "trend": 82, "salesSignal": 78, "competition": 28, "dataComplete": True},
                "SG": {"targetPriceCny": 165, "trend": 80, "salesSignal": 75, "competition": 30, "dataComplete": True},
                "TH": {"targetPriceCny": 168, "trend": 79, "salesSignal": 74, "competition": 32, "dataComplete": True},
                "VN": {"targetPriceCny": 170, "trend": 81, "salesSignal": 77, "competition": 29, "dataComplete": True},
            }
        })
        app.DB.save_evaluations(candidate["id"], evaluations)

        product = app.ensure_product_from_candidate(candidate["id"])
        app.DB.execute(
            "INSERT INTO assets(id,product_id,url,kind,approved,prompt,created_at) VALUES (?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, product["id"], "/assets/approved.jpg", "uploaded", 1, "", now),
        )
        app.DB.execute(
            "INSERT INTO generation_jobs(id,product_id,preset,status,requested_count,completed_count,error,context,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("job-approved", product["id"], "standard", "awaiting_approval", 3, 3, "", "{}", now, now),
        )
        shop_id = uuid.uuid4().hex
        app.DB.execute(
            "INSERT INTO shops(id,account_name,entity_name,shop_name,market,warehouse,default_inventory,price_multiplier,enabled) VALUES (?,?,?,?,?,?,?,?,?)",
            (shop_id, "account", "entity", "MY shop", "MY", "MY-WH", 20, 1, 1),
        )
        app.DB.save_market_version(product["id"], "MY", {
            "title": "轻量透气运动鞋",
            "sale_price": 129,
            "warehouse": "MY-WH",
            "inventory": 20,
        })

        batch_payload = {"id": "batch-flow", "product_ids": [product["id"]], "shop_ids": [shop_id], "dry_run": True}
        preview = app.batch_preflight(batch_payload)
        self.assertTrue(preview["ready"])
        app.DB.execute(
            "INSERT INTO batches(id,name,status,dry_run,product_ids,shop_ids,summary,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                "batch-flow", "联调演练批次", "preparing", 1,
                "[\"%s\"]" % product["id"], "[\"%s\"]" % shop_id,
                json.dumps(app.batch_summary_from_preview(preview), ensure_ascii=False),
                now, now,
            ),
        )
        app.reserve_publish_keys(batch_payload)
        run = app.DB.create_run("publish", ["检查批次完整性", "等待人工确认"], batch_id="batch-flow", status="waiting_confirmation")

        confirmation = app.batch_confirmation_summary(app.DB.row("SELECT * FROM batches WHERE id=?", ("batch-flow",)))
        self.assertTrue(confirmation["canConfirm"])
        with patch("app.enqueue_automation_run", return_value=True):
            confirmed = app.confirm_batch("batch-flow", {"confirmation": confirmation["phrase"]})

        self.assertEqual(confirmed["batch"]["status"], "confirmed")
        app.DB.update_run(run["id"], status="completed", current_step="演练完成，未点击妙手最终发布")
        app.DB.execute("UPDATE batches SET status='completed' WHERE id=?", ("batch-flow",))
        app.DB.execute("UPDATE publish_keys SET status='dry_run' WHERE batch_id=?", ("batch-flow",))

        workflow = self.step_map()
        image_summary = app.image_workbench_summary()
        publish_results = app.publish_results_summary()

        self.assertEqual(workflow["import_candidates"]["done"], 1)
        self.assertEqual(workflow["complete_product_data"]["done"], 1)
        self.assertEqual(workflow["five_market_scoring"]["done"], 1)
        self.assertEqual(workflow["collect_qualified"]["done"], 1)
        self.assertEqual(workflow["generate_images"]["done"], 1)
        self.assertEqual(workflow["review_images"]["done"], 1)
        self.assertEqual(workflow["create_batches"]["done"], 1)
        self.assertEqual(workflow["dry_run_check"]["done"], 1)
        self.assertEqual(workflow["publish_results"]["done"], 1)
        self.assertEqual(image_summary["overview"]["approved"], 1)
        self.assertEqual(publish_results["overview"]["completedRuns"], 1)
        self.assertEqual(publish_results["overview"]["dryRunTasks"], 1)
        self.assertFalse(publish_results["failures"])

    def test_product_workflow_status_blocks_unapproved_images_until_review_passes(self):
        product = app.DB.save_product({
            "sourceUrl": "https://detail.1688.com/offer/777.html",
            "sourceProductId": "777",
            "title": "待审核商品",
            "mainImage": "https://example.com/777.jpg",
        })
        now = int(time.time())
        app.DB.execute(
            "INSERT INTO assets(id,product_id,url,kind,approved,review_status,rejection_reason,prompt,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            ("asset-pending-status", product["id"], "/assets/pending.jpg", "generated", 0, "pending", "", "p", now),
        )

        pending = app.get_product_workflow_status(product["id"])
        self.assertEqual(pending["stage"], "image_awaiting_review")
        self.assertTrue(pending["blocked"])

        app.approve_asset("asset-pending-status")
        ready = app.get_product_workflow_status(product["id"])
        self.assertEqual(ready["stage"], "ready_to_batch")
        self.assertFalse(ready["blocked"])

    def test_products_api_shape_includes_workflow_status(self):
        product = app.DB.save_product({
            "sourceUrl": "https://detail.1688.com/offer/778.html",
            "sourceProductId": "778",
            "title": "接口状态商品",
        })

        items = app.products_with_workflow_status()

        item = next(row for row in items if row["id"] == product["id"])
        self.assertIn("workflowStatus", item)
        self.assertEqual(item["workflowStatus"]["stage"], "image_needs_generation")

    def test_product_workflow_status_uses_batch_level_failures(self):
        product = app.DB.save_product({
            "sourceUrl": "https://detail.1688.com/offer/779.html",
            "sourceProductId": "779",
            "title": "批次失败商品",
            "mainImage": "https://example.com/779.jpg",
        })
        now = int(time.time())
        app.DB.execute(
            "INSERT INTO assets(id,product_id,url,kind,approved,review_status,rejection_reason,prompt,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            ("asset-batch-failure", product["id"], "/assets/ok.jpg", "uploaded", 1, "approved", "", "p", now),
        )
        app.DB.execute(
            "INSERT INTO batches(id,name,status,dry_run,product_ids,shop_ids,summary,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            ("batch-product-failure", "失败批次", "failed", 1, "[\"%s\"]" % product["id"], "[]", "{}", now, now),
        )
        app.DB.execute(
            "INSERT INTO automation_runs(id,batch_id,kind,status,current_step,steps,error,diagnostics,context,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("run-product-failure", "batch-product-failure", "publish", "failed", "演练发布", "[]", "页面结构变化", "{}", "{}", now, now),
        )

        status = app.get_product_workflow_status(product["id"])

        self.assertEqual(status["stage"], "failure_handling")
        self.assertTrue(status["failed"])


if __name__ == "__main__":
    unittest.main()
