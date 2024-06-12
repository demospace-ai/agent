from livekit import rtc


async def send_asset(args: str, room: rtc.Room):
  await room.local_participant.publish_data(payload=args, topic="asset")
