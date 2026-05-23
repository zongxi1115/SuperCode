import tempfile
import unittest
from pathlib import Path

from agent import AgentLLMConfig
from fastapi_app import main as api_main
from fastapi_app.model_config_store import (
    build_agent_config,
    list_model_options,
    save_ui_model_providers,
    scan_env_model_sources,
)


class ModelConfigStoreTests(unittest.TestCase):
    def test_scan_env_and_ui_model_sources_can_coexist(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="supercode-model-config-")).resolve()
        (root / ".env").write_text(
            "\n".join(
                [
                    "SC_AGENT_API_KEY=env-key",
                    "SC_AGENT_BASE_URL=https://api.openai.com/v1",
                    "SC_AGENT_MODEL=gpt-4.1",
                ]
            ),
            encoding="utf-8",
        )
        save_ui_model_providers(
            root,
            [
                {
                    "id": "provider-a",
                    "name": "OpenRouter",
                    "baseUrl": "https://openrouter.ai/api/v1",
                    "apiKey": "router-key",
                    "models": ["openai/gpt-4.1-mini"],
                }
            ],
        )

        env_sources = scan_env_model_sources(root)
        all_models = list_model_options(root)

        self.assertEqual(env_sources[0]["envFile"], "env::.env")
        self.assertEqual(len(all_models), 2)
        self.assertTrue(any(item["id"] == "ui::provider-a::openai/gpt-4.1-mini" for item in all_models))

    def test_build_agent_config_supports_ui_provider(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="supercode-ui-provider-")).resolve()
        save_ui_model_providers(
            root,
            [
                {
                    "id": "provider-a",
                    "name": "OpenRouter",
                    "baseUrl": "https://openrouter.ai/api/v1",
                    "apiKey": "router-key",
                    "models": ["openai/gpt-4.1-mini"],
                }
            ],
        )

        config, model_ref = build_agent_config(root, "ui::provider-a::openai/gpt-4.1-mini")

        self.assertIsInstance(config, AgentLLMConfig)
        self.assertEqual(config.model, "openai/gpt-4.1-mini")
        self.assertEqual(config.base_url, "https://openrouter.ai/api/v1")
        self.assertEqual(model_ref, "ui::provider-a::openai/gpt-4.1-mini")

    def test_resolve_model_reference_id_prefers_env_file_for_duplicate_names(self) -> None:
        original_root = api_main.ROOT
        root = Path(tempfile.mkdtemp(prefix="supercode-duplicate-model-")).resolve()
        (root / ".env.1").write_text(
            "\n".join(
                [
                    "SC_AGENT_API_KEY=env-key",
                    "SC_AGENT_BASE_URL=https://api.deepseek.com",
                    "SC_AGENT_MODEL=deepseek-v4-pro",
                ]
            ),
            encoding="utf-8",
        )
        save_ui_model_providers(
            root,
            [
                {
                    "id": "lzhan",
                    "name": "Lzhan",
                    "baseUrl": "https://lzhan.example/v1",
                    "apiKey": "lzhan-key",
                    "models": ["deepseek-v4-pro"],
                }
            ],
        )

        try:
            api_main.ROOT = root
            model_id = api_main.resolve_model_reference_id(
                "deepseek-v4-pro",
                "ui::lzhan::deepseek-v4-pro",
            )
        finally:
            api_main.ROOT = original_root

        self.assertEqual(model_id, "ui::lzhan::deepseek-v4-pro")


if __name__ == "__main__":
    unittest.main()
