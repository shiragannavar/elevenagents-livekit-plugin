"""Main entry point — wires up the LiveKit client and HTTP server."""

import asyncio
import logging
import os

import uvicorn
from dotenv import load_dotenv

from .livekit_client import LiveKitClient
from .server import create_app

logger = logging.getLogger("elevenagents-livekit-plugin")


class ElevenAgentsBridge:
    def __init__(
        self,
        *,
        livekit_url: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        room_name: str = "elevenagents-bridge",
        identity: str = "elevenagents-bridge",
        port: int = 8013,
        host: str = "0.0.0.0",
        buffer_words: str = "... ",
    ):
        load_dotenv()

        self.livekit_url = livekit_url or os.getenv("LIVEKIT_URL", "")
        self.api_key = api_key or os.getenv("LIVEKIT_API_KEY", "")
        self.api_secret = api_secret or os.getenv("LIVEKIT_API_SECRET", "")
        self.room_name = room_name
        self.identity = identity
        self.port = port
        self.host = host

        if not all([self.livekit_url, self.api_key, self.api_secret]):
            raise ValueError(
                "LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET must be "
                "set via arguments or environment variables."
            )

        self.lk_client = LiveKitClient(
            url=self.livekit_url,
            api_key=self.api_key,
            api_secret=self.api_secret,
            room_name=self.room_name,
            identity=self.identity,
        )
        self.app = create_app(self.lk_client, buffer_words=buffer_words)

    def run(self) -> None:
        """Start the bridge (blocking)."""
        asyncio.run(self._run())

    async def _run(self) -> None:
        # Connect to LiveKit room
        await self.lk_client.connect()
        logger.info(
            "Bridge connected to LiveKit at %s, room '%s'",
            self.livekit_url,
            self.room_name,
        )

        # Start HTTP server
        config = uvicorn.Config(
            self.app, host=self.host, port=self.port, log_level="info"
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
            await self.lk_client.disconnect()
