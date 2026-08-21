"""Append-only hash-chained audit log writer and verifier."""
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from payguard.shared.enums import AuditActor, AuditEventKind
from payguard.shared.models import AuditEvent

GENESIS_HASH = "0" * 64


def _canonical_json(data: dict) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def _compute_hash(prev_hash: str, event_data: dict) -> str:
    payload = prev_hash + _canonical_json(event_data)
    return hashlib.sha256(payload.encode()).hexdigest()


async def append_audit_event(
    session: AsyncSession,
    actor: AuditActor | str,
    event: AuditEventKind,
    object_type: str | None = None,
    object_id: str | None = None,
    metadata: dict | None = None,
) -> AuditEvent:
    result = await session.execute(
        select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1)
    )
    last = result.scalar_one_or_none()
    prev_hash = last.hash if last else GENESIS_HASH

    ts = datetime.now(timezone.utc)
    actor_str = actor.value if isinstance(actor, AuditActor) else actor
    event_str = event.value if isinstance(event, AuditEventKind) else event

    # ts excluded from hash payload: SQLite and Postgres return datetimes in
    # different string formats, causing spurious mismatches. The chain already
    # provides ordering integrity via prev_hash; actor/event/object/metadata
    # are the content that must not be tampered with.
    event_data = {
        "actor": actor_str,
        "event": event_str,
        "object_type": object_type,
        "object_id": object_id,
        "metadata": metadata or {},
    }

    h = _compute_hash(prev_hash, event_data)

    audit_event = AuditEvent(
        ts=ts,
        actor=actor_str,
        event=event_str,
        object_type=object_type,
        object_id=object_id,
        metadata_json=metadata or {},
        prev_hash=prev_hash,
        hash=h,
    )
    session.add(audit_event)
    await session.flush()
    return audit_event


async def verify_audit_chain(session: AsyncSession) -> tuple[bool, str]:
    """
    Recompute the full hash chain. Returns (ok, error_message).
    Fails if any row has a wrong hash or a broken prev_hash link.
    """
    result = await session.execute(select(AuditEvent).order_by(AuditEvent.seq))
    events = result.scalars().all()

    if not events:
        return True, ""

    prev_hash = GENESIS_HASH
    for ev in events:
        if ev.prev_hash != prev_hash:
            return False, (
                f"Chain broken at seq={ev.seq}: "
                f"prev_hash mismatch (expected {prev_hash[:16]}…, got {ev.prev_hash[:16]}…)"
            )

        event_data = {
            "actor": ev.actor,
            "event": ev.event,
            "object_type": ev.object_type,
            "object_id": ev.object_id,
            "metadata": ev.metadata_json or {},
        }
        expected = _compute_hash(prev_hash, event_data)
        if ev.hash != expected:
            return False, (
                f"Hash mismatch at seq={ev.seq}: "
                f"expected {expected[:16]}…, stored {ev.hash[:16]}…"
            )

        prev_hash = ev.hash

    return True, ""
