"""Read-only VA STOCK viewer for Render; inventory comes from a secret file."""
import json
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPBasic
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent
USERNAME = os.environ.get("VA_STOCK_USERNAME", "vastock").encode()
PASSWORD = os.environ.get("VA_STOCK_PASSWORD", "").encode()
if not PASSWORD:
    raise RuntimeError("Set VA_STOCK_PASSWORD before starting the shared viewer.")
INVENTORY_PATH = Path(os.environ.get("INVENTORY_PATH", "/etc/secrets/inventory.json"))
security = HTTPBasic(auto_error=False)
app = FastAPI(title="VA STOCK", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.middleware("http")
async def protect_inventory(request, call_next):
    headers = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"}
    if request.url.path != "/healthz":
        try:
            supplied = await security(request)
        except HTTPException:
            supplied = None
        if supplied is None or not (
            secrets.compare_digest(supplied.username.encode(), USERNAME)
            and secrets.compare_digest(supplied.password.encode(), PASSWORD)
        ):
            return Response(status_code=401, headers={**headers, "WWW-Authenticate": 'Basic realm="VA STOCK"'})
    if request.method not in ("GET", "HEAD"):
        return Response(status_code=403, headers=headers)
    response = await call_next(request)
    response.headers.update(headers)
    return response


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.get("/")
def home():
    return FileResponse(ROOT / "templates" / "index.html")


@app.get("/api/inventory")
def inventory():
    try:
        body = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
        if not isinstance(body, dict) or not isinstance(body.get("data"), list):
            raise ValueError("Invalid inventory snapshot")
        return {"success": True, "count": len(body["data"]),
                "updated_at": body.get("updated_at"), "data": body["data"]}
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Chưa có dữ liệu tồn kho hợp lệ. Hãy thêm Secret File inventory.json trên Render.") from exc
