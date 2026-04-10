"""
Minimal example: run the ElevenAgents bridge with tool support.

Prerequisites:
  1. LiveKit server running (local or cloud)
  2. LiveKit agent running with elevenagents_tools() registered
  3. .env file with LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET

Usage:
  python basic.py

Then point ElevenAgents custom LLM to:
  http://localhost:8013/v1  (or your ngrok URL + /v1)
"""

from elevenagents_livekit_plugin import ElevenAgentsBridge

bridge = ElevenAgentsBridge(
    room_name="elevenagents-bridge",
    port=8013,
    buffer_words="",
)
bridge.run()
