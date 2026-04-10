"""Converts LiveKit text chunks and tool calls into OpenAI-compatible SSE format."""

import json
import time
import uuid


def _make_id() -> str:
    return f"chatcmpl-{uuid.uuid4().hex[:12]}"


def format_chunk(content: str, model: str = "livekit-agent") -> str:
    """Format a text chunk as an OpenAI chat completion SSE chunk."""
    chunk = {
        "id": _make_id(),
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"content": content},
                "finish_reason": None,
            }
        ],
    }
    return f"data: {json.dumps(chunk)}\n\n"


def format_first_chunk(model: str = "livekit-agent") -> str:
    """Format the initial SSE chunk with the role."""
    chunk = {
        "id": _make_id(),
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": ""},
                "finish_reason": None,
            }
        ],
    }
    return f"data: {json.dumps(chunk)}\n\n"


def format_tool_call(tool_name: str, tool_args: dict, model: str = "livekit-agent") -> str:
    """Format a tool call as an OpenAI chat completion SSE chunk."""
    chunk = {
        "id": _make_id(),
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": f"call_{uuid.uuid4().hex[:8]}",
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(tool_args),
                            },
                        }
                    ]
                },
                "finish_reason": None,
            }
        ],
    }
    return f"data: {json.dumps(chunk)}\n\n"


def format_done_chunk(model: str = "livekit-agent") -> str:
    """Format the final SSE chunk with finish_reason=stop."""
    chunk = {
        "id": _make_id(),
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }
        ],
    }
    return f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n"
