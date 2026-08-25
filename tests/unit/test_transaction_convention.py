"""Grep-guard: route handlers must not manage transactions.

The transaction is owned by the ``get_db`` dependency (commit on clean return, rollback
on exception). A handler that opens ``async with db.begin()`` after a read collides with
SQLAlchemy 2.0 autobegin and 500s — the exact regression fixed on 2026-08-24 (see
FAILURES.md). This test fails CI if that pattern reappears anywhere in the API module.
"""
from __future__ import annotations

import re
from pathlib import Path

API_APP = Path(__file__).resolve().parents[2] / "payguard" / "api" / "app.py"

FORBIDDEN = [
    re.compile(r"\bdb\.begin\("),
    re.compile(r"\bdb\.commit\("),
    re.compile(r"\bdb\.rollback\("),
]


def test_api_routes_do_not_manage_transactions() -> None:
    source = API_APP.read_text(encoding="utf-8")
    offenders: list[str] = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for pat in FORBIDDEN:
            if pat.search(line):
                offenders.append(f"{API_APP.name}:{lineno}: {stripped}")

    assert not offenders, (
        "Route handlers must not call db.begin()/commit()/rollback(); "
        "get_db owns the transaction. Offending lines:\n" + "\n".join(offenders)
    )
