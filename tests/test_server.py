"""Run with .sharp/venv/bin/python -m unittest discover -s tests. No fal calls."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "world"))
import config
import serve


class Credentials(unittest.TestCase):
    def test_missing_quoted_key_reload_and_precedence(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(config, "REPO", Path(directory)), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(config.fal_key(), "")
            path = Path(directory) / ".env"
            path.write_text('export FAL_KEY = "example:quoted#secret" # comment\n')
            self.assertEqual(config.fal_key(), "example:quoted#secret")
            path.write_text('FAL_KEY=changed\n')
            self.assertEqual(config.fal_key(), "changed")
            (Path(directory) / ".env.local").write_text("FAL_KEY='local'\n")
            self.assertEqual(config.fal_key(), "local")
            with patch.dict(os.environ, {"FAL_KEY": "environment"}):
                self.assertEqual(config.fal_key(), "environment")

    def test_missing_key_fails_before_reading_or_writing_world(self):
        with patch.object(serve, "require_fal_key", side_effect=RuntimeError("FAL_KEY missing")):
            with self.assertRaisesRegex(RuntimeError, "FAL_KEY missing"):
                serve.generate({})

    def test_auth_failure_does_not_retry_or_upload(self):
        response = Mock(status_code=401, text="Unauthorized")
        with patch.object(serve, "require_fal_key", return_value="test-only"), \
                patch.object(serve.requests, "post", return_value=response) as post, \
                patch.object(serve.requests, "put") as put:
            with self.assertRaisesRegex(RuntimeError, "401"):
                serve.paint(Image.new("RGB", (128, 128)), "test")
            self.assertEqual(post.call_count, 1)
            put.assert_not_called()

    def test_network_failure_is_actionable_and_never_retried(self):
        with patch.object(serve, "require_fal_key", return_value="test-only"), \
                patch.object(serve.requests, "post", side_effect=serve.requests.ConnectionError("DNS failed")) as post, \
                patch.object(serve.requests, "put") as put:
            with self.assertRaisesRegex(RuntimeError, "Cannot reach fal.*Start.command"):
                serve.paint(Image.new("RGB", (128, 128)), "test")
            self.assertEqual(post.call_count, 1)
            put.assert_not_called()

    def test_health_checks_auth_without_submitting(self):
        with patch.object(serve, "fal_key", return_value="test-only"), \
                patch.object(serve.socket, "getaddrinfo"), \
                patch.object(serve.requests, "get", return_value=Mock(status_code=200)) as get, \
                patch.object(serve.requests, "post") as post:
            self.assertTrue(serve.check_fal()["fal_authenticated"])
            self.assertIn("/models/requests/by-endpoint", get.call_args.args[0])
            post.assert_not_called()


class Prompts(unittest.TestCase):
    def test_default_keeps_repair_instructions(self):
        prompt = serve.generation_prompt("a sunny room")
        self.assertIn("sunny room", prompt)
        self.assertIn("No people or text.", prompt)
        self.assertNotIn("Requested change", prompt)

    def test_specific_text_is_allowed_without_moving_camera(self):
        prompt = serve.generation_prompt("", '  Put a sign reading "HELLO" on the wall  ')
        self.assertIn('Requested change: Put a sign reading "HELLO" on the wall', prompt)
        self.assertIn("Keep the camera position, framing and perspective fixed", prompt)
        self.assertNotIn("No people or text.", prompt)

    def test_invalid_prompts_rejected(self):
        for value in [[], None, "x" * 2001]:
            with self.assertRaisesRegex(ValueError, "2000 characters"):
                serve.generation_prompt("", value)


class SingleView(unittest.TestCase):
    def test_generation_and_reset_leave_360_data_untouched(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(serve, "HERE", directory):
            root = Path(directory) / "worlds" / "test"
            root.mkdir(parents=True)
            (root / "world.json").write_text(json.dumps({"views": [{"file": "front.ply"}, {"file": "hidden.ply"}]}))
            # Deliberately not a PLY: generation must never read the hidden view in single mode.
            (root / "hidden.ply").write_bytes(b"unchanged 360 view")
            (root / "gen.json").write_bytes(b"unchanged 360 state")
            (root / "gen_01.ply").write_bytes(b"unchanged 360 generation")
            (root / "front.c01.ply").write_bytes(b"unchanged 360 cut")
            points = np.zeros((300, 14), np.float32)
            points[:, 2] = -2
            serve.write_ply(root / "front.ply", points)
            originals = {p.name: p.read_bytes() for p in root.iterdir()}
            image = io.BytesIO()
            Image.new("RGB", (128, 128), "white").save(image, "JPEG")
            import base64
            req = {"world": "test", "mode": "single", "fov": 62,
                   "matrix": np.eye(4).flatten().tolist(), "prompt": "Add a warm lamp",
                   "image": "data:image/jpeg;base64," + base64.b64encode(image.getvalue()).decode()}
            g = {"xyz": np.tile([0, 0, 2], (300, 1)), "scale": np.ones((300, 3)),
                 "quat": np.tile([1, 0, 0, 0], (300, 1)), "opac": np.full(300, 0.8), "rgb": np.ones((300, 3))}
            with patch.object(serve, "sharp", return_value=g), \
                    patch.object(serve, "require_fal_key", return_value="test-only"), \
                    patch.object(serve, "paint", return_value="https://example.test/image.jpg") as paint, \
                    patch.object(serve.requests, "get", return_value=Mock(content=image.getvalue())):
                result = serve.generate(req)
            self.assertIn("Requested change: Add a warm lamp", paint.call_args.args[1])
            self.assertEqual(result["gens"][0]["file"], "gen_single_01.ply")
            self.assertEqual(result["gens"][0]["prompt"], "Add a warm lamp")
            self.assertEqual(set(result["replace"]), {"front.ply"})
            self.assertTrue((root / "gen_single.json").exists())
            for name, data in originals.items():
                self.assertEqual((root / name).read_bytes(), data)
            serve.reset({"world": "test", "mode": "single"})
            self.assertEqual({p.name for p in root.iterdir()}, set(originals))
            for name, data in originals.items():
                self.assertEqual((root / name).read_bytes(), data)


if __name__ == "__main__":
    unittest.main()
