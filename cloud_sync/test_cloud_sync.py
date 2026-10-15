import base64
import gzip
import io
import json
import os
import tempfile
import unittest
from contextlib import nullcontext
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError

import run_sync


def environment():
    return {"VAONLINE_URL": "https://example.vaonline.vn/#",
            "VAONLINE_STORAGE_STATE_GZIP_B64": base64.b64encode(gzip.compress(json.dumps({"cookies": [], "origins": [{"origin": "https://example.vaonline.vn", "localStorage": []}]}).encode())).decode(),
            "RENDER_API_KEY": "test-render-key", "RENDER_SERVICE_ID": "srv-testservice"}


class CloudSyncTests(unittest.TestCase):
    def test_presets_roll_forward_without_losing_filters(self):
        raw = json.dumps({"period": "Tháng này", "from_date": "2026-09-01", "to_date": "2026-09-27", "warehouse_code": "TEST-WAREHOUSE"})
        options = run_sync.report_options(raw, date(2027, 1, 2))
        self.assertEqual((options.from_date, options.to_date), (date(2027, 1, 1), date(2027, 1, 2)))
        self.assertEqual(options.warehouse_code, "TEST-WAREHOUSE")

    def test_custom_period_is_preserved(self):
        options = run_sync.report_options('{"period":"Tùy chọn","from_date":"2026-09-01","to_date":"2026-09-27"}', date(2026, 10, 15))
        self.assertEqual(options.to_date, date(2026, 9, 27))

    def test_invalid_filters_fail_instead_of_silently_changing_the_report(self):
        for raw in ("[]", "{", '{"period":"invalid"}', '{"period":"Tùy chọn"}'):
            with self.subTest(raw=raw), self.assertRaises(run_sync.CloudSyncError):
                run_sync.report_options(raw, date(2026, 10, 15))

    def test_missing_credentials_and_untrusted_target_are_rejected(self):
        for changes in ({"RENDER_API_KEY": ""}, {"VAONLINE_URL": "http://example.vaonline.vn"},
                        {"VAONLINE_URL": "https://example.vaonline.vn.evil.example"},
                        {"RENDER_SERVICE_ID": "srv-id/other"}, {"VAONLINE_STORAGE_STATE_GZIP_B64": "{}"}):
            with self.subTest(changes=changes), self.assertRaises(run_sync.CloudSyncError):
                run_sync.validate_config({**environment(), **changes})

    def test_publish_updates_only_inventory_file_then_deploys_existing_build(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        body = {"success": True, "data": [{"ma_hang": "TEST", "ton_kho": 3}], "count": 1}
        with patch.object(run_sync, "urlopen", return_value=response) as send:
            run_sync.publish_inventory(body, "test-key", "srv-testservice")
        requests = [call.args[0] for call in send.call_args_list]
        self.assertEqual([request.method for request in requests], ["PUT", "POST"])
        self.assertTrue(requests[0].full_url.endswith("/secret-files/inventory.json"))
        self.assertEqual(json.loads(json.loads(requests[0].data)["content"]), body)
        self.assertEqual(json.loads(requests[1].data), {"deployMode": "deploy_only"})

    def test_failed_upload_does_not_trigger_deploy_or_print_credentials(self):
        error = HTTPError("https://api.render.com", 401, "Unauthorized", {}, io.BytesIO(b"private"))
        with patch.object(run_sync, "urlopen", side_effect=error) as send:
            with self.assertRaises(run_sync.CloudSyncError) as caught:
                run_sync.publish_inventory({"data": []}, "test-private-key", "srv-testservice")
        self.assertEqual(send.call_count, 1)
        self.assertNotIn("test-private-key", str(caught.exception))
        self.assertNotIn("private", str(caught.exception))

    def test_oversized_inventory_is_rejected_before_upload(self):
        with patch.object(run_sync, "urlopen") as send, self.assertRaises(run_sync.CloudSyncError):
            run_sync.publish_inventory({"data": ["x" * 1_000_000]}, "key", "srv-testservice")
        send.assert_not_called()

    def test_success_publishes_current_rows_and_removes_session_file(self):
        self.check_sync()

    def test_expired_session_keeps_published_inventory(self):
        self.check_sync(expired=True)

    def check_sync(self, expired=False):
        class ExpiredSession(Exception):
            pass

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            fetch = Mock(side_effect=ExpiredSession if expired else None)
            rows = [{"ma_hang": "TEST", "ton_kho": 3, "updated_at": "2026-10-15T00:00:00Z"}]
            modules = {"config": SimpleNamespace(STATE_PATH=state_path),
                       "database": SimpleNamespace(list_inventory=Mock(return_value=rows)),
                       "scraper": SimpleNamespace(SessionExpired=ExpiredSession, run=fetch),
                       "sync_lock": SimpleNamespace(process_lock=nullcontext)}
            with patch.dict(os.environ, environment(), clear=True), patch.dict("sys.modules", modules), patch.object(run_sync, "publish_inventory") as publish:
                if expired:
                    with self.assertRaisesRegex(run_sync.CloudSyncError, "session expired"):
                        run_sync.sync_once()
                    publish.assert_not_called()
                else:
                    run_sync.sync_once()
                    self.assertEqual(publish.call_args.args[0]["data"], rows)
                fetch.assert_called_once()
                self.assertFalse(state_path.exists())


if __name__ == "__main__":
    unittest.main()
