"""Seed a clean demo: one scan of the dup-fulfillment target whose CRITICAL finding is
already VERIFIED with a MEASURED ₹1,500, so first load is never empty and the money
moment is one click away.

Everything is REAL — it drives the running API/worker/gateway/sandbox, not fixtures.
Requires the services to be up (see `make demo`).

    python -m payguard.demo.seed
"""
from __future__ import annotations

# Table names in DELETE come from a fixed local list, not user input.
# ruff: noqa: S608
import asyncio
import os
import time

import httpx

API = os.environ.get("PAYGUARD_API_URL", "http://localhost:8000")
TARGET = os.environ.get(
    "PAYGUARD_DEMO_TARGET",
    os.path.join(os.getcwd(), "examples", "targets", "dup-fulfillment-node"),
)

# Delete order respects foreign keys (children first).
_TABLES = [
    "verification_results",
    "remediations",
    "findings",
    "jobs",
    "scans",
    "repositories",
    "audit_events",
]


async def _reset_db() -> None:
    from sqlalchemy import text

    from payguard.shared.db import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            for table in _TABLES:
                await session.execute(text(f"DELETE FROM {table}"))
    print(f"  cleared: {', '.join(_TABLES)}")


def _wait_scan(sid: str, timeout: int = 90) -> dict:
    for _ in range(timeout * 2):
        s = httpx.get(f"{API}/scans/{sid}", timeout=5).json()
        if s["state"] in ("DONE", "FAILED"):
            return s
        time.sleep(0.5)
    return httpx.get(f"{API}/scans/{sid}", timeout=5).json()


def _wait_verify(fid: str, timeout: int = 90) -> dict | None:
    for _ in range(timeout * 2):
        f = httpx.get(f"{API}/findings/{fid}", timeout=5).json()
        vrs = f.get("verification_results", [])
        if vrs and vrs[-1]["status"] not in ("PENDING", "RUNNING"):
            return vrs[-1]
        time.sleep(0.5)
    return None


def _seed() -> None:
    print(f"seeding demo from {TARGET}")
    print("resetting database…")
    asyncio.run(_reset_db())

    # Clear any leftover chaos so the demo starts clean.
    httpx.put(f"{API}/settings", json={"chaos_llm": False, "chaos_gateway": False}, timeout=5)

    print("scanning the dup-fulfillment target…")
    sid = httpx.post(f"{API}/scans", json={"repo_path": TARGET}, timeout=10).json()["id"]
    scan = _wait_scan(sid)
    print(f"  scan {sid[:8]} → {scan['state']} ({scan.get('n_findings')} findings, "
          f"llm={scan.get('llm_status')})")

    items = httpx.get(f"{API}/findings", params={"scan_id": sid}, timeout=5).json()["items"]
    dp = next((i for i in items if i["defect_class"] == "DUPLICATE_PAYMENT"), None)
    if dp is None:
        print("  ! no DUPLICATE_PAYMENT finding produced — is the detector wired?")
        return

    print(f"  verifying: {dp['title']}")
    httpx.post(f"{API}/findings/{dp['id']}/verify", json={"actor": "demo"}, timeout=10)
    vr = _wait_verify(dp["id"])
    if vr and vr["status"] == "VERIFIED":
        rupees = (vr.get("measured_impact_paise") or 0) / 100
        print(f"  ✓ VERIFIED — MEASURED ₹{rupees:,.0f} (tier {vr.get('tier', 'EMULATED')})")
    else:
        print(f"  ! verification ended {vr['status'] if vr else 'timeout'} "
              "(is the gateway up and SANDBOX_RUNTIME set?)")

    # Scan the SAFE control so the demo also has an LLM-only "AI finding — unverified":
    # the LLM flags it as risky, but the sandbox would show the redelivery is a no-op.
    safe = TARGET + "-safe"
    print("scanning the safe control (for the AI-only finding)…")
    sid2 = httpx.post(f"{API}/scans", json={"repo_path": safe}, timeout=10).json()["id"]
    _wait_scan(sid2)
    items2 = httpx.get(f"{API}/findings", params={"scan_id": sid2}, timeout=5).json()["items"]
    ai = next((i for i in items2 if i["detector_source"] == "LLM"), None)
    if ai:
        print(f"  ✓ AI-only finding present (source=LLM, unverified): {ai['title']}")
    else:
        print("  · no LLM-only finding this run (local model varies) — the VERIFIED beat still holds")

    print("\nDemo ready → open the console. Top finding is VERIFIED with a MEASURED amount;")
    print("the safe control carries an 'AI finding — unverified' (no measured amount).")


if __name__ == "__main__":
    _seed()
