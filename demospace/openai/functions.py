from livekit import rtc

from demospace.utils.env import is_prod

SEND_ASSET_URL = (
  "https://app.demospace.ai/api/realtime/broadcast"
  if is_prod()
  else "http://localhost:3000/api/realtime/broadcast"
)


async def send_asset(args: str, room: rtc.Room):
  await room.local_participant.publish_data(payload=args, topic="asset")
