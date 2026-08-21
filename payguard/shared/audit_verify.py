"""CLI: recompute audit hash chain and exit non-zero on any tampering."""
import asyncio
import sys

from sqlalchemy.ext.asyncio import AsyncSession

from payguard.shared.audit import verify_audit_chain
from payguard.shared.db import get_session_factory


async def _run() -> None:
    factory = get_session_factory()
    async with factory() as session:
        ok, msg = await verify_audit_chain(session)
    if ok:
        print("audit chain: OK")
    else:
        print(f"audit chain: FAILED — {msg}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
