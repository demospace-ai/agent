"""Credential-free checks for the aiohttp security update.

Run with: poetry run python -m unittest discover -s tests -v
All HTTP and WebSocket traffic stays on a temporary loopback server.
"""

import importlib.metadata
import os
from pathlib import Path
import tomllib
import unittest

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer


class AiohttpCompatibilityTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5))
    self.addAsyncCleanup(self.session.close)

  async def serve(self, app):
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    self.addAsyncCleanup(server.close)
    return server

  def test_installed_version_matches_patched_lock(self):
    root = Path(__file__).resolve().parents[1]
    lock = tomllib.loads((root / "poetry.lock").read_text())
    version = next(p["version"] for p in lock["package"] if p["name"] == "aiohttp")
    self.assertEqual(importlib.metadata.version("aiohttp"), version)
    self.assertGreaterEqual(tuple(map(int, version.split("."))), (3, 14, 4))

  async def test_json_request_round_trip(self):
    async def handler(request):
      return web.json_response({"received": await request.json()})

    app = web.Application()
    app.router.add_post("/", handler)
    server = await self.serve(app)
    async with self.session.post(server.make_url("/"), json={"message": "hello"}) as response:
      self.assertEqual(response.status, 200)
      self.assertEqual(await response.json(), {"received": {"message": "hello"}})

  async def test_websocket_text_and_binary_round_trip(self):
    async def handler(request):
      socket = web.WebSocketResponse()
      await socket.prepare(request)
      async for message in socket:
        if message.type == aiohttp.WSMsgType.TEXT:
          await socket.send_str(message.data)
        elif message.type == aiohttp.WSMsgType.BINARY:
          await socket.send_bytes(message.data)
      return socket

    app = web.Application()
    app.router.add_get("/", handler)
    server = await self.serve(app)
    async with self.session.ws_connect(server.make_url("/")) as socket:
      await socket.send_str("hello")
      self.assertEqual(await socket.receive_str(timeout=5), "hello")
      await socket.send_bytes(b"audio-sample")
      self.assertEqual(await socket.receive_bytes(timeout=5), b"audio-sample")

  async def test_livekit_api_client_success_and_error(self):
    from livekit import api

    async def handler(request):
      self.assertEqual(request.content_type, "application/protobuf")
      self.assertTrue(request.headers["Authorization"].startswith("Bearer "))
      query = api.ListRoomsRequest.FromString(await request.read())
      if list(query.names) == ["missing"]:
        return web.json_response({"code": "not_found", "msg": "test only"}, status=404)
      self.assertEqual(list(query.names), ["example"])
      result = api.ListRoomsResponse(rooms=[api.Room(name="example")])
      return web.Response(body=result.SerializeToString(), content_type="application/protobuf")

    app = web.Application()
    app.router.add_post("/twirp/livekit.RoomService/ListRooms", handler)
    server = await self.serve(app)
    client = api.LiveKitAPI(
      str(server.make_url("/")),
      api_key="loopback-test-key",
      api_secret="loopback-test-secret-not-a-real-credential",
      timeout=aiohttp.ClientTimeout(total=5),
    )
    self.addAsyncCleanup(client.aclose)
    result = await client.room.list_rooms(api.ListRoomsRequest(names=["example"]))
    self.assertEqual([room.name for room in result.rooms], ["example"])
    with self.assertRaises(api.TwirpError) as raised:
      await client.room.list_rooms(api.ListRoomsRequest(names=["missing"]))
    self.assertEqual(raised.exception.code, "not_found")

  @unittest.skipUnless(Path("/proc/self/fd").is_dir(), "Linux descriptor-count regression")
  async def test_small_multipart_files_do_not_allocate_one_descriptor_each(self):
    async def handler(request):
      before = len(os.listdir("/proc/self/fd"))
      fields = await request.post()
      during = len(os.listdir("/proc/self/fd"))
      sizes = [len(field.file.read()) for field in fields.values()]
      return web.json_response({"count": len(fields), "sizes": sizes, "fds": during - before})

    app = web.Application()
    app.router.add_post("/", handler)
    server = await self.serve(app)
    data = aiohttp.FormData()
    for index in range(64):
      data.add_field(f"file{index}", b"x", filename=f"{index}.txt")
    async with self.session.post(server.make_url("/"), data=data) as response:
      self.assertEqual(response.status, 200)
      result = await response.json()
    self.assertEqual(result["count"], 64)
    self.assertEqual(result["sizes"], [1] * 64)
    # Allow minor runtime noise, but never a descriptor per tiny uploaded file.
    self.assertLess(result["fds"], 8)

  async def test_multipart_header_overhead_counts_toward_request_limit(self):
    async def handler(request):
      await request.post()
      return web.Response(text="accepted")

    app = web.Application(client_max_size=4096)
    app.router.add_post("/", handler)
    server = await self.serve(app)
    boundary = "aiohttp-regression-boundary"
    data = b"".join(
      (f'--{boundary}\r\nContent-Disposition: form-data; name="file{index}"; '
       f'filename="{index}.txt"\r\nContent-Type: application/octet-stream\r\n\r\n\r\n').encode()
      for index in range(64)
    ) + f"--{boundary}--\r\n".encode()
    self.assertGreater(len(data), 4096)
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    async with self.session.post(server.make_url("/"), data=data, headers=headers) as response:
      self.assertEqual(response.status, 413)


if __name__ == "__main__":
  unittest.main()
