import asyncio
import logging

from dotenv import load_dotenv
from livekit.agents import JobContext, JobRequest, WorkerOptions, cli
from livekit.agents.voice_assistant import VoiceAssistant
from livekit.plugins import deepgram, elevenlabs

from demospace.livekit import claude, silero
from demospace.utils.env import is_prod

if is_prod():
  load_dotenv(".env.local")


# This function is the entrypoint for the agent.
async def entrypoint(ctx: JobContext):
  # VoiceAssistant is a class that creates a full conversational AI agent.
  # See https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice_assistant/assistant.py
  # for details on how it works.
  assistant = VoiceAssistant(
    vad=silero.VAD(
      min_silence_duration=1.0,
    ),  # Voice Activity Detection
    stt=deepgram.STT(),  # Speech-to-Text
    llm=claude.LLM(
      room=ctx.room,
    ),  # Language Model
    tts=elevenlabs.TTS(),  # Text-to-Speech
  )

  # Start the voice assistant with the LiveKit room
  assistant.start(ctx.room)

  await asyncio.sleep(1)

  # Greets the user with an initial message
  await assistant.say(
    "Hi there! I'm Demi, here to share more about Otter AI and answer any questions. First of all, I'd love to learn a bit more about your use case. Could you share what you're hoping to accomplish with Otter AI?",
    allow_interruptions=True,
  )


# This function is called when the worker receives a job request
# from a LiveKit server.
async def request_fnc(req: JobRequest) -> None:
  logging.info("received request %s", req)
  # Accept the job tells the LiveKit server that this worker
  # wants the job. After the LiveKit server acknowledges that job is accepted,
  # the entrypoint function is called.
  await req.accept(entrypoint)


if __name__ == "__main__":
  # Initialize the worker with the request function
  cli.run_app(WorkerOptions(request_fnc))
