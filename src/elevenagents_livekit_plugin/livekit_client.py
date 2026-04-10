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
    """An event in the response stream — either a text chunk or a tool call."""

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
        self._response_queue: asyncio.Queue[Optional[StreamEvent]] = asyncio.Queue()
        self._connected = False

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
            # Skip our own messages (echo from send_text)
            if participant_identity == self.identity:
                return
            logger.debug("Stream from %s", participant_identity)
            asyncio.ensure_future(self._handle_stream(reader))

        self.room.register_text_stream_handler("lk.chat", on_stream)
        self.room.register_text_stream_handler("lk.transcription", on_stream)

        token = self._generate_token()
        await self.room.connect(self.url, token)
        self._connected = True
        logger.info(
            "Connected to room '%s' as '%s'", self.room_name, self.identity
        )
        await self._dispatch_agent()

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

    async def _handle_stream(self, reader: TextStreamReader) -> None:
        """Handle a text stream — detect tool signals, otherwise stream text."""
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
                await self._response_queue.put(
                    StreamEvent(type="text", content=chunk)
                )

        if is_tool:
            full = "".join(tool_chunks)
            json_str = full[len(TOOL_SIGNAL_PREFIX):]
            try:
                data = json.loads(json_str)
                tool_name = data.pop("tool")
                await self._response_queue.put(
                    StreamEvent(type="tool_call", tool_name=tool_name, tool_args=data)
                )
                logger.info("Tool call: %s", tool_name)
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("Bad tool signal: %s", e)
        else:
            # Text stream done
            await self._response_queue.put(None)

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
        """Send text to the agent and yield streamed response events."""
        if not self._connected or self.room is None:
            raise RuntimeError("Not connected to LiveKit room")

        await self._ensure_agent_in_room()

        # Drain stale events
        while not self._response_queue.empty():
            self._response_queue.get_nowait()

        await self.room.local_participant.send_text(text, topic="lk.chat")
        logger.info("Sent: %s", text[:100])

        text_done = False
        while True:
            try:
                wait = tool_wait if text_done else timeout
                event = await asyncio.wait_for(
                    self._response_queue.get(), timeout=wait
                )
            except asyncio.TimeoutError:
                break
            if event is None:
                text_done = True
                continue
            yield event

    async def disconnect(self) -> None:
        if self.room:
            await self.room.disconnect()
            self._connected = False
            logger.info("Disconnected from room")
