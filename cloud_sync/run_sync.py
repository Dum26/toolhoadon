"""Fetch VAOnline on a hosted runner, then publish only a successful snapshot."""
import base64
import gzip
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from report_options import ReportOptions, preset_dates


class CloudSyncError(RuntimeError):
    pass


def report_options(raw, today):
    try:
        values = json.loads(raw or "{}")
        if not isinstance(values, dict):
            raise ValueError()
        period = values.get("period", "Cả năm")
        if period != "Tùy chọn":
            start, end = preset_dates(period, today)
        else:
            start = date.fromisoformat(values["from_date"])
            end = date.fromisoformat(values["to_date"])
        return ReportOptions(**{**values, "period": period, "from_date": start, "to_date": end})
    except (TypeError, ValueError, KeyError) as exc:
        raise CloudSyncError("VAONLINE_REPORT_OPTIONS is invalid; check the saved report filters.") from exc


def validate_config(env):
    required = ("VAONLINE_URL", "VAONLINE_STORAGE_STATE_GZIP_B64", "RENDER_API_KEY", "RENDER_SERVICE_ID")
    missing = [name for name in required if not env.get(name, "").strip()]
    if missing:
        raise CloudSyncError("Missing GitHub Secrets: " + ", ".join(missing))
    parsed = urlsplit(env["VAONLINE_URL"])
    if (parsed.scheme != "https" or not (parsed.hostname or "").endswith(".vaonline.vn")
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise CloudSyncError("VAONLINE_URL must be an HTTPS tenant URL on vaonline.vn.")
    if not re.fullmatch(r"srv-[A-Za-z0-9]+", env["RENDER_SERVICE_ID"]):
        raise CloudSyncError("RENDER_SERVICE_ID must be a Render service ID starting with srv-.")
    try:
        state = json.loads(gzip.decompress(base64.b64decode(env["VAONLINE_STORAGE_STATE_GZIP_B64"].strip(), validate=True)))
        if (not isinstance(state, dict) or not isinstance(state.get("cookies"), list)
                or not isinstance(state.get("origins"), list)
                or not (state["cookies"] or state["origins"])):
            raise ValueError()
    except (TypeError, ValueError, OSError, EOFError) as exc:
        raise CloudSyncError("VAONLINE_STORAGE_STATE_GZIP_B64 must contain the prepared, compressed login session.") from exc
    return state


def publish_inventory(body, api_key, service_id):
    snapshot = json.dumps(body, ensure_ascii=False, allow_nan=False)
    if len(snapshot.encode("utf-8")) > 1_000_000:
        raise CloudSyncError("Inventory exceeds the Render secret file size limit.")
    base = f"https://api.render.com/v1/services/{service_id}"
    requests = (
        ("PUT", base + "/secret-files/inventory.json", {"content": snapshot}),
        ("POST", base + "/deploys", {"deployMode": "deploy_only"}),
    )
    for method, url, payload in requests:
        request = Request(url, data=json.dumps(payload).encode("utf-8"), method=method,
                          headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urlopen(request, timeout=60):
                pass
        except HTTPError as exc:
            raise CloudSyncError(f"Render {method} failed with HTTP {exc.code}; check API key and service permissions.") from None
        except (URLError, TimeoutError, OSError):
            raise CloudSyncError("Cannot reach Render; the next scheduled run can retry.") from None


def sync_once():
    env = os.environ
    state = validate_config(env)
    options = report_options(env.get("VAONLINE_REPORT_OPTIONS", ""), datetime.now(timezone(timedelta(hours=7))).date())
    from config import STATE_PATH
    from database import list_inventory
    from scraper import SessionExpired, run
    from sync_lock import process_lock

    try:
        with os.fdopen(os.open(STATE_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as handle:
            json.dump(state, handle)
        with process_lock():
            try:
                run("sync", report_options=options)
            except SessionExpired:
                raise CloudSyncError("VAOnline session expired. Log in again on Windows and replace VAONLINE_STORAGE_STATE_GZIP_B64 in GitHub Secrets.") from None
            rows = list_inventory()
        if not rows:
            raise CloudSyncError("No inventory was returned; the published snapshot has not been replaced.")
        body = {"success": True, "count": len(rows),
                "updated_at": max(row["updated_at"] for row in rows), "data": rows,
                "report": {"from_date": options.from_date.isoformat(), "to_date": options.to_date.isoformat(), "period": options.period}}
        publish_inventory(body, env["RENDER_API_KEY"], env["RENDER_SERVICE_ID"])
        print(f"Fetched {len(rows)} inventory items; Render deployment requested.")
    finally:
        STATE_PATH.unlink(missing_ok=True)


def main():
    try:
        sync_once()
        return 0
    except CloudSyncError as exc:
        print(str(exc), file=sys.stderr)
    except Exception:
        # Avoid printing browser exceptions that may include login/session details.
        print("VAOnline synchronization failed. The published inventory was not replaced. Check the login session and report filters.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
