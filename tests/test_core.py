import sys
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

    def test_health_endpoint_is_available(self):
        response = self.client.get("/api/info")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])

    def test_config_response_hides_credentials(self):
        config = {
            "openai_api_key": "secret",
            "douyin_cookie": "cookie",
            "stt_api_key": "stt-secret",
            "llm_model": "demo-model",
        }

        self.assertEqual(app._safe_config(config), {"llm_model": "demo-model"})


if __name__ == "__main__":
    unittest.main()
