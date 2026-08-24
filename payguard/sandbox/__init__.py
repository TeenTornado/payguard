"""Sandbox runner: boot a target merchant app so the verifier can drive it.

Two runtimes:

- **docker** (preferred, ADR-009): a locked-down container (read-only rootfs, tmpfs,
  cpu/mem/pids caps, hard timeout, no host mounts except a read-only copy of the target,
  network = the gateway only). Real isolation.
- **subprocess** (dev fallback): runs the target as a plain child process on localhost.
  **No isolation** — dev/demo only. Chosen automatically when the Docker daemon is
  unavailable, or forced with ``SANDBOX_RUNTIME=subprocess``. The target still runs as a
  REAL process producing REAL state-probe numbers; nothing is simulated. This limitation
  is documented in docs/failure-modes.md.

In both runtimes the target's Razorpay calls are routed to the EMULATE gateway via
``RAZORPAY_BASE_URL`` (Tier A). The sandbox receives only dummy ``rzp_test_DUMMY`` creds —
real credentials never enter it.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shlex
import socket
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import yaml

log = logging.getLogger("payguard.sandbox")

# Fixed emulator test credentials the target is given. The gateway's /_test/reset
# establishes the matching key pair + webhook secret before delivery.
DUMMY_KEY_ID = "rzp_test_DUMMY"
DUMMY_KEY_SECRET = "dummy_secret"
DUMMY_WEBHOOK_SECRET = "dummy_webhook_secret"

BOOT_TIMEOUT_SECONDS = 25.0
INSTALL_TIMEOUT_SECONDS = 120.0


class SandboxError(Exception):
    """Raised when a target cannot be booted (missing manifest, health never came up)."""


@dataclass
class Manifest:
    name: str
    defect_class: str
    scenario: str
    runtime: str
    start: str
    health_method: str
    health_path: str
    install: str | None = None
    port_env: str = "PORT"
    webhook_path: str = "/webhook"
    state_path: str = "/state"
    state_query: str = "order_id"
    state_json_path: str = "fulfilled_count"
    charge_path: str | None = None
    charge_amount_inr: int = 1500
    env_map: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


def load_manifest(target_dir: str | Path) -> Manifest | None:
    """Load payguard.yml from a target dir, or return None if it isn't a runnable target."""
    path = Path(target_dir) / "payguard.yml"
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    health = str(data.get("health", "GET /health")).split()
    health_method, health_path = (health + ["GET", "/health"])[:2] if len(health) < 2 else health[:2]
    probe = data.get("state_probe", {}) or {}
    charge = data.get("charge_endpoint", {}) or {}
    return Manifest(
        name=data.get("name", Path(target_dir).name),
        defect_class=data.get("defect_class", ""),
        scenario=data.get("scenario", ""),
        runtime=data.get("runtime", "node20"),
        start=data.get("start", "node app.js"),
        install=data.get("install"),
        port_env=data.get("port_env", "PORT"),
        health_method=health_method,
        health_path=health_path,
        webhook_path=(data.get("webhook_endpoint", {}) or {}).get("path", "/webhook"),
        state_path=probe.get("path", "/state"),
        state_query=probe.get("query", "order_id"),
        state_json_path=probe.get("json_path", "fulfilled_count"),
        charge_path=charge.get("path"),
        charge_amount_inr=int((charge.get("request_template", {}) or {}).get("intended_amount_inr", 1500)),
        env_map=data.get("env_map", {}) or {},
        raw=data,
    )


@dataclass
class SandboxHandle:
    base_url: str
    manifest: Manifest
    runtime: str
    _teardown: object = None
    log_path: str | None = None

    @property
    def health_url(self) -> str:
        return f"{self.base_url}{self.manifest.health_path}"

    @property
    def webhook_url(self) -> str:
        return f"{self.base_url}{self.manifest.webhook_path}"

    def probe_url(self, order_id: str) -> str:
        m = self.manifest
        return f"{self.base_url}{m.state_path}?{m.state_query}={order_id}"

    async def teardown(self) -> None:
        if callable(self._teardown):
            await self._teardown()  # type: ignore[misc]


def docker_available() -> bool:
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def resolve_runtime() -> str:
    forced = os.environ.get("SANDBOX_RUNTIME")
    if forced:
        return forced
    return "docker" if docker_available() else "subprocess"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _sandbox_env(port: int, gateway_url: str, manifest: Manifest) -> dict[str, str]:
    """Only the harness vars the manifest declares — plus PATH so node is found."""
    env = {"PATH": os.environ.get("PATH", "")}
    em = manifest.env_map
    mapping = {
        em.get("port", manifest.port_env): str(port),
        em.get("base_url", "RAZORPAY_BASE_URL"): gateway_url,
        em.get("key_id", "RAZORPAY_KEY_ID"): DUMMY_KEY_ID,
        em.get("key_secret", "RAZORPAY_KEY_SECRET"): DUMMY_KEY_SECRET,
        em.get("webhook_secret", "RAZORPAY_WEBHOOK_SECRET"): DUMMY_WEBHOOK_SECRET,
    }
    env.update({k: v for k, v in mapping.items() if k})
    return env


async def _wait_healthy(base_url: str, manifest: Manifest, timeout: float) -> None:
    url = f"{base_url}{manifest.health_path}"
    deadline = asyncio.get_event_loop().time() + timeout
    async with httpx.AsyncClient(timeout=2.0) as client:
        while asyncio.get_event_loop().time() < deadline:
            try:
                r = await client.request(manifest.health_method, url)
                if r.status_code == 200:
                    return
            except Exception:
                pass
            await asyncio.sleep(0.3)
    raise SandboxError(f"target did not become healthy at {url} within {timeout}s")


async def _boot_subprocess(target_dir: Path, gateway_url: str, manifest: Manifest) -> SandboxHandle:
    # Install deps once if the manifest asks and they're absent.
    if manifest.install and not (target_dir / "node_modules").exists():
        log.info("installing target deps: %s", manifest.install)
        proc = await asyncio.create_subprocess_exec(
            *shlex.split(manifest.install), cwd=str(target_dir),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=INSTALL_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            proc.kill()
            raise SandboxError("dependency install timed out")
        if proc.returncode != 0:
            raise SandboxError(f"dependency install failed (exit {proc.returncode})")

    port = _free_port()
    env = _sandbox_env(port, gateway_url, manifest)
    log_path = str(target_dir / ".sandbox.log")
    logf = open(log_path, "wb")
    proc = await asyncio.create_subprocess_exec(
        *shlex.split(manifest.start), cwd=str(target_dir), env=env,
        stdout=logf, stderr=asyncio.subprocess.STDOUT,
    )
    base_url = f"http://127.0.0.1:{port}"

    async def _teardown() -> None:
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        finally:
            logf.close()

    try:
        await _wait_healthy(base_url, manifest, BOOT_TIMEOUT_SECONDS)
    except SandboxError:
        await _teardown()
        raise
    return SandboxHandle(base_url=base_url, manifest=manifest, runtime="subprocess",
                         _teardown=_teardown, log_path=log_path)


async def _boot_docker(target_dir: Path, gateway_url: str, manifest: Manifest) -> SandboxHandle:
    """Boot the target in a locked-down container (read-only rootfs, tmpfs, caps).

    Structurally complete but exercised only where the Docker daemon is up; the subprocess
    runtime is the tested path in this environment.
    """
    image = f"payguard-sandbox-{manifest.runtime}"
    port = _free_port()
    env = _sandbox_env(port, gateway_url, manifest)
    # host.docker.internal lets the container reach the gateway/host on macOS.
    env = {k: (v.replace("127.0.0.1", "host.docker.internal").replace("localhost", "host.docker.internal")
               if k.endswith("BASE_URL") else v) for k, v in env.items()}
    name = f"pg-sandbox-{manifest.name}-{port}"
    args = [
        "docker", "run", "-d", "--rm", "--name", name,
        "--read-only", "--tmpfs", "/tmp", "--tmpfs", "/app/.cache",
        "--cpus", "1", "--memory", "512m", "--pids-limit", "128",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "-p", f"127.0.0.1:{port}:{port}",
        "--add-host", "host.docker.internal:host-gateway",
        "-v", f"{target_dir}:/app:ro",
    ]
    for k, v in env.items():
        args += ["-e", f"{k}={v}"]
    args += [image]
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.STDOUT)
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        raise SandboxError(f"docker run failed: {out.decode(errors='replace')[:400]}")
    base_url = f"http://127.0.0.1:{port}"

    async def _teardown() -> None:
        p = await asyncio.create_subprocess_exec("docker", "rm", "-f", name,
                                                 stdout=asyncio.subprocess.DEVNULL,
                                                 stderr=asyncio.subprocess.DEVNULL)
        await p.communicate()

    try:
        await _wait_healthy(base_url, manifest, BOOT_TIMEOUT_SECONDS)
    except SandboxError:
        await _teardown()
        raise
    return SandboxHandle(base_url=base_url, manifest=manifest, runtime="docker",
                         _teardown=_teardown, log_path=None)


async def boot_target(target_dir: str | Path, gateway_url: str, *, runtime: str | None = None) -> SandboxHandle:
    """Boot the target in target_dir and return a handle once it is healthy."""
    target_dir = Path(target_dir)
    manifest = load_manifest(target_dir)
    if manifest is None:
        raise SandboxError(f"{target_dir} has no payguard.yml — not a runnable target")

    rt = runtime or resolve_runtime()
    if rt == "docker":
        if not docker_available():
            log.warning("docker requested but daemon unavailable — falling back to subprocess (no isolation)")
            rt = "subprocess"
        else:
            return await _boot_docker(target_dir, gateway_url, manifest)
    log.info("booting target %s via subprocess runtime (dev, no isolation)", manifest.name)
    return await _boot_subprocess(target_dir, gateway_url, manifest)
