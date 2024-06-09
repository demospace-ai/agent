from __future__ import annotations

import asyncio
import logging
from typing import Literal, MutableSet

import openai
from attrs import define
from livekit.agents import llm
from openai import AssistantEventHandler, AsyncAssistantEventHandler

logger = logging.getLogger("livekit.plugins.openai")

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

  async def get_thread(self):
    if self.thread is not None:
      return self.thread
    else:
      self.thread = await self._client.beta.threads.create()
      return self.thread

  async def chat(
    self,
    history: llm.ChatContext,
    fnc_ctx: llm.FunctionContext | None = None,
    temperature: float | None = None,
    n: int | None = None,
  ) -> "LLMStream":
    opts = dict()

    thread = await self.get_thread()
    cmp = await self._client.beta.threads.runs.stream(
      thread_id=thread.id,
      assistant_id=self.assistant_id,
      event_handler=AssistantEventHandler(),
      model=self._opts.model,
      n=n,
      temperature=temperature,
      **opts,
    )

    return LLMStream(cmp)


class LLMStream(llm.LLMStream):
  def __init__(self, oai_stream: AsyncAssistantEventHandler) -> None:
    super().__init__()
    self._oai_stream = oai_stream
    self._running_fncs: MutableSet[asyncio.Task] = set()

  def __aiter__(self) -> "LLMStream":
    return self

  async def __anext__(self) -> llm.ChatChunk:
    async for chunk in self._oai_stream:
      if chunk.event == "thread.message.delta":
        choice = chunk.data.delta.content[0]
        return llm.ChatChunk(
          choices=[
            llm.Choice(
              delta=llm.ChoiceDelta(
                content=choice.text,
                role=chunk.data.role,
              ),
              index=0,
            )
          ]
        )

  async def aclose(self, wait: bool = True) -> None:
    await self._oai_stream.close()

    if not wait:
      for task in self._running_fncs:
        task.cancel()

    await asyncio.gather(*self._running_fncs, return_exceptions=True)
