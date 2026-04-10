"""
Pre-built ElevenAgents tools for LiveKit agents.

Usage:
    from elevenagents_livekit_plugin import elevenagents_tools

    class MyAgent(Agent):
        def __init__(self):
            super().__init__(
                instructions="...",
                tools=[*elevenagents_tools()],
            )

When the agent's LLM calls these tools, they signal back to the bridge
via the lk.chat TextStream topic. The bridge picks up the signal and
includes the tool call in the SSE response back to ElevenAgents Voice Engine.
"""

import json
import logging

from livekit.agents import RunContext, function_tool

logger = logging.getLogger("elevenagents-livekit-plugin.tools")

TOOL_SIGNAL_PREFIX = "__ELEVENAGENTS_TOOL__:"


async def _send_tool_signal(ctx: RunContext, tool_name: str, args: dict) -> None:
    """Send a tool call signal to the bridge via TextStream on lk.chat topic."""
    room = ctx.session.room_io.room
    payload = TOOL_SIGNAL_PREFIX + json.dumps({"tool": tool_name, **args})
    await room.local_participant.send_text(payload, topic="lk.chat")
    logger.info("Sent tool signal: %s", tool_name)


@function_tool(name="end_call")
async def _end_call(
    ctx: RunContext, reason: str, system__message_to_speak: str = ""
) -> str:
    """End the current voice call. Call this when:
    1. The user says goodbye or wants to end the conversation.
    2. The main task has been completed and the user is satisfied.
    3. The conversation has reached a natural conclusion.

    Args:
        reason: Why the call is ending.
        system__message_to_speak: A farewell message to speak before ending.
    """
    await _send_tool_signal(
        ctx,
        "end_call",
        {"reason": reason, "system__message_to_speak": system__message_to_speak},
    )
    return system__message_to_speak if system__message_to_speak else "Ending the call."


@function_tool(name="skip_turn")
async def _skip_turn(ctx: RunContext, reason: str = "") -> str:
    """Skip the agent's turn and wait silently for the user to speak.
    Call this when the user says they need a moment to think, are
    looking something up, or otherwise need a pause.

    Args:
        reason: Why the pause is needed.
    """
    await _send_tool_signal(ctx, "skip_turn", {"reason": reason})
    return ""


@function_tool(name="language_detection")
async def _language_detection(ctx: RunContext, reason: str, language: str) -> str:
    """Switch the conversation language. ONLY call this tool by itself with
    NO text response. ONLY call ONCE when the user FIRST speaks in a different
    language or explicitly requests a language change. Do NOT call again if you
    are already responding in the target language.

    Args:
        reason: Why the language switch is needed.
        language: The language code to switch to (e.g. 'es', 'fr', 'de', 'ja').
    """
    await _send_tool_signal(
        ctx, "language_detection", {"reason": reason, "language": language}
    )
    return ""


def elevenagents_tools() -> list:
    """Return all ElevenAgents tools for use in a LiveKit agent.

    Example:
        class MyAgent(Agent):
            def __init__(self):
                super().__init__(
                    instructions="You are a helpful assistant.",
                    tools=[*elevenagents_tools()],
                )
    """
    return [_end_call, _skip_turn, _language_detection]
