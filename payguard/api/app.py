"""PayGuard API — full implementation."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from payguard.detector.titles import title_for
from payguard.shared.audit import append_audit_event, verify_audit_chain
from payguard.shared.chaos import read_chaos, set_chaos
from payguard.shared.config import get_settings
from payguard.shared.db import get_db
from payguard.shared.enums import (
    AuditActor,
    AuditEventKind,
    FindingState,
    JobStatus,
    RemediationStatus,
    RepositorySourceType,
    ScanState,
    VerificationStatus,
)
from payguard.shared.models import (
    AuditEvent,
    Finding,
    Job,
    Remediation,
    Repository,
    Scan,
    VerificationResult,
)

log = logging.getLogger("payguard.api")

# ── In-memory mutable settings ────────────────────────────────────────────────
#
# Detection thresholds are display/tuning knobs that only the API reads, so an in-memory
# override is fine. Chaos is NOT here: it must be seen by the worker and gateway (separate
# processes), so it lives in the shared cross-process sentinel (payguard.shared.chaos).

_settings_override: dict[str, Any] = {}


def _get_advisory_threshold() -> float:
    return _settings_override.get("advisory_threshold", get_settings().advisory_threshold)


def _get_verify_threshold() -> float:
    return _settings_override.get("verify_threshold", get_settings().verify_threshold)


def _settings_payload() -> dict[str, Any]:
    settings = get_settings()
    chaos = read_chaos()
    return {
        "advisory_threshold": _get_advisory_threshold(),
        "verify_threshold": _get_verify_threshold(),
        "gateway_mode": settings.gateway_mode,
        "payguard_demo": settings.payguard_demo,
        "llm_model": settings.payguard_llm_model,
        "chaos_llm": chaos.llm,
        "chaos_gateway": chaos.gateway,
        "chaos_enabled": chaos.any(),  # legacy: any switch on
    }


# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(title="PayGuard API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    get_settings()


# ── Pydantic request/response models ─────────────────────────────────────────


class CreateScanBody(BaseModel):
    repo_path: str
    demo: bool = False


class PreflightBody(BaseModel):
    repo_path: str


class VerifyFindingBody(BaseModel):
    actor: str = "HUMAN"
    # Optional sandbox wiring. When a target webhook URL is supplied the verifier can
    # reach a VERIFIED/NOT_REPRODUCED verdict; without it the run is BLOCKED (honest).
    target_url: str | None = None
    probe_url: str | None = None
    order_amount_paise: int = 150000


class DismissFindingBody(BaseModel):
    reason: str
    actor: str = "HUMAN"


class EscalateFindingBody(BaseModel):
    actor: str = "HUMAN"


class ProposeRemediationBody(BaseModel):
    actor: str = "HUMAN"


class ApproveRemediationBody(BaseModel):
    actor: str = "HUMAN"


class RejectRemediationBody(BaseModel):
    actor: str = "HUMAN"


class UpdateSettingsBody(BaseModel):
    advisory_threshold: float | None = None
    verify_threshold: float | None = None
    # Independent fault switches (shared cross-process sentinel).
    chaos_llm: bool | None = None
    chaos_gateway: bool | None = None
    # Legacy single toggle → maps to the LLM switch. Kept for older clients.
    chaos_enabled: bool | None = None


# ── SSE terminal states ───────────────────────────────────────────────────────

_SCAN_TERMINAL = {ScanState.DONE, ScanState.FAILED}
_VERIFY_TERMINAL = {
    VerificationStatus.VERIFIED,
    VerificationStatus.NOT_REPRODUCED,
    VerificationStatus.INCONCLUSIVE,
    VerificationStatus.BLOCKED,
    VerificationStatus.ERROR,
}

_SCAN_STATE_MESSAGES: dict[str, str] = {
    ScanState.INGEST: "Ingesting repository...",
    ScanState.DISCOVER: "Discovering payment units...",
    ScanState.STATIC: "Running static analysis rules...",
    ScanState.SEMANTIC: "Running LLM semantic analysis...",
    ScanState.NORMALIZE: "Normalizing and deduplicating findings...",
    ScanState.SCORE: "Scoring and estimating exposure...",
    ScanState.SELECT_SCENARIOS: "Selecting verification scenarios...",
    ScanState.VERIFY: "Running verifier...",
    ScanState.DECIDE: "Applying decision thresholds...",
    ScanState.HUMAN_GATE: "Waiting for human review...",
    ScanState.REMEDIATE: "Applying remediations...",
    ScanState.DONE: "Scan complete.",
    ScanState.FAILED: "Scan failed.",
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _human_actor(name: str) -> str:
    """Format a human actor as HUMAN:<name> per the audit convention."""
    if not name or name == AuditActor.HUMAN.value:
        return AuditActor.HUMAN.value
    if ":" in name:
        return name
    return f"{AuditActor.HUMAN.value}:{name}"


def _sse_line(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


async def _get_finding_or_404(finding_id: str, session: AsyncSession) -> Finding:
    finding = await session.scalar(select(Finding).where(Finding.id == finding_id))
    if finding is None:
        raise HTTPException(status_code=404, detail=f"Finding {finding_id} not found")
    return finding


# ── POST /scans ───────────────────────────────────────────────────────────────


@app.post("/scans")
async def create_scan(body: CreateScanBody, db: AsyncSession = Depends(get_db)) -> dict:
    repo_path = body.repo_path
    scan_id = str(uuid.uuid4())
    repo_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    # Check for razorpay manifest
    root = Path(repo_path)
    manifest_present = False
    if root.exists():
        for fpath in root.rglob("*.py"):
            try:
                if "razorpay" in fpath.read_text(encoding="utf-8", errors="replace"):
                    manifest_present = True
                    break
            except Exception:
                pass
        if not manifest_present:
            for fpath in root.rglob("*.json"):
                try:
                    if "razorpay" in fpath.read_text(encoding="utf-8", errors="replace"):
                        manifest_present = True
                        break
                except Exception:
                    pass

    # Transaction is owned by get_db (commit on clean return). Handlers never call
    # begin()/commit()/rollback() — see tests/unit/test_transaction_convention.py.
    repo = Repository(
        id=repo_id,
        source_type=RepositorySourceType.LOCAL_PATH,
        locator=repo_path,
        commit_sha=None,
        manifest_present=manifest_present,
    )
    db.add(repo)

    scan = Scan(
        id=scan_id,
        repository_id=repo_id,
        state=ScanState.INGEST,
        started_at=_now(),
        llm_status="OK",
        static_status="OK",
    )
    db.add(scan)

    job = Job(
        id=job_id,
        kind="SCAN",
        idempotency_key=f"scan:{scan_id}",
        payload_json={"scan_id": scan_id, "repo_path": repo_path},
        status=JobStatus.PENDING,
        attempts=0,
    )
    db.add(job)
    await db.flush()

    await append_audit_event(
        db,
        actor=AuditActor.SYSTEM,
        event=AuditEventKind.SCAN_STARTED,
        object_type="Scan",
        object_id=scan_id,
        metadata={"repo_path": repo_path, "demo": body.demo},
    )

    return {
        "id": scan_id,
        "state": scan.state,
        "repository_id": repo_id,
        "repo_path": repo_path,
        "started_at": scan.started_at.isoformat(),
    }


# ── GET /scans ────────────────────────────────────────────────────────────────


@app.get("/scans")
async def list_scans(db: AsyncSession = Depends(get_db)) -> list[dict]:
    result = await db.execute(
        select(Scan, Repository)
        .join(Repository, Scan.repository_id == Repository.id)
        .order_by(Scan.started_at.desc())
    )
    rows = result.all()

    items = []
    for scan, repo in rows:
        n = await db.scalar(select(func.count()).where(Finding.scan_id == scan.id))
        items.append({
            "id": scan.id,
            "state": scan.state,
            "repo_locator": repo.locator,
            "started_at": scan.started_at.isoformat() if scan.started_at else None,
            "finished_at": scan.finished_at.isoformat() if scan.finished_at else None,
            "n_findings": n or 0,
            "llm_status": scan.llm_status,
            "static_status": scan.static_status,
        })
    return items


# ── GET /scans/{scan_id} ──────────────────────────────────────────────────────


@app.get("/scans/{scan_id}")
async def get_scan(scan_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    scan = await db.scalar(select(Scan).where(Scan.id == scan_id))
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")

    repo = await db.scalar(select(Repository).where(Repository.id == scan.repository_id))

    findings_result = await db.scalars(
        select(Finding).where(Finding.scan_id == scan_id).order_by(Finding.created_at).limit(50)
    )
    findings = list(findings_result.all())

    n_advisory = sum(1 for f in findings if f.state == FindingState.ADVISORY)
    n_verified = sum(1 for f in findings if f.state == FindingState.VERIFIED)
    n_exception = sum(1 for f in findings if f.state == FindingState.EXCEPTION)

    n_total = await db.scalar(select(func.count()).where(Finding.scan_id == scan_id))

    findings_summary = [
        {
            "id": f.id,
            "defect_class": f.defect_class,
            "severity": f.severity,
            "confidence": f.confidence,
            "file": f.file,
            "start_line": f.start_line,
            "end_line": f.end_line,
            "state": f.state,
            "detector_source": f.detector_source,
            "exposure_estimated_paise": f.exposure_estimated_paise,
            "remediation_status": f.remediation_status,
        }
        for f in findings
    ]

    return {
        "id": scan.id,
        "state": scan.state,
        "repo_locator": repo.locator if repo else None,
        "started_at": scan.started_at.isoformat() if scan.started_at else None,
        "finished_at": scan.finished_at.isoformat() if scan.finished_at else None,
        "llm_status": scan.llm_status,
        "static_status": scan.static_status,
        "stats_json": scan.stats_json,
        "n_findings": n_total or 0,
        "n_advisory": n_advisory,
        "n_verified": n_verified,
        "n_exception": n_exception,
        "findings": findings_summary,
    }


# ── GET /scans/{scan_id}/events  (SSE) ───────────────────────────────────────


@app.get("/scans/{scan_id}/events")
async def scan_events(scan_id: str) -> StreamingResponse:
    # No request-scoped session: an SSE stream can run for minutes and must not pin a
    # pooled DB connection for its whole lifetime. The generator opens short-lived
    # sessions per poll instead.
    async def _generate() -> AsyncGenerator[str, None]:
        from payguard.shared.db import get_session_factory
        factory = get_session_factory()
        last_state: str | None = None
        while True:
            try:
                async with factory() as session:
                    scan = await session.scalar(select(Scan).where(Scan.id == scan_id))
                    if scan is None:
                        yield _sse_line({"error": "scan not found"})
                        return
                    state = scan.state
                    if state != last_state:
                        last_state = state
                        yield _sse_line({
                            "state": state,
                            "message": _SCAN_STATE_MESSAGES.get(state, state),
                        })
                    if state in _SCAN_TERMINAL:
                        return
            except Exception as exc:
                yield _sse_line({"error": str(exc)})
                return
            await asyncio.sleep(1)

    return StreamingResponse(_generate(), media_type="text/event-stream")


# ── POST /scans/preflight ─────────────────────────────────────────────────────


@app.post("/scans/preflight")
async def preflight(body: PreflightBody) -> dict:
    root = Path(body.repo_path)
    if not root.exists():
        return {"manifest_present": False, "file_count": 0, "payment_units_estimated": 0}

    py_files = list(root.rglob("*.py"))
    file_count = len(py_files)

    manifest_present = False
    razorpay_files = 0
    for fpath in py_files:
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
            if "razorpay" in text.lower():
                manifest_present = True
                razorpay_files += 1
        except Exception:
            pass

    return {
        "manifest_present": manifest_present,
        "file_count": file_count,
        "payment_units_estimated": razorpay_files * 2,  # rough estimate: ~2 units per file
    }


# ── GET /findings ─────────────────────────────────────────────────────────────


@app.get("/findings")
async def list_findings(
    scan_id: str | None = Query(None),
    state: str | None = Query(None),
    severity: str | None = Query(None),
    defect_class: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict:
    q = select(Finding)
    count_q = select(func.count()).select_from(Finding)

    filters = []
    if scan_id:
        filters.append(Finding.scan_id == scan_id)
    if state:
        filters.append(Finding.state == state)
    if severity:
        filters.append(Finding.severity == severity)
    if defect_class:
        filters.append(Finding.defect_class == defect_class)

    for f in filters:
        q = q.where(f)
        count_q = count_q.where(f)

    total = await db.scalar(count_q) or 0
    result = await db.scalars(q.order_by(Finding.created_at.desc()).limit(limit).offset(offset))
    items = list(result.all())

    return {
        "items": [
            {
                "id": f.id,
                "scan_id": f.scan_id,
                "title": title_for(f.rule_ids, f.defect_class),
                "defect_class": f.defect_class,
                "severity": f.severity,
                "confidence": f.confidence,
                "file": f.file,
                "start_line": f.start_line,
                "end_line": f.end_line,
                "state": f.state,
                "detector_source": f.detector_source,
                "exposure_estimated_paise": f.exposure_estimated_paise,
                "exposure_measured_paise": f.exposure_measured_paise,
                "remediation_status": f.remediation_status,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in items
        ],
        "total": total,
    }


# ── GET /findings/{finding_id} ────────────────────────────────────────────────


@app.get("/findings/{finding_id}")
async def get_finding(finding_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    finding = await _get_finding_or_404(finding_id, db)

    repo = await db.scalar(select(Repository).where(Repository.id == finding.repository_id))

    # Code context: read ±15 lines around start_line/end_line
    code_context: dict | None = None
    if repo and finding.file:
        try:
            file_path = Path(repo.locator) / finding.file
            if not file_path.exists():
                # Try absolute path
                file_path = Path(finding.file)
            if file_path.exists():
                lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
                total_lines = len(lines)
                ctx_start = max(0, finding.start_line - 1 - 15)
                ctx_end = min(total_lines, finding.end_line + 15)
                context_lines = lines[ctx_start:ctx_end]
                code_context = {
                    "lines": context_lines,
                    "highlight_start": finding.start_line - ctx_start,  # 1-based relative
                    "highlight_end": finding.end_line - ctx_start,       # 1-based relative
                    "file": finding.file,
                }
        except Exception:
            pass

    # Verification results
    vr_result = await db.scalars(
        select(VerificationResult).where(VerificationResult.finding_id == finding_id)
    )
    vr_list = [
        {
            "id": vr.id,
            "scenario_id": vr.scenario_id,
            "status": vr.status,
            "tier": vr.tier,
            "expected_behavior": vr.expected_behavior,
            "observed_behavior": vr.observed_behavior,
            "proof_summary": vr.proof_summary,
            "measured_impact_paise": vr.measured_impact_paise,
            "attempts": vr.attempts,
            "error_code": vr.error_code,
            "webhook_deliveries_json": vr.webhook_deliveries_json,
            "state_probe_before": vr.state_probe_before,
            "state_probe_after": vr.state_probe_after,
            "steps": vr.responses_json,
            "started_at": vr.started_at.isoformat() if vr.started_at else None,
            "finished_at": vr.finished_at.isoformat() if vr.finished_at else None,
        }
        for vr in vr_result.all()
    ]

    # Remediations
    rem_result = await db.scalars(
        select(Remediation).where(Remediation.finding_id == finding_id)
    )
    rem_list = [
        {
            "id": r.id,
            "diff": r.diff,
            "rationale": r.rationale,
            "status": r.status,
            "decided_by": r.decided_by,
            "decided_at": r.decided_at.isoformat() if r.decided_at else None,
        }
        for r in rem_result.all()
    ]

    return {
        "id": finding.id,
        "scan_id": finding.scan_id,
        "repository_id": finding.repository_id,
        "title": title_for(finding.rule_ids, finding.defect_class),
        "defect_class": finding.defect_class,
        "scenario_ids": finding.scenario_ids,
        "severity": finding.severity,
        "confidence": finding.confidence,
        "file": finding.file,
        "start_line": finding.start_line,
        "end_line": finding.end_line,
        "evidence_lines": finding.evidence_lines,
        "explanation": finding.explanation,
        "llm_reasoning": finding.llm_reasoning,
        "rule_ids": finding.rule_ids,
        "detector_source": finding.detector_source,
        "state": finding.state,
        "verification_id": finding.verification_id,
        "exposure_measured_paise": finding.exposure_measured_paise,
        "exposure_estimated_paise": finding.exposure_estimated_paise,
        "exposure_assumptions_json": finding.exposure_assumptions_json,
        "remediation_status": finding.remediation_status,
        "created_at": finding.created_at.isoformat() if finding.created_at else None,
        "code_context": code_context,
        "verification_results": vr_list,
        "remediations": rem_list,
    }


# ── POST /findings/{finding_id}/verify ───────────────────────────────────────


@app.post("/findings/{finding_id}/verify")
async def verify_finding(
    finding_id: str,
    body: VerifyFindingBody,
    db: AsyncSession = Depends(get_db),
) -> dict:
    finding = await _get_finding_or_404(finding_id, db)

    # Pick first scenario_id or default
    scenario_ids = finding.scenario_ids or []
    scenario_id = scenario_ids[0] if scenario_ids else "UNKNOWN"

    verification_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    vr = VerificationResult(
        id=verification_id,
        finding_id=finding_id,
        scenario_id=scenario_id,
        status=VerificationStatus.PENDING,
        tier="EMULATED",
        expected_behavior=f"Verify {finding.defect_class} defect via scenario {scenario_id}",
        observed_behavior=None,
    )
    db.add(vr)

    finding.state = FindingState.QUEUED_FOR_VERIFICATION
    finding.verification_id = verification_id

    job = Job(
        id=job_id,
        kind="VERIFY",
        idempotency_key=f"verify:{verification_id}",
        payload_json={
            "finding_id": finding_id,
            "verification_id": verification_id,
            "target_url": body.target_url,
            "probe_url": body.probe_url,
            "order_amount_paise": body.order_amount_paise,
        },
        status=JobStatus.PENDING,
        attempts=0,
    )
    db.add(job)
    await db.flush()

    await append_audit_event(
        db,
        actor=_human_actor(body.actor),
        event=AuditEventKind.VERIFICATION_REQUESTED,
        object_type="Finding",
        object_id=finding_id,
        metadata={"verification_id": verification_id, "scenario_id": scenario_id},
    )

    return {"verification_id": verification_id}


# ── GET /verifications/{verification_id} ──────────────────────────────────────


@app.get("/verifications/{verification_id}")
async def get_verification(verification_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    vr = await db.scalar(select(VerificationResult).where(VerificationResult.id == verification_id))
    if vr is None:
        raise HTTPException(status_code=404, detail="Verification not found")

    return {
        "id": vr.id,
        "finding_id": vr.finding_id,
        "scenario_id": vr.scenario_id,
        "status": vr.status,
        "tier": vr.tier,
        "expected_behavior": vr.expected_behavior,
        "observed_behavior": vr.observed_behavior,
        "requests_json": vr.requests_json,
        "responses_json": vr.responses_json,
        "webhook_deliveries_json": vr.webhook_deliveries_json,
        "state_probe_before": vr.state_probe_before,
        "state_probe_after": vr.state_probe_after,
        "proof_summary": vr.proof_summary,
        "measured_impact_paise": vr.measured_impact_paise,
        "attempts": vr.attempts,
        "error_code": vr.error_code,
        "started_at": vr.started_at.isoformat() if vr.started_at else None,
        "finished_at": vr.finished_at.isoformat() if vr.finished_at else None,
    }


# ── GET /verifications/{verification_id}/stream  (SSE) ────────────────────────


@app.get("/verifications/{verification_id}/stream")
async def stream_verification(verification_id: str) -> StreamingResponse:
    async def _generate() -> AsyncGenerator[str, None]:
        from payguard.shared.db import get_session_factory
        factory = get_session_factory()
        last_status: str | None = None
        steps_sent = 0
        while True:
            try:
                async with factory() as session:
                    vr = await session.scalar(
                        select(VerificationResult).where(VerificationResult.id == verification_id)
                    )
                    if vr is None:
                        yield _sse_line({"error": "verification not found"})
                        return
                    # Stream each new sandbox/verifier step (boot → deliver → probe → verdict).
                    steps = vr.responses_json or []
                    while steps_sent < len(steps):
                        step = steps[steps_sent]
                        yield _sse_line({"step": step.get("step"), "message": step.get("detail")})
                        steps_sent += 1
                    status = vr.status
                    if status != last_status:
                        last_status = status
                        yield _sse_line({"status": status})
                    if status in _VERIFY_TERMINAL:
                        yield _sse_line({
                            "status": status,
                            "proof_summary": vr.proof_summary,
                            "observed_behavior": vr.observed_behavior,
                            "measured_impact_paise": vr.measured_impact_paise,
                            "error_code": vr.error_code,
                            "attempts": vr.attempts,
                            "done": True,
                        })
                        return
            except Exception as exc:
                yield _sse_line({"error": str(exc)})
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(_generate(), media_type="text/event-stream")


# ── POST /findings/{finding_id}/dismiss ───────────────────────────────────────


@app.post("/findings/{finding_id}/dismiss")
async def dismiss_finding(
    finding_id: str,
    body: DismissFindingBody,
    db: AsyncSession = Depends(get_db),
) -> dict:
    finding = await _get_finding_or_404(finding_id, db)

    finding.state = FindingState.DISMISSED
    await append_audit_event(
        db,
        actor=_human_actor(body.actor),
        event=AuditEventKind.FINDING_STATE_CHANGED,
        object_type="Finding",
        object_id=finding_id,
        metadata={"new_state": "DISMISSED", "reason": body.reason},
    )

    return {"ok": True}


# ── POST /findings/{finding_id}/escalate ──────────────────────────────────────


@app.post("/findings/{finding_id}/escalate")
async def escalate_finding(
    finding_id: str,
    body: EscalateFindingBody,
    db: AsyncSession = Depends(get_db),
) -> dict:
    finding = await _get_finding_or_404(finding_id, db)

    finding.state = FindingState.EXCEPTION
    await append_audit_event(
        db,
        actor=_human_actor(body.actor),
        event=AuditEventKind.FINDING_STATE_CHANGED,
        object_type="Finding",
        object_id=finding_id,
        metadata={"new_state": "EXCEPTION"},
    )

    return {"ok": True}


# ── POST /findings/{finding_id}/remediation/propose ───────────────────────────


@app.post("/findings/{finding_id}/remediation/propose")
async def propose_remediation(
    finding_id: str,
    body: ProposeRemediationBody,
    db: AsyncSession = Depends(get_db),
) -> dict:
    finding = await _get_finding_or_404(finding_id, db)

    # Generate a stub diff
    diff = (
        f"--- a/{finding.file}\n"
        f"+++ b/{finding.file}\n"
        f"@@ -{finding.start_line},3 +{finding.start_line},3 @@\n"
        f"-    # Vulnerable: {finding.defect_class}\n"
        f"+    # TODO: fix {finding.defect_class} — see PayGuard finding {finding.id[:8]}\n"
    )
    rationale = "Replace the vulnerable pattern with the secure equivalent."

    remediation_id = str(uuid.uuid4())

    rem = Remediation(
        id=remediation_id,
        finding_id=finding_id,
        diff=diff,
        rationale=rationale,
        status=RemediationStatus.PROPOSED,
    )
    db.add(rem)

    finding.remediation_status = RemediationStatus.PROPOSED
    await db.flush()

    await append_audit_event(
        db,
        actor=_human_actor(body.actor),
        event=AuditEventKind.REMEDIATION_PROPOSED,
        object_type="Remediation",
        object_id=remediation_id,
        metadata={"finding_id": finding_id},
    )

    return {
        "id": remediation_id,
        "diff": diff,
        "rationale": rationale,
        "status": RemediationStatus.PROPOSED,
    }


# ── POST /remediations/{remediation_id}/approve ───────────────────────────────


@app.post("/remediations/{remediation_id}/approve")
async def approve_remediation(
    remediation_id: str,
    body: ApproveRemediationBody,
    db: AsyncSession = Depends(get_db),
) -> dict:
    rem = await db.scalar(select(Remediation).where(Remediation.id == remediation_id))
    if rem is None:
        raise HTTPException(status_code=404, detail="Remediation not found")

    rem.status = RemediationStatus.APPROVED
    rem.decided_by = body.actor
    rem.decided_at = _now()
    await append_audit_event(
        db,
        actor=_human_actor(body.actor),
        event=AuditEventKind.REMEDIATION_APPROVED,
        object_type="Remediation",
        object_id=remediation_id,
        metadata={"finding_id": rem.finding_id},
    )

    return {"ok": True}


# ── POST /remediations/{remediation_id}/reject ────────────────────────────────


@app.post("/remediations/{remediation_id}/reject")
async def reject_remediation(
    remediation_id: str,
    body: RejectRemediationBody,
    db: AsyncSession = Depends(get_db),
) -> dict:
    rem = await db.scalar(select(Remediation).where(Remediation.id == remediation_id))
    if rem is None:
        raise HTTPException(status_code=404, detail="Remediation not found")

    rem.status = RemediationStatus.REJECTED
    rem.decided_by = body.actor
    rem.decided_at = _now()
    await append_audit_event(
        db,
        actor=_human_actor(body.actor),
        event=AuditEventKind.REMEDIATION_REJECTED,
        object_type="Remediation",
        object_id=remediation_id,
        metadata={"finding_id": rem.finding_id},
    )

    return {"ok": True}


# ── GET /audit ────────────────────────────────────────────────────────────────


@app.get("/audit")
async def list_audit(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict:
    total = await db.scalar(select(func.count()).select_from(AuditEvent)) or 0
    result = await db.scalars(
        select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(limit).offset(offset)
    )
    events = list(result.all())

    chain_ok = True
    try:
        chain_ok, _ = await verify_audit_chain(db)
    except Exception:
        chain_ok = False

    return {
        "events": [
            {
                "seq": e.seq,
                "ts": e.ts.isoformat() if e.ts else None,
                "actor": e.actor,
                "event": e.event,
                "object_type": e.object_type,
                "object_id": e.object_id,
                "metadata_json": e.metadata_json,
                "hash": e.hash,
            }
            for e in events
        ],
        "total": total,
        "chain_ok": chain_ok,
    }


# ── POST /audit/verify ────────────────────────────────────────────────────────


@app.post("/audit/verify")
async def audit_verify(db: AsyncSession = Depends(get_db)) -> dict:
    n = await db.scalar(select(func.count()).select_from(AuditEvent)) or 0
    try:
        ok, error = await verify_audit_chain(db)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "n_events": n}
    return {"ok": ok, "error": error if not ok else None, "n_events": n}


# ── GET /eval/latest ──────────────────────────────────────────────────────────


@app.get("/eval/latest")
async def eval_latest() -> dict | None:
    reports_dir = Path(__file__).parent.parent.parent / "eval" / "reports" / "test"
    if not reports_dir.exists():
        return None
    json_files = sorted(
        (f for f in reports_dir.glob("*.json") if f.is_file()),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    if not json_files:
        return None
    try:
        return json.loads(json_files[0].read_text(encoding="utf-8"))
    except Exception:
        return None


# ── GET /system/status ────────────────────────────────────────────────────────


@app.get("/system/status")
async def system_status(db: AsyncSession = Depends(get_db)) -> dict:
    settings = get_settings()

    # DB check
    db_status = "ok"
    try:
        await db.scalar(select(func.now()))
    except Exception:
        db_status = "error"

    chaos = read_chaos()

    # Gateway check — chaos is reported explicitly (reachable but deliberately failing).
    if chaos.gateway:
        gateway_status = "chaos"
    else:
        gateway_status = "unreachable"
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{settings.gateway_url}/healthz")
                gateway_status = "ok" if resp.status_code == 200 else "error"
        except Exception:
            gateway_status = "unreachable"

    # LLM check
    if chaos.llm:
        llm_status = "degraded"
    else:
        llm_status = "ok"
        try:
            from payguard.llm.providers import build_analyzer_provider
            provider = build_analyzer_provider()
            if provider is None:
                llm_status = "unavailable"
        except Exception:
            llm_status = "unavailable"

    # Worker info
    worker_info: dict[str, Any] = {"last_job_at": None, "pending_jobs": 0}
    try:
        pending = await db.scalar(
            select(func.count()).select_from(Job).where(Job.status == JobStatus.PENDING)
        ) or 0
        last_job = await db.scalar(
            select(Job.created_at).where(Job.status == JobStatus.DONE).order_by(Job.created_at.desc()).limit(1)
        )
        worker_info = {
            "last_job_at": last_job.isoformat() if last_job else None,
            "pending_jobs": pending,
        }
    except Exception:
        pass

    return {
        "api": "ok",
        "db": db_status,
        "gateway": gateway_status,
        "llm": llm_status,
        "worker": worker_info,
    }


# ── GET /settings ─────────────────────────────────────────────────────────────


@app.get("/settings")
async def get_api_settings() -> dict:
    return _settings_payload()


# ── PUT /settings ─────────────────────────────────────────────────────────────


@app.put("/settings")
async def update_settings(body: UpdateSettingsBody, db: AsyncSession = Depends(get_db)) -> dict:
    if body.advisory_threshold is not None:
        _settings_override["advisory_threshold"] = body.advisory_threshold
    if body.verify_threshold is not None:
        _settings_override["verify_threshold"] = body.verify_threshold

    # Resolve the requested chaos switches. `chaos_enabled` is the legacy single toggle
    # and is treated as the LLM switch unless the explicit fields are provided.
    llm_req = body.chaos_llm if body.chaos_llm is not None else body.chaos_enabled
    gateway_req = body.chaos_gateway

    if llm_req is not None or gateway_req is not None:
        before = read_chaos()
        after = set_chaos(llm=llm_req, gateway=gateway_req)
        if after != before:
            await append_audit_event(
                db,
                actor=AuditActor.HUMAN,
                event=AuditEventKind.CHAOS_TOGGLED,
                object_type=None,
                object_id=None,
                metadata={"llm": after.llm, "gateway": after.gateway},
            )

    return _settings_payload()


# ── GET /healthz ──────────────────────────────────────────────────────────────


@app.get("/healthz")
async def healthz() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "env": settings.payguard_env,
        "gateway_mode": settings.gateway_mode,
        "demo": settings.payguard_demo,
    }
