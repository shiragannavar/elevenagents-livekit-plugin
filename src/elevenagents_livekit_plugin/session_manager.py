"""Manages per-conversation LiveKit rooms and clients."""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field

from .livekit_client import LiveKitClient

logger = logging.getLogger("elevenagents-livekit-plugin.sessions")

# Clean up sessions idle for more than 5 minutes
SESSION_IDLE_TIMEOUT = 300


@dataclass
class Session:
    client: LiveKitClient
    messages: list[dict]
    last_active: float = field(default_factory=time.time)


class SessionManager:
    def __init__(
        self,
        url: str,
        api_key: str,
        api_secret: str,
        room_prefix: str = "elevenagents",
    ):
        self.url = url
        self.api_key = api_key
        self.api_secret = api_secret
        self.room_prefix = room_prefix
        self._sessions: dict[str, Session] = {}
        self._cleanup_task: asyncio.Task | None = None

    def _start_cleanup(self) -> None:
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.ensure_future(self._cleanup_loop())

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            now = time.time()
            expired = [
                sid for sid, s in self._sessions.items()
                if now - s.last_active > SESSION_IDLE_TIMEOUT
            ]
            for sid in expired:
                session = self._sessions.pop(sid)
                await session.client.disconnect()
                logger.info("Cleaned up idle session %s", sid)

    def _is_continuation(self, old_msgs: list[dict], new_msgs: list[dict]) -> bool:
        """Check if new_msgs is a continuation of old_msgs."""
        if len(new_msgs) <= len(old_msgs):
            return False
        for old, new in zip(old_msgs, new_msgs):
            if old.get("role") != new.get("role"):
                return False
            if old.get("content") != new.get("content"):
                return False
        return True

    async def get_client(self, messages: list[dict]) -> LiveKitClient:
        """Find an existing session or create a new one."""
        self._start_cleanup()

        # Try to match to an existing conversation
        for sid, session in self._sessions.items():
            if self._is_continuation(session.messages, messages):
                session.messages = messages
                session.last_active = time.time()
                logger.info("Matched session %s (%d messages)", sid, len(messages))
                return session.client

        # New conversation -- create a new room
        sid = uuid.uuid4().hex[:8]
        room_name = f"{self.room_prefix}-{sid}"
        identity = f"bridge-{sid}"

        client = LiveKitClient(
            url=self.url,
            api_key=self.api_key,
            api_secret=self.api_secret,
            room_name=room_name,
            identity=identity,
        )
        await client.connect()

        self._sessions[sid] = Session(
            client=client,
            messages=messages,
        )
        logger.info(
            "New session %s in room '%s' (%d messages)",
            sid, room_name, len(messages),
        )
        return client

    @property
    def active_count(self) -> int:
        return len(self._sessions)

    async def close_all(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()
        for session in self._sessions.values():
            await session.client.disconnect()
        self._sessions.clear()
