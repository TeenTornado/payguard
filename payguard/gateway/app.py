"""Gateway service — EMULATE mode (Phase 3) and FORWARD_TEST proxy (Phase 7).
Phase 1 stub: healthz only."""
import os

from fastapi import FastAPI

app = FastAPI(title="PayGuard Gateway", version="0.1.0")

GATEWAY_MODE = os.environ.get("GATEWAY_MODE", "EMULATE")


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "mode": GATEWAY_MODE}
