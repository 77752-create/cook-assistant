import os
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

import app
import core
import knowledge


class CoreTests(unittest.TestCase):
    def tearDown(self):
        core._WHISPER_MODEL = None

    def test_bilibili_url_is_recognized(self):
        result = core.parse_video_input("https://www.bilibili.com/video/BV1oro6YxEmu")

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "bilibili")

    def test_recipe_organization_returns_steps(self):
        raw = "五花肉切片。热锅下五花肉煸出油脂，加入青椒大火翻炒，放生抽调味后出锅。"

        organized = knowledge.attach_reasons(core.organize(raw, "青椒炒肉"))

        self.assertTrue(organized["steps"])

    def test_empty_local_model_setting_downloads_small_model(self):
        captured = []

        class FakeWhisperModel:
            def __init__(self, source, **kwargs):
                captured.append((source, kwargs))

        fake_module = types.SimpleNamespace(WhisperModel=FakeWhisperModel)
        with patch.dict(sys.modules, {"faster_whisper": fake_module}):
            core.get_whisper_model("")

        self.assertEqual(captured[0][0], "small")


class AppTests(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()
        self.original_db_path = app.DB_PATH
        self.temp_dir = tempfile.TemporaryDirectory()
        app.DB_PATH = os.path.join(self.temp_dir.name, "recipes.db")
        app._init_db()

    def tearDown(self):
        app.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_health_endpoint_is_available(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])

    def test_password_protects_application_but_not_health_check(self):
        with patch.dict(os.environ, {"APP_PASSWORD": "test-password"}):
            self.assertEqual(self.client.get("/").status_code, 401)
            self.assertEqual(self.client.get("/health").status_code, 200)

    def test_recipe_can_be_saved_read_and_deleted(self):
        created = self.client.post("/api/recipes", json={
            "title": "测试菜谱",
            "source": "bilibili",
            "organized": {"ingredients": {}, "steps": ["下锅翻炒"], "tips": []},
        }).get_json()

        recipe_id = created["id"]
        loaded = self.client.get(f"/api/recipes/{recipe_id}").get_json()
        deleted = self.client.delete(f"/api/recipes/{recipe_id}").get_json()

        self.assertTrue(loaded["ok"])
        self.assertEqual(loaded["recipe"]["title"], "测试菜谱")
        self.assertTrue(deleted["ok"])

    def test_config_response_hides_credentials(self):
        config = {
            "openai_api_key": "secret",
            "douyin_cookie": "cookie",
            "stt_api_key": "stt-secret",
            "llm_model": "demo-model",
        }

        safe = app._safe_config(config)

        self.assertEqual(safe["llm_model"], "demo-model")
        self.assertTrue(safe["openai_key_configured"])
        self.assertNotIn("openai_api_key", safe)
        self.assertNotIn("douyin_cookie", safe)
        self.assertNotIn("stt_api_key", safe)

    def test_api_errors_are_generic_and_do_not_leak_exception_text(self):
        response = self.client.post("/api/generate", json={"result": ["bad"]})

        self.assertEqual(response.status_code, 500)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertIn("稍后重试", payload["error"])
        self.assertNotIn("list", payload["error"])

    def test_api_method_not_allowed_preserves_405(self):
        response = self.client.put("/api/search")

        self.assertEqual(response.status_code, 405)
        self.assertFalse(response.get_json()["ok"])

    def test_background_job_errors_are_generic_and_traceable(self):
        job_id = app._new_job(lambda: (_ for _ in ()).throw(ValueError("private failure")))
        payload = None
        for _ in range(20):
            payload = self.client.get(f"/api/job/{job_id}").get_json()
            if payload["status"] == "error":
                break
            time.sleep(0.01)

        self.assertEqual(payload["status"], "error")
        self.assertIn("稍后重试", payload["error"])
        self.assertNotIn("private failure", payload["error"])
        self.assertTrue(payload.get("error_id"))

    def test_deleting_missing_recipe_returns_404(self):
        response = self.client.delete("/api/recipes/999999")

        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.get_json()["ok"])


if __name__ == "__main__":
    unittest.main()
