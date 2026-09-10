"""No-network smoke test for the public release."""
import app
import core
import knowledge


def check(condition, message):
    if not condition:
        raise AssertionError(message)


client = app.app.test_client()
info = client.get("/api/info").get_json()
check(info and info.get("ok"), "/api/info should be available")

safe_config = app._safe_config({"openai_api_key": "secret", "douyin_cookie": "cookie", "llm_model": "demo"})
check(safe_config.get("llm_model") == "demo", "Non-sensitive configuration should remain available")
check(safe_config.get("openai_key_configured") is True, "Key configuration state should be available")
check("openai_api_key" not in safe_config and "douyin_cookie" not in safe_config,
      "Sensitive configuration must not reach the browser")

parsed = core.parse_video_input("https://www.bilibili.com/video/BV1oro6YxEmu")
check(parsed.get("ok") and parsed.get("source") == "bilibili", "Bilibili URL parsing failed")

raw = "五花肉切片。热锅下五花肉煸出油脂，加入青椒大火翻炒，放生抽调味后出锅。"
organized = knowledge.attach_reasons(core.organize(raw, "青椒炒肉"))
check(organized.get("steps"), "Recipe organization should produce steps")

print("Smoke test passed.")
