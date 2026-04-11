"""FastAPI server exposing an OpenAI-compatible /v1/chat/completions endpoint."""

import json
import logging

import fastapi
from fastapi.responses import StreamingResponse

from .adapter import format_chunk, format_done_chunk, format_first_chunk, format_tool_call
from .session_manager import SessionManager

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("elevenagents-livekit-plugin.server")


def extract_text(content) -> str:
    """Extract text from content that may be a string or a list of content parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(part.get("text", ""))
            elif isinstance(part, str):
                parts.append(part)
        return " ".join(parts)
    return str(content) if content else ""


DEFAULT_BUFFER_WORDS = "... "


def create_app(session_mgr: SessionManager, buffer_words: str = DEFAULT_BUFFER_WORDS) -> fastapi.FastAPI:
    app = fastapi.FastAPI(title="ElevenAgents LiveKit Plugin")

    @app.post("/v1/chat/completions")
    async def chat_completions(request: fastapi.Request) -> StreamingResponse:
        body = await request.json()
        logger.debug("Incoming request body: %s", json.dumps(body, indent=2))

        messages = body.get("messages", [])
        if not messages:
            return fastapi.responses.JSONResponse(
                {"error": "No messages provided"}, status_code=400
            )

        # Extract the latest user message (content can be string or list)
        user_message = None
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_message = extract_text(msg.get("content", ""))
                break

        if not user_message:
            return fastapi.responses.JSONResponse(
                {"error": "No user message found"}, status_code=400
            )

        logger.debug("Extracted user message: %s", user_message)
        model = body.get("model", "livekit-agent")

        # Get or create a session for this conversation
        lk_client = await session_mgr.get_client(messages)

        async def event_stream():
            yield format_first_chunk(model)
            # Send buffer words immediately so ElevenAgents doesn't time out
            if buffer_words:
                yield format_chunk(buffer_words, model)
            try:
                async for event in lk_client.send_and_stream(user_message):
                    if event.type == "text":
                        yield format_chunk(event.content, model)
                    elif event.type == "tool_call":
                        yield format_tool_call(
                            event.tool_name, event.tool_args, model
                        )
                        logger.info(
                            "Forwarding tool call to ElevenAgents: %s",
                            event.tool_name,
                        )
                yield format_done_chunk(model)
            except Exception as e:
                logger.error("Error streaming response: %s", str(e))
                yield format_chunk(f"Error: {str(e)}", model)
                yield format_done_chunk(model)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.get("/health")
    async def health():
        return {"status": "ok", "active_sessions": session_mgr.active_count}

    return app
