import json
from typing import Annotated

from livekit import rtc
from livekit.agents import (
  llm,
)


class Functions(
  llm.FunctionContext,
):
  def __init__(self, room: rtc.Room):
    self._room = room
    super().__init__()

  @llm.ai_callable(desc="Send a visual asset to the customer's application.")
  async def send_asset(
    self,
    assetUrl: Annotated[
      str,
      llm.TypeInfo(
        desc="The URL of the visual asset. Taken from the Assets section of the prompt."
      ),
    ],
    alt: Annotated[
      str,
      llm.TypeInfo(
        desc="The alt text of the visual asset. Taken from the Assets section of the prompt."
      ),
    ],
  ):
    await self._room.local_participant.publish_data(
      payload=json.dumps(
        {
          "assetUrl": assetUrl,
          "alt": alt,
        }
      ),
      topic="asset",
    )
