from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Literal, MutableSet

import anthropic
from attrs import define
from livekit import rtc
from livekit.agents import llm

from demospace.livekit.claude import tool_calling

ChatModels = Literal["claude-3-5-sonnet-20240620",]


@define
class LLMOptions:
  model: ChatModels


class LLM(llm.LLM):
  def __init__(
    self,
    *,
    room: rtc.Room,
    model: ChatModels = "claude-3-5-sonnet-20240620",
    client: anthropic.AsyncClient | None = None,
    max_tokens: int = 1024,
    system: str | None = None,
  ) -> None:
    self._room: rtc.Room = room
    self._opts: LLMOptions = LLMOptions(model=model)
    self._client: anthropic.AsyncClient = client or anthropic.AsyncAnthropic()
    self._max_tokens: int = max_tokens
    self._system: str | None = system

  async def chat(
    self,
    history: llm.ChatContext,
    fnc_ctx: llm.FunctionContext | None = None,
    temperature: float | None = None,
    n: int | None = None,
  ) -> "LLMStream":
    tools = []
    if fnc_ctx and len(fnc_ctx.ai_functions) > 0:
      for fnc in fnc_ctx.ai_functions.values():
        tools.append(tool_calling.build_function_description(fnc))

    stream = await self._client.messages.create(
      max_tokens=self._max_tokens,
      model=self._opts.model,
      tools=tools,
      messages=_build_anthropic_context(history),
      system=self._system,
      stream=True,
    )

    async def _send_tool_result(
      message_text: str,
      fnc_name: str,
      fnc_raw_arguments: str,
      tool_use_id: str,
      result: str,
    ):
      args = json.loads(fnc_raw_arguments)
      messages = _build_anthropic_context(history)
      messages.extend(
        [
          {
            "role": "assistant",
            "content": [
              {
                "type": "text",
                "text": message_text,
              },
              {
                "type": "tool_use",
                "id": tool_use_id,
                "name": fnc_name,
                "input": args,
              },
            ],
          },
          {
            "role": "user",
            "content": [
              {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": result,
              }
            ],
          },
        ]
      )
      return await self._client.messages.create(
        max_tokens=self._max_tokens,
        model=self._opts.model,
        tools=tools,
        messages=messages,
        system=self._system,
        stream=True,
      )

    return LLMStream(stream, _send_tool_result, fnc_ctx)


class LLMStream(llm.LLMStream):
  def __init__(
    self,
    anthropic_stream: anthropic.AsyncStream[anthropic.types.RawMessageStreamEvent],
    send_tool_result: Callable,
    fnc_ctx: llm.FunctionContext | None,
  ) -> None:
    super().__init__()
    self._anthropic_stream = anthropic_stream
    self._send_tool_result = send_tool_result
    self._fnc_ctx = fnc_ctx
    self._running_tasks: MutableSet[asyncio.Task[Any]] = set()

    self._message_text: str = ""

    # current function call that we're waiting for full completion (args are streamed)
    self._tool_use_id: str | None = None
    self._fnc_name: str | None = None
    self._fnc_raw_arguments: str | None = None

  async def gather_function_results(self) -> list[llm.CalledFunction]:
    await asyncio.gather(*self._running_tasks, return_exceptions=True)
    return self._called_functions

  def __aiter__(self) -> "LLMStream":
    return self

  async def aclose(self) -> None:
    await self._anthropic_stream.close()

    for task in self._running_tasks:
      task.cancel()

    await asyncio.gather(*self._running_tasks, return_exceptions=True)

  async def __anext__(self):
    async for chunk in self._anthropic_stream:
      chat_chunk = await self._parse_chunk(chunk)
      if chat_chunk is not None:
        return chat_chunk

    raise StopAsyncIteration

  async def _parse_chunk(
    self, chunk: anthropic.types.RawMessageStreamEvent
  ) -> llm.ChatChunk | None:
    match chunk.type:
      case "message_start":
        return llm.ChatChunk(
          choices=[
            llm.Choice(
              delta=llm.ChoiceDelta(
                role="assistant",
              )
            )
          ]
        )
      case "message_delta":
        return llm.ChatChunk(
          choices=[
            llm.Choice(
              delta=llm.ChoiceDelta(
                role="assistant",
              )
            )
          ]
        )
      case "message_stop":
        return None
      case "content_block_start":
        if chunk.content_block.type == "text":
          self._message_text += chunk.content_block.text
          return llm.ChatChunk(
            choices=[
              llm.Choice(
                delta=llm.ChoiceDelta(
                  role="assistant",
                  content=chunk.content_block.text,
                )
              )
            ]
          )
        elif chunk.content_block.type == "tool_use":
          self._tool_use_id = chunk.content_block.id
          self._fnc_name = chunk.content_block.name
        else:
          logging.warning(f"unhandled content block type {chunk.content_block.type}")
      case "content_block_delta":
        if chunk.delta.type == "text_delta":
          self._message_text += chunk.delta.text
          return llm.ChatChunk(
            choices=[
              llm.Choice(
                delta=llm.ChoiceDelta(
                  role="assistant",
                  content=chunk.delta.text,
                )
              )
            ]
          )
        elif chunk.delta.type == "input_json_delta":
          if self._fnc_raw_arguments is not None:
            self._fnc_raw_arguments += chunk.delta.partial_json
          else:
            self._fnc_raw_arguments = chunk.delta.partial_json
        else:
          logging.warning(f"unhandled content block delta type {chunk.delta.type}")
      case "content_block_stop":
        if self._fnc_name is not None:
          return await self._try_run_function()
        return None

  async def _try_run_function(
    self,
  ) -> llm.ChatChunk | None:
    if not self._fnc_ctx:
      logging.warning("anthropic stream tried to run function without function context")
      return None

    if self._fnc_name is None or self._fnc_raw_arguments is None:
      logging.warning(
        "anthropic stream tried to call a function but raw_arguments and fnc_name are not set"
      )
      return None

    task, called_function = tool_calling.create_function_task(
      self._fnc_ctx, self._fnc_name, self._fnc_raw_arguments
    )

    self._called_functions.append(called_function)

    await asyncio.wait_for(task, None)

    new_stream = await self._send_tool_result(
      self._message_text,
      self._fnc_name,
      self._fnc_raw_arguments,
      self._tool_use_id,
      task.result(),
    )
    self._anthropic_stream = new_stream

    self._tool_use_id = self._fnc_name = self._fnc_raw_arguments = None

    return llm.ChatChunk(
      choices=[
        llm.Choice(
          delta=llm.ChoiceDelta(
            role="assistant",
          ),
        )
      ]
    )


def _build_anthropic_context(
  chat_ctx: llm.ChatContext,
) -> list[anthropic.types.Message]:
  return [_build_anthropic_message(msg) for msg in chat_ctx.messages]  # type: ignore


def _build_anthropic_message(msg: llm.ChatMessage):
  anthropic_msg: dict = {
    "role": msg.role.value,
  }

  # add content if provided
  if isinstance(msg.text, str):
    anthropic_msg["content"] = msg.text
  elif isinstance(msg.text, list):
    anthropic_content = []
    for content in msg.text:
      if isinstance(content, str):
        anthropic_content.append(
          {
            "type": "text",
            "text": content,
          }
        )

    anthropic_msg["content"] = anthropic_content

  return anthropic_msg
