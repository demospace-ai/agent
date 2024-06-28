from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal, MutableSet

import anthropic
from attrs import define
from livekit import rtc
from livekit.agents import llm

from demospace.livekit.claude import system_prompt, tool_calling

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
  ) -> None:
    self._room: rtc.Room = room
    self._opts: LLMOptions = LLMOptions(model=model)
    self._client: anthropic.AsyncClient = client or anthropic.AsyncAnthropic()
    self._max_tokens: int = max_tokens

  async def chat(
    self,
    chat_ctx: llm.ChatContext,
    fnc_ctx: llm.FunctionContext | None = None,
    temperature: float | None = None,
    n: int | None = None,
  ) -> "LLMStream":
    tools = [
      {
        "name": "send_asset",
        "description": "Send a visual asset to the customer's application",
        "input_schema": {
          "type": "object",
          "properties": {
            "assetUrl": {
              "type": "string",
              "description": "The URL of the visual asset. Taken from the Assets section of the prompt.",
            },
            "alt": {
              "type": "string",
              "description": "The alt text of the visual asset. Taken from the Assets section of the prompt.",
            },
          },
          "required": ["assetUrl", "alt"],
        },
      }
    ]

    stream = await self._client.messages.create(
      max_tokens=self._max_tokens,
      model=self._opts.model,
      temperature=temperature,
      tools=tools,
      messages=_build_anthropic_context(chat_ctx),
      system_prompt=system_prompt.SYSTEM_PROMPT,
      stream=True,
    )

    return LLMStream(stream)


class LLMStream(llm.LLMStream):
  def __init__(
    self,
    anthropic_stream: anthropic.AsyncStream[anthropic.types.RawMessageStreamEvent],
    fnc_ctx: llm.FunctionContext | None,
  ) -> None:
    super().__init__()
    self._anthropic_stream = anthropic_stream
    self._fnc_ctx = fnc_ctx
    self._running_tasks: MutableSet[asyncio.Task[Any]] = set()

    # current function call that we're waiting for full completion (args are streamed)
    self._tool_call_id: str | None = None
    self._fnc_name: str | None = None
    self._fnc_raw_arguments: str | None = None

  async def gather_function_results(self) -> list[llm.CalledFunction]:
    await asyncio.gather(*self._running_tasks, return_exceptions=True)
    return self._called_functions

  async def aclose(self) -> None:
    await self._anthropic_stream.close()

    for task in self._running_tasks:
      task.cancel()

    await asyncio.gather(*self._running_tasks, return_exceptions=True)

  async def __anext__(self):
    async for chunk in self._anthropic_stream:
      chat_chunk = self._parse_chunk(chunk)
      if chat_chunk is not None:
        return chat_chunk

    raise StopAsyncIteration

  def _parse_chunk(
    self, chunk: anthropic.types.RawMessageStreamEvent
  ) -> llm.ChatChunk | None:
    match chunk.type:
      case "message_start":
        return None
      case "message_delta":
        return self._parse_message_delta(chunk)
      case "message_stop":
        return None
      case "content_block_start":
        if chunk.content_block.type == "text":
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
          self._fnc_name = chunk.content_block.name
        else:
          logging.warning(f"unhandled content block type {chunk.content_block.type}")
      case "content_block_delta":
        if chunk.delta.type == "text_delta":
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
          self._fnc_raw_arguments += chunk.delta.partial_json
        else:
          logging.warning(f"unhandled content block delta type {chunk.delta.type}")
      case "content_block_stop":
        if self._fnc_name is not None:
          return self._try_run_function()
        return None

  def _try_run_function(
    self,
  ) -> llm.ChatChunk | None:
    if not self._fnc_ctx:
      logging.warning("anthropic stream tried to run function without function context")
      return None

    if self._tool_call_id is None:
      logging.warning(
        "anthropic stream tried to run function but tool_call_id is not set"
      )
      return None

    if self._fnc_name is None or self._fnc_raw_arguments is None:
      logging.warning(
        "anthropic stream tried to call a function but raw_arguments and fnc_name are not set"
      )
      return None

    task, called_function = tool_calling.create_function_task(
      self._fnc_ctx, self._tool_call_id, self._fnc_name, self._fnc_raw_arguments
    )
    self._tool_call_id = self._fnc_name = self._fnc_raw_arguments = None

    self._running_tasks.add(task)
    task.add_done_callback(self._running_tasks.remove)
    self._called_functions.append(called_function)

    return llm.ChatChunk(
      choices=[
        llm.Choice(
          delta=llm.ChoiceDelta(
            role="assistant",
            tool_calls=[called_function],
          ),
        )
      ]
    )


def _build_anthropic_context(
  chat_ctx: llm.ChatContext, cache_key: Any
) -> list[anthropic.types.Message]:
  return [_build_anthropic_message(msg, cache_key) for msg in chat_ctx.messages]  # type: ignore


def _build_anthropic_message(msg: llm.ChatMessage, cache_key: Any):
  anthropic_msg: dict = {
    "role": msg.role,
  }

  if msg.name:
    anthropic_msg["name"] = msg.name

  # add content if provided
  if isinstance(msg.content, str):
    anthropic_msg["content"] = msg.content
  elif isinstance(msg.content, list):
    anthropic_content = []
    for cnt in msg.content:
      if isinstance(cnt, str):
        anthropic_content.append(
          {
            "type": "text",
            "text": cnt,
          }
        )

    anthropic_msg["content"] = anthropic_content

  # make sure to provide when function has been called inside the context
  # (+ raw_arguments)
  if msg.tool_calls is not None:
    tool_calls: list[dict[str, Any]] = []
    anthropic_msg["tool_calls"] = tool_calls
    for fnc in msg.tool_calls:
      tool_calls.append(
        {
          "id": fnc.tool_call_id,
          "type": "function",
          "function": {
            "name": fnc.function_info.name,
            "arguments": fnc.raw_arguments,
          },
        }
      )

  # tool_call_id is set when the message is a response/result to a function call
  # (content is a string in this case)
  if msg.tool_call_id:
    anthropic_msg["tool_call_id"] = msg.tool_call_id

  return anthropic_msg
