import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ViewerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.snapshot = Path(cls.directory.name) / "inventory.json"
        cls.snapshot.write_text(json.dumps({"data": [{"ma_hang": "TEST", "ten_hang": "Hàng thử", "ton_kho": 2.5, "updated_at": "2026-10-15T00:00:00Z"}]}), encoding="utf-8")
        env = {**os.environ, "INVENTORY_PATH": str(cls.snapshot)}
        env.pop("VA_STOCK_USERNAME", None)
        env.pop("VA_STOCK_PASSWORD", None)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        cls.base = f"http://127.0.0.1:{port}"
        cls.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=Path(__file__).resolve().parent,
            env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        cls.addClassCleanup(cls.directory.cleanup)
        cls.addClassCleanup(cls.stop_server)
        for _ in range(100):
            if cls.process.poll() is not None:
                raise RuntimeError("Viewer exited before becoming ready")
            try:
                with urlopen(cls.base + "/healthz", timeout=1) as response:
                    if response.status == 200:
                        return
            except (OSError, URLError):
                time.sleep(0.1)
        raise RuntimeError("Viewer did not start")

    @classmethod
    def stop_server(cls):
        cls.process.terminate()
        cls.process.wait(timeout=10)

    def request(self, path, auth=None, method="GET"):
        request = Request(self.base + path, headers={"Authorization": auth} if auth else {}, method=method)
        try:
            return urlopen(request, timeout=5)
        except HTTPError as response:
            return response

    def test_inventory_and_assets_open_without_login(self):
        for path in ("/", "/api/inventory", "/static/app.js", "/static/style.css"):
            with self.subTest(path=path), self.request(path) as response:
                self.assertEqual(response.status, 200)
                self.assertIsNone(response.headers.get("WWW-Authenticate"))

    def test_cached_credentials_do_not_block_public_access(self):
        for auth in ("Basic aW52YWxpZDppbnZhbGlk", "Basic invalid", "Bearer test"):
            with self.subTest(auth=auth), self.request("/api/inventory", auth) as response:
                self.assertEqual(response.status, 200)
                self.assertIsNone(response.headers.get("WWW-Authenticate"))

    def test_public_inventory(self):
        with self.request("/api/inventory") as response:
            body = json.load(response)
            self.assertEqual(body["count"], 1)
            self.assertEqual(body["data"][0]["ton_kho"], 2.5)
            self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_home_and_assets(self):
        for path in ("/", "/static/app.js", "/static/style.css"):
            with self.subTest(path=path), self.request(path) as response:
                self.assertEqual(response.status, 200)

    def test_sync_and_internal_files_not_exposed(self):
        with self.request("/api/sync", method="POST") as response:
            self.assertEqual(response.status, 403)
        for path in ("/docs", "/openapi.json", "/inventory.json", "/.env", "/static/../app.py"):
            with self.subTest(path=path), self.request(path) as response:
                self.assertEqual(response.status, 404)

    def test_unavailable_snapshot_is_service_error(self):
        original = self.snapshot.read_text(encoding="utf-8")
        try:
            for invalid in ("{", '{"data": null}'):
                self.snapshot.write_text(invalid, encoding="utf-8")
                with self.request("/api/inventory") as response:
                    self.assertEqual(response.status, 503)
            self.snapshot.unlink()
            with self.request("/api/inventory") as response:
                self.assertEqual(response.status, 503)
        finally:
            self.snapshot.write_text(original, encoding="utf-8")

if __name__ == "__main__":
    unittest.main()
