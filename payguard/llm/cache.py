"""
Disk cache for LLM responses.

Cache key: sha256(provider|base_url|model|temperature|prompt_version|user_prompt)
- provider and base_url are in the key so different endpoints never share entries
- prompt_version (e.g. "v1") means bumping the version invalidates old entries
- temperature is included because temperature=0 vs 0.2 produces different outputs

Cache dir: PAYGUARD_LLM_CACHE_DIR env var, default dataset/llm_cache/ (repo-relative).
The cache IS committed for demo-replay without a live API key.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def _cache_root() -> Path:
    env = os.environ.get("PAYGUARD_LLM_CACHE_DIR", "")
    if env:
        p = Path(env)
        if not p.is_absolute():
            p = Path(__file__).parent.parent.parent / p
        return p
    return Path(__file__).parent.parent.parent / "dataset" / "llm_cache"


def _key(
    provider: str,
    base_url: str,
    model: str,
    temperature: float,
    prompt_version: str,
    user_prompt: str,
) -> str:
    raw = "|".join([provider, base_url, model, str(temperature), prompt_version, user_prompt])
    return hashlib.sha256(raw.encode()).hexdigest()


def cache_get(
    provider: str,
    base_url: str,
    model: str,
    temperature: float,
    prompt_version: str,
    user_prompt: str,
) -> dict | None:
    key = _key(provider, base_url, model, temperature, prompt_version, user_prompt)
    path = _cache_root() / key[:2] / f"{key}.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            path.unlink(missing_ok=True)
    return None


def cache_put(
    provider: str,
    base_url: str,
    model: str,
    temperature: float,
    prompt_version: str,
    user_prompt: str,
    response: dict,
) -> None:
    key = _key(provider, base_url, model, temperature, prompt_version, user_prompt)
    path = _cache_root() / key[:2] / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(response))


def cache_key_hex(
    provider: str,
    base_url: str,
    model: str,
    temperature: float,
    prompt_version: str,
    user_prompt: str,
) -> str:
    return _key(provider, base_url, model, temperature, prompt_version, user_prompt)
