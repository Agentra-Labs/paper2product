import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from paper2product.errors import AgenticaConnectionError


class SpawnAgentTests(unittest.IsolatedAsyncioTestCase):
    """Tests for spawn_agent timeout and connection error paths."""

    @patch("paper2product.pipeline.spawn")
    async def test_spawn_agent_raises_on_asyncio_timeout(self, mock_spawn):
        """Hanging backend connections should raise AgenticaConnectionError."""
        from paper2product.pipeline import spawn_agent

        async def hang_forever(**kwargs):
            await asyncio.sleep(9999)

        mock_spawn.side_effect = hang_forever

        with patch("paper2product.pipeline.SPAWN_TIMEOUT_SECONDS", 0.1):
            with self.assertRaises(AgenticaConnectionError) as ctx:
                await spawn_agent(premise="test", model="test-model")
            self.assertIn("Timed out after", str(ctx.exception))

    @patch("paper2product.pipeline.spawn")
    async def test_spawn_agent_raises_on_httpx_timeout(self, mock_spawn):
        """httpx.TimeoutException during spawn should be wrapped."""
        from paper2product.pipeline import spawn_agent

        mock_spawn.side_effect = httpx.TimeoutException("connect timeout")

        with self.assertRaises(AgenticaConnectionError) as ctx:
            await spawn_agent(premise="test", model="test-model")
        self.assertIn("Timed out while connecting", str(ctx.exception))

    @patch("paper2product.pipeline.spawn")
    async def test_spawn_agent_raises_on_httpx_http_error(self, mock_spawn):
        """General httpx.HTTPError during spawn should be wrapped."""
        from paper2product.pipeline import spawn_agent

        mock_spawn.side_effect = httpx.HTTPError("503 Service Unavailable")

        with self.assertRaises(AgenticaConnectionError) as ctx:
            await spawn_agent(premise="test", model="test-model")
        self.assertIn("Agentica request failed", str(ctx.exception))

    @patch("paper2product.pipeline.spawn")
    async def test_spawn_agent_disables_listener_by_default(self, mock_spawn):
        """Listener should be set to None when ENABLE_AGENT_LOGS is off."""
        from paper2product.pipeline import spawn_agent

        mock_spawn.return_value = MagicMock()

        with patch.dict("os.environ", {"ENABLE_AGENT_LOGS": "0"}, clear=False):
            await spawn_agent(premise="test", model="test-model")

        _, kwargs = mock_spawn.call_args
        self.assertIsNone(kwargs.get("listener"))

    @patch("paper2product.pipeline.spawn")
    async def test_spawn_agent_keeps_listener_when_logs_enabled(self, mock_spawn):
        """Listener should NOT be forced to None when logs are enabled."""
        from paper2product.pipeline import spawn_agent

        mock_spawn.return_value = MagicMock()

        with patch.dict("os.environ", {"ENABLE_AGENT_LOGS": "1"}, clear=False):
            await spawn_agent(premise="test", model="test-model")

        _, kwargs = mock_spawn.call_args
        self.assertNotIn("listener", kwargs)


class CallAgentTextTeardownTests(unittest.IsolatedAsyncioTestCase):
    """Tests for graceful agent teardown in call_agent_text."""

    async def test_call_agent_text_calls_close_on_success(self):
        """Agent.close() should be called even on the happy path."""
        from paper2product.pipeline import call_agent_text

        agent = AsyncMock()
        agent.call.return_value = "result"
        agent.close = AsyncMock()

        result = await call_agent_text(agent, "prompt", phase="test")
        self.assertEqual(result, "result")
        agent.close.assert_awaited_once()

    async def test_call_agent_text_calls_close_on_failure(self):
        """Agent.close() should be attempted even when the call fails."""
        from paper2product.errors import AgentExecutionError
        from paper2product.pipeline import call_agent_text

        agent = AsyncMock()
        agent.call.side_effect = asyncio.TimeoutError()
        agent.close = AsyncMock()

        with self.assertRaises(AgentExecutionError):
            await call_agent_text(agent, "prompt", phase="test")

        agent.close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
