"""
`payguard llm doctor` — connectivity check for all configured LLM profiles.

Sends one minimal JSON request per profile and reports:
  model, latency (ms), finish_reason, input/output tokens, content[:80]

Usage:
    python -m payguard llm doctor
    payguard llm doctor
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import yaml


def _load_profiles() -> dict:
    limits_file = Path(__file__).parent.parent.parent / "config" / "llm_limits.yml"
    if not limits_file.exists():
        return {}
    return yaml.safe_load(limits_file.read_text()).get("profiles", {})


def _probe(
    *,
    label: str,
    base_url: str,
    api_key: str,
    model: str,
) -> None:
    import openai

    if not api_key:
        print(f"  {label:<20} SKIP  (no api_key)")
        return

    client = openai.OpenAI(base_url=base_url, api_key=api_key, max_retries=0)
    t0 = time.monotonic()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": 'Return exactly: {"ok":true}'}],
            temperature=0,
            max_tokens=256,
        )
        elapsed_ms = (time.monotonic() - t0) * 1000
        choice = resp.choices[0]
        usage = resp.usage
        reasoning = None
        if usage:
            details = getattr(usage, "completion_tokens_details", None)
            if details:
                reasoning = getattr(details, "reasoning_tokens", None)
        content = (choice.message.content or "")[:80]
        print(
            f"  {label:<20} OK    model={model} "
            f"latency={elapsed_ms:.0f}ms "
            f"finish={choice.finish_reason} "
            f"in={getattr(usage,'prompt_tokens','?')} "
            f"out={getattr(usage,'completion_tokens','?')} "
            f"reasoning={reasoning} "
            f"content={repr(content)}"
        )
    except Exception as exc:
        elapsed_ms = (time.monotonic() - t0) * 1000
        print(f"  {label:<20} ERROR {type(exc).__name__}: {str(exc)[:120]}")


def run_doctor() -> None:
    """Probe all configured profiles and print results."""
    profiles = _load_profiles()

    print("PayGuard LLM Doctor\n")

    # Primary analyzer
    print("[analyzer]")
    _probe(
        label="primary (env)",
        base_url=os.environ.get("PAYGUARD_LLM_BASE_URL", ""),
        api_key=os.environ.get("PAYGUARD_LLM_API_KEY", ""),
        model=os.environ.get("PAYGUARD_LLM_MODEL", ""),
    )
    _probe(
        label="fallback (env)",
        base_url=os.environ.get("PAYGUARD_FALLBACK_BASE_URL", ""),
        api_key=os.environ.get("PAYGUARD_FALLBACK_API_KEY", ""),
        model=os.environ.get("PAYGUARD_FALLBACK_MODEL", ""),
    )

    # Primary generator
    print("\n[generator]")
    _probe(
        label="primary (env)",
        base_url=os.environ.get("PAYGUARD_GEN_BASE_URL", ""),
        api_key=os.environ.get("PAYGUARD_GEN_API_KEY") or os.environ.get("GROQ_API_KEY", ""),
        model=os.environ.get("PAYGUARD_GEN_MODEL", ""),
    )

    # All named profiles from config/llm_limits.yml
    print("\n[named profiles]")
    for name, cfg in profiles.items():
        _probe(
            label=name,
            base_url=cfg.get("base_url", ""),
            api_key=cfg.get("api_key", ""),
            model=cfg.get("model", ""),
        )

    print()
