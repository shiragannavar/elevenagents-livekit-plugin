"""Main entry point -- wires up the session manager and HTTP server."""

import asyncio
import logging
import os

import uvicorn
from dotenv import load_dotenv

from .session_manager import SessionManager
from .server import create_app

logger = logging.getLogger("elevenagents-livekit-plugin")


class ElevenAgentsBridge:
    def __init__(
        self,
        *,
        livekit_url: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        room_name: str = "elevenagents",
        port: int = 8013,
        host: str = "0.0.0.0",
        buffer_words: str = "... ",
    ):
        load_dotenv()

        self.livekit_url = livekit_url or os.getenv("LIVEKIT_URL", "")
        self.api_key = api_key or os.getenv("LIVEKIT_API_KEY", "")
        self.api_secret = api_secret or os.getenv("LIVEKIT_API_SECRET", "")
        self.room_prefix = room_name
        self.port = port
        self.host = host

        if not all([self.livekit_url, self.api_key, self.api_secret]):
            raise ValueError(
                "LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET must be "
                "set via arguments or environment variables."
            )

        self.session_mgr = SessionManager(
            url=self.livekit_url,
            api_key=self.api_key,
            api_secret=self.api_secret,
            room_prefix=self.room_prefix,
        )
        self.app = create_app(self.session_mgr, buffer_words=buffer_words)

    def run(self) -> None:
        """Start the bridge as a standalone process (blocking)."""
        asyncio.run(self._run())

    def embed(self, agent_server) -> None:
        """Embed the bridge into a LiveKit AgentServer.

        Call this before cli.run_app(). The bridge will start automatically
        when the agent worker starts, so only one process is needed.

        Usage:
            server = AgentServer()
            bridge = ElevenAgentsBridge(...)
            bridge.embed(server)
            cli.run_app(server)
        """
        @agent_server.once("worker_started")
        def _on_worker_started():
            asyncio.ensure_future(self._run())

    async def _run(self) -> None:
        logger.info(
            "Bridge starting (room prefix: '%s')", self.room_prefix
        )

        # Start HTTP server (log_config=None preserves our logging setup)
        config = uvicorn.Config(
            self.app, host=self.host, port=self.port, log_level="info",
            log_config=None,
        )
        server = uvicorn.Server(config)

        logger.info("Starting server on %s:%d", self.host, self.port)
        logger.info(
            "ElevenAgents custom LLM endpoint: http://%s:%d/v1",
            self.host,
            self.port,
        )

        try:
            await server.serve()
        finally:
            await self.session_mgr.close_all()
