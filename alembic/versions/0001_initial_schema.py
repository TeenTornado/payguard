"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # repositories
    op.create_table(
        "repositories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("locator", sa.Text, nullable=False),
        sa.Column("commit_sha", sa.String(40), nullable=True),
        sa.Column("manifest_present", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # scans
    op.create_table(
        "scans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("repository_id", sa.String(36), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("llm_status", sa.String(16), nullable=False, server_default="OK"),
        sa.Column("static_status", sa.String(16), nullable=False, server_default="OK"),
        sa.Column("stats_json", sa.JSON, nullable=True),
    )
    op.create_index("ix_scans_repository_id", "scans", ["repository_id"])

    # findings
    op.create_table(
        "findings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scan_id", sa.String(36), sa.ForeignKey("scans.id"), nullable=False),
        sa.Column("repository_id", sa.String(36), sa.ForeignKey("repositories.id"), nullable=False),
        sa.Column("defect_class", sa.String(32), nullable=False),
        sa.Column("scenario_ids", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("file", sa.Text, nullable=False),
        sa.Column("start_line", sa.Integer, nullable=False),
        sa.Column("end_line", sa.Integer, nullable=False),
        sa.Column("evidence_lines", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("explanation", sa.Text, nullable=False),
        sa.Column("llm_reasoning", sa.Text, nullable=True),
        sa.Column("rule_ids", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("detector_source", sa.String(16), nullable=False),
        sa.Column("state", sa.String(32), nullable=False, server_default="ADVISORY"),
        sa.Column("verification_id", sa.String(36), nullable=True),
        sa.Column("exposure_measured_paise", sa.BigInteger, nullable=True),
        sa.Column("exposure_estimated_paise", sa.BigInteger, nullable=True),
        sa.Column("exposure_assumptions_json", sa.JSON, nullable=True),
        sa.Column("remediation_status", sa.String(16), nullable=False, server_default="NONE"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_findings_scan_id", "findings", ["scan_id"])
    op.create_index("ix_findings_repository_id", "findings", ["repository_id"])
    op.create_index("ix_findings_state", "findings", ["state"])
    op.create_index("ix_findings_defect_class", "findings", ["defect_class"])

    # verification_results
    op.create_table(
        "verification_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("finding_id", sa.String(36), sa.ForeignKey("findings.id"), nullable=False),
        sa.Column("scenario_id", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("tier", sa.String(16), nullable=False),
        sa.Column("expected_behavior", sa.Text, nullable=False),
        sa.Column("observed_behavior", sa.Text, nullable=True),
        sa.Column("requests_json", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("responses_json", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("webhook_deliveries_json", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("state_probe_before", sa.JSON, nullable=True),
        sa.Column("state_probe_after", sa.JSON, nullable=True),
        sa.Column("proof_summary", sa.Text, nullable=True),
        sa.Column("measured_impact_paise", sa.BigInteger, nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="1"),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_verification_results_finding_id", "verification_results", ["finding_id"])

    # jobs
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(255), unique=True, nullable=False),
        sa.Column("payload_json", sa.JSON, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_kind", "jobs", ["kind"])

    # audit_events — append-only hash-chained table
    op.create_table(
        "audit_events",
        sa.Column("seq", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("object_type", sa.String(64), nullable=True),
        sa.Column("object_id", sa.String(36), nullable=True),
        sa.Column("metadata_json", sa.JSON, nullable=True),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
    )
    op.create_index("ix_audit_events_ts", "audit_events", ["ts"])

    # Enforce append-only: grant only INSERT + SELECT to the app role
    # (no UPDATE/DELETE). This is advisory when running as superuser locally;
    # in prod, create a restricted role and revoke UPDATE/DELETE.
    op.execute("""
        CREATE RULE no_update_audit AS ON UPDATE TO audit_events DO INSTEAD NOTHING;
    """)
    op.execute("""
        CREATE RULE no_delete_audit AS ON DELETE TO audit_events DO INSTEAD NOTHING;
    """)

    # remediations
    op.create_table(
        "remediations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("finding_id", sa.String(36), sa.ForeignKey("findings.id"), nullable=False),
        sa.Column("diff", sa.Text, nullable=False),
        sa.Column("rationale", sa.Text, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="PROPOSED"),
        sa.Column("decided_by", sa.String(255), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reverify_result_id", sa.String(36), nullable=True),
    )
    op.create_index("ix_remediations_finding_id", "remediations", ["finding_id"])

    # eval_reports
    op.create_table(
        "eval_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("dataset_version", sa.String(32), nullable=False),
        sa.Column("git_sha", sa.String(40), nullable=False),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("split", sa.String(8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("report_json", sa.JSON, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("eval_reports")
    op.drop_table("remediations")
    op.execute("DROP RULE IF EXISTS no_delete_audit ON audit_events;")
    op.execute("DROP RULE IF EXISTS no_update_audit ON audit_events;")
    op.drop_table("audit_events")
    op.drop_table("jobs")
    op.drop_table("verification_results")
    op.drop_table("findings")
    op.drop_table("scans")
    op.drop_table("repositories")
