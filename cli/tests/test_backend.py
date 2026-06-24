import os
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

from paper2product.backend import (
    AGENTICA_BACKEND,
    OPENAI_COMPATIBLE_BACKEND,
    OpenAICompatibleBackend,
    get_execution_backend_name,
    normalize_model_name,
)
from paper2product.errors import AgentExecutionError


class BackendSelectionTests(unittest.TestCase):
    def test_normalize_model_name_removes_openrouter_prefix(self):
        self.assertEqual(
            normalize_model_name("openrouter:google/gemini-2.5-pro"),
            "google/gemini-2.5-pro",
        )

    def test_execution_backend_defaults_to_agentica_without_direct_key(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(get_execution_backend_name(), AGENTICA_BACKEND)

    def test_execution_backend_prefers_openai_compatible_with_direct_key(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "key"}, clear=True):
            self.assertEqual(get_execution_backend_name(), OPENAI_COMPATIBLE_BACKEND)


class OpenAICompatibleBackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_text_raises_when_key_missing(self):
        backend = OpenAICompatibleBackend(
            base_url="https://openrouter.ai/api/v1",
            api_key="",
            timeout_seconds=30.0,
        )
        with self.assertRaises(AgentExecutionError):
            await backend.generate_text(
                system_prompt="system",
                user_prompt="user",
                model="anthropic/claude-sonnet-4",
                phase="test",
            )

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_generate_text_parses_openai_compatible_response(self, mock_post):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "hello world",
                    }
                }
            ]
        }
        mock_post.return_value = response

        backend = OpenAICompatibleBackend(
            base_url="https://openrouter.ai/api/v1",
            api_key="key",
            timeout_seconds=30.0,
        )
        text = await backend.generate_text(
            system_prompt="system",
            user_prompt="user",
            model="anthropic/claude-sonnet-4",
            phase="test",
        )
        self.assertEqual(text, "hello world")

    @patch("httpx.AsyncClient.post", new_callable=AsyncMock)
    async def test_generate_text_surfaces_http_error_details(self, mock_post):
        request = httpx.Request("POST", "https://gen.pollinations.ai/v1/chat/completions")
        response = httpx.Response(
            400,
            request=request,
            json={"error": "Unknown model"},
        )
        mock_post.return_value = response

        backend = OpenAICompatibleBackend(
            base_url="https://gen.pollinations.ai/v1",
            api_key="key",
            timeout_seconds=30.0,
        )
        with self.assertRaises(AgentExecutionError) as ctx:
            await backend.generate_text(
                system_prompt="system",
                user_prompt="user",
                model="anthropic/claude-sonnet-4",
                phase="technical primitive extraction",
            )

        message = str(ctx.exception)
        self.assertIn("gen.pollinations.ai", message)
        self.assertIn("Unknown model", message)
        self.assertIn("provider-native model name", message)


if __name__ == "__main__":
    unittest.main()
