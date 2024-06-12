from __future__ import annotations

import asyncio
from typing import Literal, MutableSet, Optional

import openai
from attrs import define
from livekit import rtc
from livekit.agents import llm

from demospace.openai.functions import send_asset

ChatModels = Literal[
  "gpt-4o",
  "gpt-4o-2024-05-13",
  "gpt-4-turbo",
  "gpt-4-turbo-2024-04-09",
  "gpt-4-turbo-preview",
  "gpt-4-0125-preview" "gpt-4-1106-preview",
  "gpt-4-vision-preview",
  "gpt-4-1106-vision-preview",
  "gpt-4",
  "gpt-4-0314",
  "gpt-4-0613",
  "gpt-4-32k",
  "gpt-4-32k-0314",
  "gpt-4-32k-0613",
  "gpt-3.5-turbo",
  "gpt-3.5-turbo-16k",
  "gpt-3.5-turbo-0301",
  "gpt-3.5-turbo-0613",
  "gpt-3.5-turbo-1106",
  "gpt-3.5-turbo-16k-0613",
]


@define
class LLMOptions:
  model: str | ChatModels


class LLM(llm.LLM):
  def __init__(
    self,
    *,
    assistant_id: str,
    model: str | ChatModels = "gpt-4o",
    client: openai.AsyncClient | None = None,
    room: rtc.Room,
  ) -> None:
    self.assistant_id = assistant_id
    self._opts = LLMOptions(model=model)
    self._client = client or openai.AsyncClient()
    self._running_fncs: MutableSet[asyncio.Task] = set()
    self._thread: openai.Thread = None
    self._active_run: openai.Run = None
    self._room: rtc.Room = room

  async def _cancel_active_runs(self) -> None:
    try:
      if self._active_run is not None:
        await self._client.beta.threads.runs.cancel(
          thread_id=self._thread.id, run_id=self._active_run.id
        )
        self._active_run = None

    except openai.APIError as e:
      if e.message == "Cannot cancel run with status 'cancelling'.":
        self._active_run = None
      print(f"Error cancelling run: {e}")

  async def _add_messages_and_get_thread(
    self, history: llm.ChatContext
  ) -> openai.Thread:
    if self._thread is not None:
      message_added = False
      while not message_added:
        try:
          await self._cancel_active_runs()

          # Add the latest message to the thread and return it
          latest_msg = history.messages[-1]
          await self._client.beta.threads.messages.create(
            thread_id=self._thread.id,
            content=latest_msg.text,
            role=latest_msg.role.value,
          )
          message_added = True
        except openai.APIError as e:
          if "is active" in e.message:
            try:
              run_id = e.message.split(" ")[14]
              await self._client.beta.threads.runs.cancel(
                thread_id=self._thread.id, run_id=run_id
              )
            except openai.APIError as e:
              print(f"Failed cancelling run: {e}")
          print(f"Failed adding message: {e}, retrying...")
      return self._thread
    else:
      self._thread = await self._client.beta.threads.create(
        messages=to_openai_ctx(history),
      )
      return self._thread

  def _add_chunk_to_stream(
    self, llm_stream: LLMStream, chunk: openai.ThreadMessageDelta
  ) -> None:
    choice = chunk.data.delta.content[0]
    llm_stream.push_text(
      llm.ChatChunk(
        choices=[
          llm.Choice(
            delta=llm.ChoiceDelta(
              content=choice.text.value,
              role=chunk.data.delta.role,
            ),
            index=0,
          )
        ]
      )
    )

  async def _handle_response_stream(
    self, stream: openai.AsyncAssistantEventHandler, llm_stream: LLMStream
  ) -> None:
    async for chunk in stream:
      self._active_run = stream.current_run
      if chunk.event == "thread.message.delta":
        self._add_chunk_to_stream(llm_stream, chunk)
      elif chunk.event == "thread.run.completed":
        self._active_run = None
        llm_stream.push_text(None)
      elif chunk.event == "thread.run.requires_action":
        tool_calls = chunk.data.required_action.submit_tool_outputs.tool_calls
        outputs = []
        for tool_call in tool_calls:
          match tool_call.function.name:
            case "send_asset":
              print(f"Sending asset: {tool_call.function.arguments}")
              await send_asset(tool_call.function.arguments, self._room)
              outputs.append({"tool_call_id": tool_call.id, "output": "OK"})
            case _:
              print(f"Unrecognized function name: {tool_call.function.name}")
              continue
        async with self._client.beta.threads.runs.submit_tool_outputs_stream(
          thread_id=self._thread.id,
          run_id=self._active_run.id,
          tool_outputs=outputs,
        ) as new_stream:
          await self._handle_response_stream(new_stream, llm_stream)

  async def chat(
    self,
    history: llm.ChatContext,
    fnc_ctx: llm.FunctionContext | None = None,
    temperature: float | None = None,
    n: int | None = None,
  ) -> "LLMStream":
    thread = await self._add_messages_and_get_thread(history)
    llm_stream = LLMStream()
    stream: openai.AsyncAssistantEventHandler
    async with self._client.beta.threads.runs.stream(
      thread_id=thread.id,
      assistant_id=self.assistant_id,
      model=self._opts.model,
      temperature=temperature,
    ) as stream:
      await self._handle_response_stream(stream, llm_stream)

    return llm_stream


class LLMStream(llm.LLMStream):
  def __init__(self) -> None:
    super().__init__()
    self._event_queue = asyncio.Queue[Optional[str]]()
    self._closed = False
    self._running_fncs: MutableSet[asyncio.Task] = set()

  def push_text(self, text: llm.ChatChunk) -> None:
    if self._closed:
      raise ValueError("cannot push text to a closed stream")

    self._event_queue.put_nowait(text)

  def __aiter__(self) -> "LLMStream":
    return self

  async def __anext__(self) -> llm.ChatChunk:
    event = await self._event_queue.get()
    if event is None:
      raise StopAsyncIteration

    return event

  async def aclose(self, wait: bool = True) -> None:
    self._closed = True

    if not wait:
      for task in self._running_fncs:
        task.cancel()

    await asyncio.gather(*self._running_fncs, return_exceptions=True)


def to_openai_ctx(chat_ctx: llm.ChatContext) -> list:
  return [
    {
      "role": msg.role.value,
      "content": msg.text,
    }
    for msg in chat_ctx.messages
  ]
