"""Cross-process chaos sentinel.

The API, the worker, and the gateway run as separate OS processes, so an in-memory
flag in one cannot be seen by the others. Chaos state therefore lives in a small JSON
file that every process reads on demand:

    {"llm": bool, "gateway": bool}

- ``llm``     — the worker skips LLM analysis; scans report ``llm_status=FAILED``
                (static-only fallback path).
- ``gateway`` — the gateway service returns 503 on payment/verification calls,
                exercising the verifier's bounded-retry → ERROR path.

Limitation (documented in docs/failure-modes.md): this is a single global switch for
the whole host. It has no per-user / per-tenant scope and is unsuitable for anything
beyond a single-operator demo. Point ``PAYGUARD_CHAOS_FILE`` at a temp path to isolate
tests.
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path

# Deliberate world-readable path: a single-operator demo switch, not a secret store.
# Its global scope is a documented limitation (docs/failure-modes.md).
_DEFAULT_PATH = "/tmp/.payguard_chaos.json"  # noqa: S108


def chaos_path() -> Path:
    """Resolve the sentinel path fresh each call so tests can redirect it via env."""
    return Path(os.environ.get("PAYGUARD_CHAOS_FILE", _DEFAULT_PATH))


@dataclass(frozen=True)
class ChaosState:
    llm: bool = False
    gateway: bool = False

    def any(self) -> bool:
        return self.llm or self.gateway

    def to_dict(self) -> dict[str, bool]:
        return {"llm": self.llm, "gateway": self.gateway}


def read_chaos() -> ChaosState:
    """Return the current chaos state. Missing/corrupt file → all-off (fail safe)."""
    try:
        raw = json.loads(chaos_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return ChaosState()
    return ChaosState(llm=bool(raw.get("llm")), gateway=bool(raw.get("gateway")))


def write_chaos(state: ChaosState) -> None:
    """Persist chaos state. When everything is off the file is removed (all-off default)."""
    path = chaos_path()
    if not state.any():
        path.unlink(missing_ok=True)
        return
    path.write_text(json.dumps(state.to_dict()), encoding="utf-8")


def set_chaos(*, llm: bool | None = None, gateway: bool | None = None) -> ChaosState:
    """Apply a partial update, leaving unspecified switches untouched, and persist."""
    current = read_chaos()
    new = ChaosState(
        llm=current.llm if llm is None else llm,
        gateway=current.gateway if gateway is None else gateway,
    )
    write_chaos(new)
    return new


def _parse_switch(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.lower() in {"1", "on", "true", "yes"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Toggle PayGuard chaos switches.")
    parser.add_argument("--llm", choices=["on", "off"], help="Simulate LLM degradation")
    parser.add_argument("--gateway", choices=["on", "off"], help="Simulate gateway failures")
    parser.add_argument("--off", action="store_true", help="Turn everything off")
    args = parser.parse_args()

    if args.off:
        write_chaos(ChaosState())
    else:
        set_chaos(llm=_parse_switch(args.llm), gateway=_parse_switch(args.gateway))

    state = read_chaos()
    print(f"chaos: llm={state.llm} gateway={state.gateway}  ({chaos_path()})")


if __name__ == "__main__":
    main()
