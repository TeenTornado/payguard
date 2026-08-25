"""
Worker: polls jobs table for PENDING scan jobs, runs the full pipeline.
Run as: python -m payguard.worker
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select

from payguard.detector.discovery import discover_payment_units
from payguard.detector.static_rules import RuleHit, run_static_rules
from payguard.llm.adapter import analyze
from payguard.llm.prompts import SYSTEM_PROMPT, build_analysis_prompt
from payguard.llm.schema import LLMFinding
from payguard.risk.features import extract_features
from payguard.risk.scorer import score_sample
from payguard.shared.audit import append_audit_event
from payguard.shared.chaos import read_chaos
from payguard.shared.db import get_session_factory
from payguard.shared.enums import (
    AuditActor,
    AuditEventKind,
    DefectClass,
    DetectorSource,
    FindingState,
    JobStatus,
    LLMStatus,
    ScanState,
    Severity,
)
from payguard.shared.models import Finding, Job, Scan

log = logging.getLogger("payguard.worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

POLL_INTERVAL = 2  # seconds
LOCK_SECONDS = 120

# Estimated exposure per defect class (in paise)
_EXPOSURE_BY_CLASS: dict[str, int] = {
    DefectClass.DUPLICATE_PAYMENT: 15000,
    DefectClass.WEBHOOK_INTEGRITY: 50000,
    DefectClass.AMOUNT_CURRENCY: 9900,
}
_DEFAULT_EXPOSURE = 10000  # ₹100


def _exposure_for(defect_class: str) -> int:
    return _EXPOSURE_BY_CLASS.get(defect_class, _DEFAULT_EXPOSURE)


def _severity_for(defect_class: str, static_hits: list[RuleHit], llm_findings: list[LLMFinding]) -> str:
    """Pick the highest severity from static hits, defaulting by defect class."""
    all_severities: list[str] = [h.severity.value for h in static_hits if h.defect_class.value == defect_class]
    _order = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    for sev in _order:
        if sev in all_severities:
            return sev
    # Default by defect class
    defaults: dict[str, str] = {
        DefectClass.WEBHOOK_INTEGRITY: Severity.CRITICAL,
        DefectClass.DUPLICATE_PAYMENT: Severity.HIGH,
        DefectClass.AMOUNT_CURRENCY: Severity.HIGH,
        DefectClass.SUSPICIOUS_CONTENT: Severity.MEDIUM,
    }
    return defaults.get(defect_class, Severity.MEDIUM)


async def _run_scan(scan_id: str, repo_path: str, session_factory) -> None:
    """Execute the full scan pipeline for one scan job."""

    async with session_factory() as session:
        async with session.begin():
            scan = await session.scalar(select(Scan).where(Scan.id == scan_id))
            if scan is None:
                log.error("Scan %s not found", scan_id)
                return

            # ── INGEST ───────────────────────────────────────────────────────
            scan.state = ScanState.INGEST
            py_count = sum(1 for _ in Path(repo_path).rglob("*.py")) if Path(repo_path).exists() else 0
            js_count = sum(
                1 for p in Path(repo_path).rglob("*")
                if p.suffix in {".js", ".ts", ".mjs", ".cjs"}
            ) if Path(repo_path).exists() else 0
            scan.stats_json = {
                "py_files": py_count,
                "js_files": js_count,
                "repo_path": repo_path,
            }
            # SCAN_STARTED is emitted once, by the API when the scan is created. The worker
            # does not re-emit it here (that produced two SCAN_STARTED rows per scan).

    # ── DISCOVER ─────────────────────────────────────────────────────────
    async with session_factory() as session:
        async with session.begin():
            scan = await session.scalar(select(Scan).where(Scan.id == scan_id))
            scan.state = ScanState.DISCOVER

    units = discover_payment_units(repo_path)

    async with session_factory() as session:
        async with session.begin():
            scan = await session.scalar(select(Scan).where(Scan.id == scan_id))
            stats = dict(scan.stats_json or {})
            stats["n_units"] = len(units)
            scan.stats_json = stats
            await append_audit_event(
                session,
                actor=AuditActor.SYSTEM,
                event=AuditEventKind.DISCOVERY_COMPLETED,
                object_type="Scan",
                object_id=scan_id,
                metadata={"n_units": len(units)},
            )

    # ── STATIC ───────────────────────────────────────────────────────────
    async with session_factory() as session:
        async with session.begin():
            scan = await session.scalar(select(Scan).where(Scan.id == scan_id))
            scan.state = ScanState.STATIC

    all_static_hits: list[tuple[str, RuleHit]] = []  # (unit.file, hit)
    for unit in units:
        hits = run_static_rules(unit)
        for hit in hits:
            all_static_hits.append((unit.file, hit))

    async with session_factory() as session:
        async with session.begin():
            scan = await session.scalar(select(Scan).where(Scan.id == scan_id))
            stats = dict(scan.stats_json or {})
            stats["n_static_hits"] = len(all_static_hits)
            scan.stats_json = stats
            scan.static_status = "OK"
            await append_audit_event(
                session,
                actor=AuditActor.SYSTEM,
                event=AuditEventKind.STATIC_ANALYSIS_COMPLETED,
                object_type="Scan",
                object_id=scan_id,
                metadata={"n_hits": len(all_static_hits)},
            )

    # ── SEMANTIC ─────────────────────────────────────────────────────────
    async with session_factory() as session:
        async with session.begin():
            scan = await session.scalar(select(Scan).where(Scan.id == scan_id))
            scan.state = ScanState.SEMANTIC

    all_llm_findings: list[tuple[str, LLMFinding]] = []  # (unit.file, finding)
    llm_failed = False
    llm_off = False
    chaos = read_chaos().llm

    from payguard.llm.grounded import llm_enabled
    if not llm_enabled():
        log.info("PAYGUARD_LLM=off — static + verifier only for scan %s", scan_id)
        llm_off = True
    elif chaos:
        log.warning("LLM chaos active — skipping LLM analysis for scan %s (static-only)", scan_id)
        llm_failed = True
    else:
        from payguard.llm.grounded import is_grounded
        grounded = is_grounded()
        if grounded:
            from payguard.llm.grounded import retrieve_for_unit
            from payguard.llm.prompts import build_grounded_analysis_prompt
        for unit in units:
            try:
                if grounded:
                    refs = retrieve_for_unit(unit.source)
                    user_prompt = build_grounded_analysis_prompt(unit, refs)
                    sid = f"grounded:{scan_id}:{unit.file}:{unit.symbol}"
                else:
                    user_prompt = build_analysis_prompt(unit)
                    sid = f"{scan_id}:{unit.file}:{unit.symbol}"
                analysis, _cache_hit = analyze(SYSTEM_PROMPT, user_prompt, sample_id=sid)
                for f in analysis.findings:
                    all_llm_findings.append((unit.file, f))
            except Exception as exc:
                log.warning("LLM analysis failed for %s: %s", unit.file, exc)
                llm_failed = True

    async with session_factory() as session:
        async with session.begin():
            scan = await session.scalar(select(Scan).where(Scan.id == scan_id))
            if llm_off:
                scan.llm_status = "OFF"
                event_kind = AuditEventKind.LLM_ANALYSIS_COMPLETED
            elif llm_failed and not all_llm_findings:
                scan.llm_status = LLMStatus.FAILED
                event_kind = AuditEventKind.LLM_ANALYSIS_DEGRADED
            elif llm_failed:
                scan.llm_status = LLMStatus.DEGRADED
                event_kind = AuditEventKind.LLM_ANALYSIS_DEGRADED
            else:
                scan.llm_status = LLMStatus.OK
                event_kind = AuditEventKind.LLM_ANALYSIS_COMPLETED
            stats = dict(scan.stats_json or {})
            stats["n_llm_findings"] = len(all_llm_findings)
            scan.stats_json = stats
            await append_audit_event(
                session,
                actor=AuditActor.LLM,
                event=event_kind,
                object_type="Scan",
                object_id=scan_id,
                metadata={"n_findings": len(all_llm_findings), "failed": llm_failed},
            )

    # ── NORMALIZE ────────────────────────────────────────────────────────
    # Merge static hits + LLM findings per (file, defect_class) with dedup.
    # Key: (file, defect_class) → one Finding using higher confidence.
    async with session_factory() as session:
        async with session.begin():
            scan = await session.scalar(select(Scan).where(Scan.id == scan_id))
            scan.state = ScanState.NORMALIZE
            repo_id = scan.repository_id

    # Group by (file, defect_class)
    MergeKey = tuple[str, str]  # (file, defect_class)

    static_by_key: dict[MergeKey, list[RuleHit]] = {}
    for file, hit in all_static_hits:
        key: MergeKey = (file, hit.defect_class.value)
        static_by_key.setdefault(key, []).append(hit)

    llm_by_key: dict[MergeKey, list[LLMFinding]] = {}
    for file, finding in all_llm_findings:
        key = (file, finding.defect_class)
        llm_by_key.setdefault(key, []).append(finding)

    all_keys: set[MergeKey] = set(static_by_key.keys()) | set(llm_by_key.keys())

    # Map unit file -> unit for line number lookup
    unit_map: dict[str, object] = {u.file: u for u in units}

    created_findings: list[Finding] = []

    async with session_factory() as session:
        async with session.begin():
            for key in all_keys:
                file, defect_class = key
                s_hits = static_by_key.get(key, [])
                l_findings = llm_by_key.get(key, [])

                has_static = bool(s_hits)
                has_llm = bool(l_findings)

                if has_static and has_llm:
                    source = DetectorSource.BOTH
                elif has_static:
                    source = DetectorSource.STATIC
                else:
                    source = DetectorSource.LLM

                # Pick highest confidence
                static_conf = max((h.confidence for h in s_hits), default=0.0)
                llm_conf = max((f.confidence for f in l_findings), default=0.0)
                confidence = max(static_conf, llm_conf)

                # Evidence lines: prefer static string lines; merge LLM int lines
                evidence: list[str] = []
                for h in s_hits:
                    evidence.extend(h.evidence_lines)
                for f in l_findings:
                    evidence.extend(str(ln) for ln in f.evidence_lines)
                evidence = list(dict.fromkeys(evidence))  # dedup, order-preserving

                # Rule IDs from static hits
                rule_ids: list[str] = list({h.rule_id for h in s_hits})

                # Scenario IDs merged
                scenario_ids: list[str] = []
                for h in s_hits:
                    scenario_ids.extend(h.scenario_ids)
                for f in l_findings:
                    scenario_ids.extend(f.scenario_ids)
                scenario_ids = list(dict.fromkeys(scenario_ids))

                # Explanation: prefer highest-confidence source
                if s_hits and static_conf >= llm_conf:
                    best_static = max(s_hits, key=lambda h: h.confidence)
                    explanation = best_static.explanation
                    llm_reasoning = l_findings[0].explanation if l_findings else None
                elif l_findings:
                    best_llm = max(l_findings, key=lambda f: f.confidence)
                    explanation = best_llm.explanation
                    llm_reasoning = best_llm.explanation
                else:
                    explanation = f"Detected {defect_class} in {file}"
                    llm_reasoning = None

                # Line numbers: from the unit if available
                unit = unit_map.get(file)
                start_line = getattr(unit, "start_line", 1) if unit else 1
                end_line = getattr(unit, "end_line", 1) if unit else 1

                # For LLM-only findings, try to use evidence_lines for start/end
                if not has_static and l_findings:
                    all_ln = [ln for f in l_findings for ln in f.evidence_lines if ln > 0]
                    if all_ln:
                        start_line = min(all_ln)
                        end_line = max(all_ln)

                severity = _severity_for(defect_class, s_hits, l_findings)

                finding = Finding(
                    id=str(uuid.uuid4()),
                    scan_id=scan_id,
                    repository_id=repo_id,
                    defect_class=defect_class,
                    scenario_ids=scenario_ids,
                    severity=severity,
                    confidence=round(confidence, 4),
                    file=file,
                    start_line=start_line,
                    end_line=end_line,
                    evidence_lines=evidence[:20],
                    explanation=explanation,
                    llm_reasoning=llm_reasoning,
                    rule_ids=rule_ids,
                    detector_source=source,
                    state=FindingState.ADVISORY,
                    exposure_estimated_paise=_exposure_for(defect_class),
                )
                session.add(finding)
                created_findings.append(finding)

            await session.flush()

            # Append audit events for each finding
            for finding in created_findings:
                await append_audit_event(
                    session,
                    actor=AuditActor.SYSTEM,
                    event=AuditEventKind.FINDING_CREATED,
                    object_type="Finding",
                    object_id=finding.id,
                    metadata={
                        "defect_class": finding.defect_class,
                        "severity": finding.severity,
                        "confidence": finding.confidence,
                        "detector_source": finding.detector_source,
                    },
                )

            scan = await session.scalar(select(Scan).where(Scan.id == scan_id))
            stats = dict(scan.stats_json or {})
            stats["n_findings"] = len(created_findings)
            scan.stats_json = stats

    # ── SCORE ────────────────────────────────────────────────────────────
    async with session_factory() as session:
        async with session.begin():
            scan = await session.scalar(select(Scan).where(Scan.id == scan_id))
            scan.state = ScanState.SCORE

    # Score each finding individually
    async with session_factory() as session:
        async with session.begin():
            result = await session.scalars(select(Finding).where(Finding.scan_id == scan_id))
            db_findings = list(result.all())

            for finding in db_findings:
                defect_class = finding.defect_class
                file = finding.file

                s_hits_for_file = [h for (f, h) in all_static_hits if f == file and h.defect_class.value == defect_class]
                l_finds_for_file = [lf for (f, lf) in all_llm_findings if f == file and lf.defect_class == defect_class]

                fv = extract_features(defect_class, s_hits_for_file, l_finds_for_file)
                sample_risk = score_sample(f"{scan_id}:{file}:{defect_class}", [fv])

                estimated = _exposure_for(defect_class)
                finding.exposure_estimated_paise = estimated
                finding.exposure_assumptions_json = {
                    "scorer_version": sample_risk.scorer_version,
                    "score": sample_risk.defects[0].score if sample_risk.defects else 0.0,
                    "basis": "class_heuristic",
                }

    # ── SELECT_SCENARIOS ─────────────────────────────────────────────────
    async with session_factory() as session:
        async with session.begin():
            scan = await session.scalar(select(Scan).where(Scan.id == scan_id))
            scan.state = ScanState.SELECT_SCENARIOS

            result = await session.scalars(select(Finding).where(Finding.scan_id == scan_id))
            db_findings = list(result.all())

            # Scenario IDs are already set during normalize; ensure they're on the record
            # (they were set at creation time; this step just confirms they're there)
            for finding in db_findings:
                if not finding.scenario_ids:
                    # Fallback defaults by defect class
                    defaults: dict[str, list[str]] = {
                        DefectClass.DUPLICATE_PAYMENT: ["DP-1"],
                        DefectClass.WEBHOOK_INTEGRITY: ["WI-1"],
                        DefectClass.AMOUNT_CURRENCY: ["AC-1"],
                        DefectClass.SUSPICIOUS_CONTENT: [],
                    }
                    finding.scenario_ids = defaults.get(finding.defect_class, [])

            # Mark scan DONE
            scan.state = ScanState.DONE
            scan.finished_at = datetime.now(timezone.utc)
            stats = dict(scan.stats_json or {})
            stats["n_findings"] = len(db_findings)
            scan.stats_json = stats


async def _mark_job(session_factory, job_id: str, status: JobStatus, error: str | None = None) -> None:
    async with session_factory() as session:
        async with session.begin():
            job = await session.scalar(select(Job).where(Job.id == job_id))
            if job is not None:
                job.status = status
                if error is not None:
                    job.last_error = error


async def _handle_scan_job(session_factory, job_id: str, payload: dict) -> None:
    scan_id = payload.get("scan_id", "")
    repo_path = payload.get("repo_path", "")
    log.info("Processing SCAN job %s scan=%s repo=%s", job_id, scan_id, repo_path)
    try:
        await _run_scan(scan_id, repo_path, session_factory)
        await _mark_job(session_factory, job_id, JobStatus.DONE)
        log.info("Job %s completed", job_id)
    except Exception as exc:
        log.exception("Scan job %s failed: %s", job_id, exc)
        async with session_factory() as session:
            async with session.begin():
                job = await session.scalar(select(Job).where(Job.id == job_id))
                if job is not None:
                    job.status = JobStatus.FAILED
                    job.last_error = str(exc)
                scan = await session.scalar(select(Scan).where(Scan.id == scan_id))
                if scan is not None:
                    scan.state = ScanState.FAILED
                    scan.finished_at = datetime.now(timezone.utc)
                await append_audit_event(
                    session,
                    actor=AuditActor.SYSTEM,
                    event=AuditEventKind.SCAN_FAILED,
                    object_type="Scan",
                    object_id=scan_id,
                    metadata={"error": str(exc), "failed": True},
                )


async def _handle_verify_job(session_factory, job_id: str, payload: dict) -> None:
    # Imported here to keep the scan-only worker import path light and avoid a cycle.
    from payguard.verifier.executor import execute_verification

    verification_id = payload.get("verification_id", "")
    finding_id = payload.get("finding_id", "")
    log.info("Processing VERIFY job %s verification=%s", job_id, verification_id)
    try:
        await execute_verification(session_factory, verification_id, finding_id)
        await _mark_job(session_factory, job_id, JobStatus.DONE)
        log.info("Verify job %s completed", job_id)
    except Exception as exc:
        log.exception("Verify job %s failed: %s", job_id, exc)
        await _mark_job(session_factory, job_id, JobStatus.FAILED, error=str(exc))


async def _poll_jobs(session_factory) -> None:
    """Continuously claim PENDING SCAN and VERIFY jobs and dispatch them by kind."""
    while True:
        try:
            job_id: str | None = None
            kind: str | None = None
            payload: dict | None = None

            async with session_factory() as session:
                async with session.begin():
                    now = datetime.now(timezone.utc)
                    job = await session.scalar(
                        select(Job)
                        .where(
                            Job.kind.in_(("SCAN", "VERIFY")),
                            Job.status == JobStatus.PENDING,
                        )
                        .order_by(Job.created_at)
                        .limit(1)
                    )
                    if job is not None:
                        job.status = JobStatus.RUNNING
                        job.attempts = (job.attempts or 0) + 1
                        job.locked_until = now + timedelta(seconds=LOCK_SECONDS)
                        job_id = job.id
                        kind = job.kind
                        payload = job.payload_json

            if job_id is not None and payload is not None:
                if kind == "SCAN":
                    await _handle_scan_job(session_factory, job_id, payload)
                elif kind == "VERIFY":
                    await _handle_verify_job(session_factory, job_id, payload)
        except Exception as exc:
            log.exception("Poll loop error: %s", exc)

        await asyncio.sleep(POLL_INTERVAL)


async def main() -> None:
    log.info("PayGuard worker starting")
    session_factory = get_session_factory()
    await asyncio.gather(_poll_jobs(session_factory))


if __name__ == "__main__":
    asyncio.run(main())
