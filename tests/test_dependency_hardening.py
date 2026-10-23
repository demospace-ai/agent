"""Offline regression checks for the dependency-hardening update.

No provider requests, credentials, model downloads or image codecs are needed.
Run with: poetry run python -m unittest discover -s tests -v
"""

import datetime
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib
import unittest

import fsspec
import jwt
from jinja2.exceptions import SecurityError
from livekit import api


ROOT = Path(__file__).resolve().parents[1]


class DependencyHardeningTests(unittest.TestCase):
  def test_patched_versions_match_lock_and_image_extra_is_absent(self):
    lock = tomllib.loads((ROOT / "poetry.lock").read_text())
    versions = {p["name"].lower(): p["version"] for p in lock["package"]}
    for name, floor in (("pyjwt", (2, 15, 1)), ("fsspec", (2026, 6, 0))):
      self.assertEqual(importlib.metadata.version(name), versions[name])
      self.assertGreaterEqual(tuple(map(int, versions[name].split("."))), floor)
    for name in ("pillow", "livekit-plugins-openai"):
      self.assertNotIn(name, versions)
      with self.assertRaises(importlib.metadata.PackageNotFoundError):
        importlib.metadata.version(name)

  def test_livekit_token_round_trip_and_wrong_secret_rejected(self):
    secret = "offline-test-secret-at-least-32-bytes-long"
    token = (
      api.AccessToken("offline-test-key", secret)
      .with_identity("voice-agent")
      .with_grants(api.VideoGrants(room_join=True, room="offline-test-room", agent=True))
      .to_jwt()
    )
    claims = api.TokenVerifier("offline-test-key", secret).verify(token)
    self.assertEqual(claims.identity, "voice-agent")
    self.assertEqual(claims.video.room, "offline-test-room")
    self.assertTrue(claims.video.agent)
    with self.assertRaises(jwt.InvalidSignatureError):
      api.TokenVerifier("offline-test-key", "different-offline-test-secret-of-32-bytes").verify(token)

  def test_livekit_expired_token_rejected(self):
    secret = "offline-test-secret-at-least-32-bytes-long"
    token = (
      api.AccessToken("offline-test-key", secret)
      .with_ttl(datetime.timedelta(minutes=-5))
      .to_jwt()
    )
    with self.assertRaises(jwt.ExpiredSignatureError):
      api.TokenVerifier("offline-test-key", secret).verify(token)

  def test_pyjwt_rejects_empty_symmetric_jwk(self):
    # GHSA-pxh4-856f-4h89: an empty oct key must fail before token verification.
    with self.assertRaises(jwt.InvalidKeyError):
      jwt.PyJWK.from_dict({"kty": "oct", "k": "", "alg": "HS256"})

  def test_fsspec_benign_reference_template(self):
    fs = fsspec.filesystem("reference", fo={
      "version": 1,
      "templates": {"root": "memory://offline-test"},
      "refs": {"example": ["{{root}}/file", 0, 3]},
    })
    self.assertEqual(fs.references["example"], ["memory://offline-test/file", 0, 3])

  def test_fsspec_reference_template_blocks_attribute_introspection(self):
    # Harmless regression for GHSA-27vj-qcqg-25rc. No commands or file reads.
    # The old unrestricted Jinja environment rendered this as "str".
    with self.assertRaises(SecurityError):
      fsspec.filesystem("reference", simple_templates=False, fo={
        "version": 1,
        "refs": {},
        "gen": [{
          "key": "{{ 'x'.__class__.__name__ }}",
          "url": "memory://offline-test/file",
          "offset": "0",
          "length": "3",
          "dimensions": {},
        }],
      })

  def test_voice_worker_imports_without_pillow_or_openai_plugin(self):
    # A fresh process prevents imports in other tests from masking dependencies.
    code = """
import importlib.abc
import json
import sys

class BlockUnusedImages(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'PIL' or fullname.startswith('PIL.') or fullname == 'livekit.plugins.openai':
            raise AssertionError('Voice worker unexpectedly imports ' + fullname)

sys.meta_path.insert(0, BlockUnusedImages())
import main
from livekit.agents import Plugin
print(json.dumps([plugin.package for plugin in Plugin.registered_plugins]))
"""
    env = dict(os.environ, ENVIRONMENT="production")
    result = subprocess.run(
      [sys.executable, "-c", code], cwd=ROOT, env=env,
      text=True, capture_output=True, timeout=60, check=True,
    )
    plugins = json.loads(result.stdout.strip().splitlines()[-1])
    for name in ("livekit.plugins.deepgram", "livekit.plugins.elevenlabs", "livekit.plugins.silero"):
      self.assertIn(name, plugins)
    self.assertNotIn("livekit.plugins.openai", plugins)


if __name__ == "__main__":
  unittest.main()
