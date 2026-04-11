"""
Sample LiveKit text agent using the ElevenAgents plugin.

This agent works with the ElevenAgents bridge to give your
LiveKit agent voice capabilities through ElevenAgents.

The only changes needed on an existing LiveKit agent are:
  1. Import elevenagents_tools
  2. Add them to your Agent's tools list

Prerequisites:
  pip install livekit-agents livekit-plugins-openai elevenagents-livekit-plugin

Environment variables (.env file):
  LIVEKIT_URL=ws://localhost:7880
  LIVEKIT_API_KEY=your-api-key
  LIVEKIT_API_SECRET=your-api-secret
  OPENAI_API_KEY=your-openai-key

Usage:
  python agent.py dev
"""

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    RunContext,
    cli,
    function_tool,
    room_io,
)
from livekit.plugins import openai
from elevenagents_livekit_plugin import elevenagents_tools  # <-- add this import

load_dotenv()


@function_tool()
async def calculator(ctx: RunContext, expression: str) -> str:
    """Evaluate a math expression. Supports addition, subtraction,
    multiplication, division, and exponentiation.

    Args:
        expression: A math expression to evaluate, e.g. "2 + 3 * 4"
    """
    allowed = set("0123456789+-*/.() ")
    if not all(c in allowed for c in expression):
        return "Error: invalid characters in expression"
    try:
        result = eval(expression)
        return str(result)
    except Exception as e:
        return f"Error: {e}"


class MyAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="You are a helpful assistant. Keep responses short and clear. Use the calculator tool for any math questions.",
            tools=[calculator, *elevenagents_tools()],  # <-- add tools here
        )


server = AgentServer()


@server.rtc_session()
async def entrypoint(ctx: JobContext):
    session = AgentSession(
        llm=openai.LLM(model="gpt-4.1-nano"),
    )

    await session.start(
        agent=MyAgent(),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            text_input=True,
            text_output=True,
            audio_input=False,
            audio_output=False,
        ),
    )

    await session.wait_for_inactive()


if __name__ == "__main__":
    cli.run_app(server)
