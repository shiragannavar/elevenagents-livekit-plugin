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
    cli,
    room_io,
)
from livekit.plugins import openai
from elevenagents_livekit_plugin import elevenagents_tools  # <-- add this import

load_dotenv()


class MyAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="You are a helpful assistant. Keep responses short and clear.",
            tools=[*elevenagents_tools()],  # <-- add tools here
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
