"""
LLM adapter: provider routing + cache + cost ledger.

ADR-001: LLM output is a hypothesis, never a verdict.
ADR-002: No LLM for deterministic checks (HMAC math, paise arithmetic).
ADR-003: LLM never receives tools.

Failure ladder:
  1. Hit disk cache → return cached LLMAnalysis (cache_hit=True)
  2. Call provider → parse JSON → validate schema → cache + return
  3. JSON parse error → retry once with stricter instruction
  4. Still fails → return LLMAnalysis(findings=[], analysis_notes="PARSE_ERROR:...")
  5. Rate limited → return LLMAnalysis(findings=[], analysis_notes="RATE_LIMITED")
  6. API error → return LLMAnalysis(findings=[], analysis_notes="API_ERROR:...")
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from payguard.llm.cache import cache_get, cache_put
from payguard.llm.prompts import PROMPT_VERSION
from payguard.llm.providers import (
    AnthropicProvider,
    CompletionResult,
    OpenAICompatProvider,
    ProviderError,
    RateLimitedError,
)
from payguard.llm.schema import LLMAnalysis

if TYPE_CHECKING:
    pass

LEDGER_PATH = Path(__file__).parent.parent.parent / "reports" / "llm_cost_ledger.jsonl"

# USD per 1M tokens — fallback estimates for cost ledger
_PRICE_PER_1M: dict[str, dict[str, float]] = {
    "gemini-2.5-flash":              {"input": 0.075, "output": 0.30},
    "llama-3.3-70b-versatile":       {"input": 0.05,  "output": 0.08},
    "meta-llama/llama-3.3-70b-instruct": {"input": 0.00, "output": 0.00},
    "claude-haiku-4-5-20251001":     {"input": 0.80,  "output": 4.00},
    "claude-sonnet-4-6":             {"input": 3.00,  "output": 15.00},
}


def _cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    prices = _PRICE_PER_1M.get(model, {"input": 0.00, "output": 0.00})
    return (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000


def _append_ledger(entry: dict) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _extract_json(text: str) -> str:
    """Extract JSON object from text that may have surrounding prose or fences."""
    text = text.strip()
    if text.startswith("{"):
        return text
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return m.group(1)
    m = re.search(r"(\{.*\})", text, re.DOTALL)
    if m:
        return m.group(1)
    return text


def _parse_analysis(text: str) -> LLMAnalysis:
    json_str = _extract_json(text)
    data = json.loads(json_str)
    return LLMAnalysis.model_validate(data)


AnyProvider = OpenAICompatProvider | AnthropicProvider


def analyze(
    system_prompt: str,
    user_prompt: str,
    provider: AnyProvider | None = None,
    sample_id: str = "",
) -> tuple[LLMAnalysis, bool]:
    """
    Run LLM analysis. Returns (LLMAnalysis, cache_hit).
    Never raises — failures are surfaced via analysis_notes.
    """
    if provider is None:
        from payguard.llm.providers import build_analyzer_provider
        provider = build_analyzer_provider()

    if provider is None:
        analysis = LLMAnalysis(findings=[], analysis_notes="API_ERROR:provider not configured")
        _append_ledger({
            "ts": datetime.now(timezone.utc).isoformat(),
            "provider": "none", "base_url": "", "model": "",
            "sample_id": sample_id,
            "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
            "cached": False, "success": False,
            "error": "provider not configured",
        })
        return analysis, False

    # Cache lookup
    cached = cache_get(
        provider=provider.provider,
        base_url=provider.base_url,
        model=provider.model,
        temperature=0.0,
        prompt_version=PROMPT_VERSION,
        user_prompt=user_prompt,
    )
    if cached:
        try:
            analysis = LLMAnalysis.model_validate(cached.get("analysis", {}))
            return analysis, True
        except Exception:
            pass

    # Call provider
    input_tok = output_tok = 0
    analysis = LLMAnalysis(findings=[], analysis_notes="")
    success = False
    error_reason: str | None = None

    try:
        result: CompletionResult = provider.complete(system_prompt, user_prompt)
        input_tok, output_tok = result.input_tokens, result.output_tokens
        analysis = _parse_analysis(result.text)
        success = True
    except (json.JSONDecodeError, ValidationError) as e1:
        error_reason = f"PARSE_ERROR:{e1}"
        # Retry once with explicit JSON instruction
        try:
            strict_user = user_prompt + "\n\nIMPORTANT: Respond with ONLY a JSON object. No prose."
            result2 = provider.complete(system_prompt, strict_user)
            input_tok += result2.input_tokens
            output_tok += result2.output_tokens
            analysis = _parse_analysis(result2.text)
            success = True
            error_reason = None
        except Exception as e2:
            analysis = LLMAnalysis(findings=[], analysis_notes=f"PARSE_ERROR:{e2}")
            error_reason = f"PARSE_ERROR_RETRY:{e2}"
    except RateLimitedError as e:
        analysis = LLMAnalysis(findings=[], analysis_notes=f"RATE_LIMITED:{e}")
        error_reason = f"RATE_LIMITED:{e}"
    except ProviderError as e:
        analysis = LLMAnalysis(findings=[], analysis_notes=f"API_ERROR:{e}")
        error_reason = f"API_ERROR:{e}"
    except Exception as e:
        analysis = LLMAnalysis(findings=[], analysis_notes=f"UNEXPECTED_ERROR:{e}")
        error_reason = f"UNEXPECTED_ERROR:{e}"

    cost = _cost_usd(provider.model, input_tok, output_tok)
    entry: dict = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "provider": provider.provider,
        "base_url": provider.base_url,
        "model": provider.model,
        "sample_id": sample_id,
        "input_tokens": input_tok,
        "output_tokens": output_tok,
        "cost_usd": round(cost, 6),
        "cached": False,
        "success": success,
        "n_findings": len(analysis.findings),
    }
    if error_reason:
        entry["error"] = error_reason
    _append_ledger(entry)

    if success:
        cache_put(
            provider=provider.provider,
            base_url=provider.base_url,
            model=provider.model,
            temperature=0.0,
            prompt_version=PROMPT_VERSION,
            user_prompt=user_prompt,
            response={"analysis": analysis.model_dump()},
        )

    return analysis, False
