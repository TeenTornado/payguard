"""DP-2 end-to-end through the sandbox runner (the headline path).

Boots a real gateway (uvicorn on a free port) and a real Node target (subprocess
runtime), then drives DP-2 and asserts the verdict + MEASURED amount. Skipped where
node is unavailable.

Slow (boots node + gateway). Proves: VERIFIED with measured=150000 on the vulnerable
target, NOT_REPRODUCED on the safe control, ERROR (no MEASURED) under gateway chaos.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from payguard.shared.chaos import ChaosState, set_chaos, write_chaos
from payguard.shared.enums import VerificationStatus
from payguard.verifier.executor import drive_dp2_sandbox

ROOT = Path(__file__).resolve().parents[2]
TARGET_VULN = str(ROOT / "examples" / "targets" / "dup-fulfillment-node")
TARGET_SAFE = str(ROOT / "examples" / "targets" / "dup-fulfillment-node-safe")

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def chaos_file(tmp_path_factory):
    """One chaos sentinel path shared by the gateway subprocess and the test process."""
    path = tmp_path_factory.mktemp("chaos") / "chaos.json"
    write_chaos(ChaosState())
    return str(path)


@pytest.fixture(scope="module")
def gateway_url(chaos_file):
    port = _free_port()
    env = {**os.environ, "PAYGUARD_CHAOS_FILE": chaos_file}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "payguard.gateway.app:app", "--port", str(port)],
        cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(f"{url}/healthz", timeout=1).status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("gateway did not start")
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


@pytest.fixture(autouse=True)
def _subprocess_runtime(monkeypatch, chaos_file):
    monkeypatch.setenv("SANDBOX_RUNTIME", "subprocess")
    monkeypatch.setenv("PAYGUARD_CHAOS_FILE", chaos_file)  # same file the gateway reads
    write_chaos(ChaosState())
    yield
    write_chaos(ChaosState())


@pytest.mark.asyncio
async def test_dp2_verified_with_measured(gateway_url):
    outcome = await drive_dp2_sandbox(gateway_url, TARGET_VULN, 150000)
    assert outcome.status == VerificationStatus.VERIFIED.value, outcome.observed_behavior
    assert outcome.measured_impact_paise == 150000
    assert len(outcome.webhook_deliveries) == 2
    assert outcome.state_probe_before.get("fulfilled_count") == 0
    assert outcome.state_probe_after.get("fulfilled_count") == 2


@pytest.mark.asyncio
async def test_dp2_not_reproduced_on_safe(gateway_url):
    outcome = await drive_dp2_sandbox(gateway_url, TARGET_SAFE, 150000)
    assert outcome.status == VerificationStatus.NOT_REPRODUCED.value, outcome.observed_behavior
    assert outcome.measured_impact_paise is None
    assert outcome.state_probe_after.get("fulfilled_count") == 1


@pytest.mark.asyncio
async def test_dp2_gateway_chaos_errors_without_measuring(gateway_url):
    set_chaos(gateway=True)
    outcome = await drive_dp2_sandbox(gateway_url, TARGET_VULN, 150000)
    assert outcome.status == VerificationStatus.ERROR.value
    assert outcome.error_code == "GATEWAY_UNAVAILABLE"
    assert outcome.measured_impact_paise is None
    assert outcome.attempts >= 2


def _docker_up() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=5).returncode == 0
    except Exception:
        return False


@pytest.mark.skipif(not _docker_up(), reason="docker daemon not available")
@pytest.mark.asyncio
async def test_dp2_verified_in_docker_runtime(gateway_url, monkeypatch):
    """The real path: DP-2 → VERIFIED in the isolated Docker runtime."""
    # Ensure the base image exists.
    if subprocess.run(["docker", "image", "inspect", "payguard-sandbox-node20"],
                      capture_output=True).returncode != 0:
        subprocess.run(["docker", "build", "-t", "payguard-sandbox-node20",
                        str(ROOT / "sandbox-images" / "node20")], check=True,
                       capture_output=True)
    monkeypatch.setenv("SANDBOX_RUNTIME", "docker")
    outcome = await drive_dp2_sandbox(gateway_url, TARGET_VULN, 150000)
    assert outcome.status == VerificationStatus.VERIFIED.value, outcome.observed_behavior
    assert outcome.measured_impact_paise == 150000
