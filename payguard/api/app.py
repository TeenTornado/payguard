"""PayGuard API — Phase 1 stub with healthz and version."""
from fastapi import FastAPI

from payguard.shared.config import get_settings

app = FastAPI(title="PayGuard API", version="0.1.0")


@app.on_event("startup")
async def startup() -> None:
    get_settings()  # validates config including key prefix and TEST env


@app.get("/healthz")
async def healthz() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "env": settings.payguard_env,
        "gateway_mode": settings.gateway_mode,
        "demo": settings.payguard_demo,
    }
