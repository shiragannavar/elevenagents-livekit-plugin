"""Connects to a LiveKit room and relays text to/from the agent."""

import asyncio
import datetime
import json
import logging
from dataclasses import dataclass
from typing import AsyncGenerator, Optional

from livekit.api import AccessToken, LiveKitAPI, VideoGrants
from livekit.protocol import agent_dispatch
from livekit.rtc import Room, TextStreamReader

from .tools import TOOL_SIGNAL_PREFIX

logger = logging.getLogger("elevenagents-livekit-plugin.client")


@dataclass
class StreamEvent:
    """An event in the response stream -- either a text chunk or a tool call."""

    type: str  # "text" or "tool_call"
    content: str = ""
    tool_name: str = ""
    tool_args: dict = None

    def __post_init__(self):
        if self.tool_args is None:
            self.tool_args = {}


class LiveKitClient:
    def __init__(
        self,
        url: str,
        api_key: str,
        api_secret: str,
        room_name: str = "elevenagents-bridge",
        identity: str = "elevenagents-bridge",
    ):
        self.url = url
        self.api_key = api_key
        self.api_secret = api_secret
        self.room_name = room_name
        self.identity = identity
        self.room: Optional[Room] = None
        self._connected = False
        self._pending_readers: asyncio.Queue[tuple[TextStreamReader, str]] = asyncio.Queue()

    def _generate_token(self) -> str:
        token = AccessToken(
            api_key=self.api_key,
            api_secret=self.api_secret,
        )
        token.with_identity(self.identity)
        token.with_grants(
            VideoGrants(
                room_join=True,
                room=self.room_name,
                can_publish=True,
                can_subscribe=True,
            )
        )
        token.with_ttl(datetime.timedelta(hours=24))
        return token.to_jwt()

    async def connect(self) -> None:
        """Connect to the LiveKit room and register text stream handlers."""
        self.room = Room()

        def on_stream(reader: TextStreamReader, participant_identity: str) -> None:
            if participant_identity == self.identity:
                return
            logger.info("Queuing reader from %s", participant_identity)
            self._pending_readers.put_nowait((reader, participant_identity))

        self.room.register_text_stream_handler("lk.transcription", on_stream)
        logger.info("Registered lk.transcription handler")

        token = self._generate_token()
        await self.room.connect(self.url, token)
        self._connected = True
        logger.info(
            "Connected to room '%s' as '%s'", self.room_name, self.identity
        )
        # Only dispatch if no agent is already in the room
        has_agent = any(
            p.kind == 4 for p in self.room.remote_participants.values()
        )
        if not has_agent:
            await self._dispatch_agent()
        else:
            logger.info("Agent already in room, skipping dispatch")

    async def _dispatch_agent(self) -> None:
        """Dispatch a LiveKit agent to join this room."""
        http_url = self.url.replace("ws://", "http://").replace("wss://", "https://")
        api = LiveKitAPI(http_url, self.api_key, self.api_secret)
        try:
            await api.agent_dispatch.create_dispatch(
                agent_dispatch.CreateAgentDispatchRequest(room=self.room_name)
            )
            logger.info("Dispatched agent to room '%s'", self.room_name)
        except Exception as e:
            logger.warning("Failed to dispatch agent: %s", e)
        finally:
            await api.aclose()

    async def _ensure_agent_in_room(self) -> None:
        """Re-dispatch agent if none present."""
        for p in self.room.remote_participants.values():
            if p.kind == 4:
                return
        logger.info("No agent in room, re-dispatching...")
        await self._dispatch_agent()
        for _ in range(20):
            await asyncio.sleep(0.5)
            for p in self.room.remote_participants.values():
                if p.kind == 4:
                    logger.info("Agent joined: %s", p.identity)
                    return
        logger.warning("Agent did not join after re-dispatch")

    async def send_and_stream(
        self, text: str, timeout: float = 30.0, tool_wait: float = 0.5
    ) -> AsyncGenerator[StreamEvent, None]:
        """Send text to the agent and yield streamed response events.

        Only accepts responses from the first agent that replies.
        Duplicate responses from other agents in the room are ignored.
        """
        if not self._connected or self.room is None:
            raise RuntimeError("Not connected to LiveKit room")

        await self._ensure_agent_in_room()

        # Drain stale readers
        while not self._pending_readers.empty():
            self._pending_readers.get_nowait()

        await self.room.local_participant.send_text(text, topic="lk.chat")
        logger.info("Sent: %s", text[:100])

        got_any = False
        accepted_agent: str | None = None
        while True:
            try:
                wait = tool_wait if got_any else timeout
                reader, agent_id = await asyncio.wait_for(
                    self._pending_readers.get(), timeout=wait
                )
            except asyncio.TimeoutError:
                break

            # Only accept responses from the first agent that replies
            if accepted_agent is None:
                accepted_agent = agent_id
            elif agent_id != accepted_agent:
                logger.debug("Ignoring duplicate from %s", agent_id)
                continue

            got_any = True

            # Stream chunks from this reader. Check the first chunk
            # to decide if it's a tool signal or text.
            first = True
            is_tool = False
            tool_chunks: list[str] = []

            async for chunk in reader:
                if first:
                    first = False
                    if chunk.startswith(TOOL_SIGNAL_PREFIX):
                        is_tool = True
                        tool_chunks.append(chunk)
                        continue
                if is_tool:
                    tool_chunks.append(chunk)
                else:
                    yield StreamEvent(type="text", content=chunk)

            if is_tool:
                full = "".join(tool_chunks)
                json_str = full[len(TOOL_SIGNAL_PREFIX):]
                try:
                    data = json.loads(json_str)
                    tool_name = data.pop("tool")
                    yield StreamEvent(
                        type="tool_call",
                        tool_name=tool_name,
                        tool_args=data,
                    )
                    logger.info("Tool call: %s", tool_name)
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning("Bad tool signal: %s", e)

    async def disconnect(self) -> None:
        if self.room:
            await self.room.disconnect()
            self._connected = False
            logger.info("Disconnected from room")
