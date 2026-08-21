"""SQLAlchemy ORM models. All enums are stored as strings (never bare ints)."""
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from payguard.shared.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_type: Mapped[str] = mapped_column(String(32))  # RepositorySourceType
    locator: Mapped[str] = mapped_column(Text)
    commit_sha: Mapped[str | None] = mapped_column(String(40))
    manifest_present: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    scans: Mapped[list["Scan"]] = relationship(back_populates="repository")
    findings: Mapped[list["Finding"]] = relationship(back_populates="repository")


class Scan(Base):
    __tablename__ = "scans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id"))
    state: Mapped[str] = mapped_column(String(32))  # ScanState
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    llm_status: Mapped[str] = mapped_column(String(16), default="OK")  # LLMStatus
    static_status: Mapped[str] = mapped_column(String(16), default="OK")  # AnalysisStatus
    stats_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    repository: Mapped["Repository"] = relationship(back_populates="scans")
    findings: Mapped[list["Finding"]] = relationship(back_populates="scan")


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scan_id: Mapped[str] = mapped_column(ForeignKey("scans.id"))
    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id"))
    defect_class: Mapped[str] = mapped_column(String(32))  # DefectClass
    scenario_ids: Mapped[list] = mapped_column(JSON, default=list)
    severity: Mapped[str] = mapped_column(String(16))  # Severity
    confidence: Mapped[float] = mapped_column(Float)
    file: Mapped[str] = mapped_column(Text)
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    evidence_lines: Mapped[list] = mapped_column(JSON, default=list)
    explanation: Mapped[str] = mapped_column(Text)
    llm_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule_ids: Mapped[list] = mapped_column(JSON, default=list)
    detector_source: Mapped[str] = mapped_column(String(16))  # DetectorSource
    state: Mapped[str] = mapped_column(String(32), default="ADVISORY")  # FindingState
    verification_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    exposure_measured_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    exposure_estimated_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    exposure_assumptions_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    remediation_status: Mapped[str] = mapped_column(String(16), default="NONE")  # RemediationStatus
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    scan: Mapped["Scan"] = relationship(back_populates="findings")
    repository: Mapped["Repository"] = relationship(back_populates="findings")
    verification_results: Mapped[list["VerificationResult"]] = relationship(back_populates="finding")
    remediations: Mapped[list["Remediation"]] = relationship(back_populates="finding")


class VerificationResult(Base):
    __tablename__ = "verification_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id"))
    scenario_id: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24))  # VerificationStatus
    tier: Mapped[str] = mapped_column(String(16))  # EvidenceTier
    expected_behavior: Mapped[str] = mapped_column(Text)
    observed_behavior: Mapped[str | None] = mapped_column(Text, nullable=True)
    requests_json: Mapped[list] = mapped_column(JSON, default=list)
    responses_json: Mapped[list] = mapped_column(JSON, default=list)
    webhook_deliveries_json: Mapped[list] = mapped_column(JSON, default=list)
    state_probe_before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    state_probe_after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    proof_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    measured_impact_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    finding: Mapped["Finding"] = relationship(back_populates="verification_results")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True)
    payload_json: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")  # JobStatus
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditEvent(Base):
    """Append-only hash-chained audit log. No UPDATE/DELETE permitted (enforced by DB role)."""
    __tablename__ = "audit_events"

    # Integer in ORM (works for both SQLite unit tests and Postgres via Alembic BigInteger migration)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor: Mapped[str] = mapped_column(String(64))  # AuditActor or HUMAN:<name>
    event: Mapped[str] = mapped_column(String(64))  # AuditEventKind
    object_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    object_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class Remediation(Base):
    __tablename__ = "remediations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id"))
    diff: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="PROPOSED")  # RemediationStatus
    decided_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reverify_result_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    finding: Mapped["Finding"] = relationship(back_populates="remediations")


class EvalReport(Base):
    __tablename__ = "eval_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dataset_version: Mapped[str] = mapped_column(String(32))
    git_sha: Mapped[str] = mapped_column(String(40))
    model_id: Mapped[str] = mapped_column(String(128))
    split: Mapped[str] = mapped_column(String(8))  # train / val / test
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    report_json: Mapped[dict] = mapped_column(JSON)
