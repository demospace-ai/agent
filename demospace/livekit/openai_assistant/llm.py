from __future__ import annotations

import asyncio
from typing import Literal, MutableSet, Optional

import openai
from attrs import define
from livekit.agents import llm

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
  ) -> None:
    self.assistant_id = assistant_id
    self._opts = LLMOptions(model=model)
    self._client = client or openai.AsyncClient()
    self._running_fncs: MutableSet[asyncio.Task] = set()
    self.thread = None

  async def get_thread(self, history: llm.ChatContext):
    if self.thread is not None:
      return self.thread
    else:
      self.thread = await self._client.beta.threads.create(
        messages=to_openai_ctx(history),
      )
      return self.thread

  async def chat(
    self,
    history: llm.ChatContext,
    fnc_ctx: llm.FunctionContext | None = None,
    temperature: float | None = None,
    n: int | None = None,
  ) -> "LLMStream":
    opts = dict()

    thread = await self.get_thread(history)
    llm_stream = LLMStream()
    stream: openai.AsyncAssistantEventHandler
    async with self._client.beta.threads.runs.stream(
      thread_id=thread.id,
      assistant_id=self.assistant_id,
      model=self._opts.model,
      temperature=temperature,
      **opts,
    ) as stream:
      async for chunk in stream:
        if chunk.event == "thread.message.delta":
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
        elif chunk.event == "thread.message.completed":
          print(chunk.data.content[0].text.value)
        elif chunk.event == "thread.run.completed":
          print("complete")
          llm_stream.push_text(None)
        else:
          print(chunk.event)

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
    print("closing")
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
