from __future__ import annotations

import asyncio
import functools
import inspect
import json
import typing
from typing import Any

from livekit.agents.llm import function_context, llm

__all__ = [
  "create_function_task",
]


def create_function_task(
  fnc_ctx: function_context.FunctionContext,
  fnc_name: str,
  raw_arguments: str,  # JSON string
) -> tuple[asyncio.Task[Any], llm.CalledFunction]:
  if fnc_name not in fnc_ctx.ai_functions:
    raise ValueError(f"AI function {fnc_name} not found")

  parsed_arguments: dict[str, Any] = {}
  try:
    if raw_arguments:  # ignore empty string
      parsed_arguments = json.loads(raw_arguments)
  except json.JSONDecodeError:
    raise ValueError(
      f"AI function {fnc_name} received invalid JSON arguments - {raw_arguments}"
    )

  fnc_info = fnc_ctx.ai_functions[fnc_name]

  # Ensure all necessary arguments are present and of the correct type.
  sanitized_arguments: dict[str, Any] = {}
  for arg_info in fnc_info.args.values():
    if arg_info.name not in parsed_arguments:
      if arg_info.default is inspect.Parameter.empty:
        raise ValueError(
          f"AI function {fnc_name} missing required argument {arg_info.name}"
        )
      continue

    arg_value = parsed_arguments[arg_info.name]
    if typing.get_origin(arg_info.type) is not None:
      if not isinstance(arg_value, list):
        raise ValueError(
          f"AI function {fnc_name} argument {arg_info.name} should be a list"
        )

      inner_type = typing.get_args(arg_info.type)[0]
      sanitized_value = [
        _sanitize_primitive(value=v, expected_type=inner_type) for v in arg_value
      ]
    else:
      sanitized_value = _sanitize_primitive(
        value=arg_value, expected_type=arg_info.type
      )

    sanitized_arguments[arg_info.name] = sanitized_value

  func = functools.partial(fnc_info.fnc, **sanitized_arguments)
  if asyncio.iscoroutinefunction(fnc_info.fnc):
    task = asyncio.create_task(func())
  else:
    task = asyncio.create_task(asyncio.to_thread(func))

  return (
    task,
    llm.CalledFunction(
      fnc_name=fnc_name,
      fnc=func,
      args=sanitized_arguments,
    ),
  )


def build_function_description(
  fnc_info: function_context.AIFunction,
) -> dict[str, Any]:
  arg_names = [key for key in fnc_info.args.keys()]
  properties_info = {
    arg_name: {
      "type": "string",
      "description": arg_info.desc,
    }
    for arg_name, arg_info in fnc_info.args.items()
  }

  return {
    "name": fnc_info.metadata.name,
    "description": fnc_info.metadata.desc,
    "input_schema": {
      "type": "object",
      "properties": properties_info,
      "required": arg_names,
    },
  }


def _sanitize_primitive(*, value: Any, expected_type: type) -> Any:
  if expected_type is str:
    if not isinstance(value, str):
      raise ValueError(f"expected str, got {type(value)}")
  elif expected_type in (int, float):
    if not isinstance(value, (int, float)):
      raise ValueError(f"expected number, got {type(value)}")

    if expected_type is int:
      if value % 1 != 0:
        raise ValueError("expected int, got float")

      value = int(value)
    elif expected_type is float:
      value = float(value)

  elif expected_type is bool:
    if not isinstance(value, bool):
      raise ValueError(f"expected bool, got {type(value)}")

  return value
