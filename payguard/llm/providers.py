"""
LLM provider implementations.

ADR-002: No LLM for deterministic checks.
ADR-003: LLM never receives tools.

Providers:
  openai_compat — OpenAI-compatible REST API (Gemini, Groq, OpenRouter, Ollama, etc.)
  anthropic     — Anthropic Messages API (legacy, kept for compatibility)

Provider hierarchy (analyzer):
  1. Gemini direct (primary)    — PAYGUARD_LLM_* vars, AIza key, rpm=8
  2. Groq direct (fallback)     — PAYGUARD_GEN_* vars for generation
  3. OpenRouter (last-resort)   — 50 RPD unfunded; max_retries=1 only
"""
from __future__ import annotations

import logging
import os
import random
import time
from dataclasses import dataclass

import anthropic
import openai

from payguard.llm.rate_limiter import NoopRateLimiter, RateLimiter

logger = logging.getLogger(__name__)


@dataclass
class CompletionResult:
    text: str
    input_tokens: int
    output_tokens: int
    provider: str
    model: str
    base_url: str
    finish_reason: str = ""
    reasoning_tokens: int | None = None


class ProviderError(Exception):
    """Non-retriable provider error."""


class RateLimitedError(Exception):
    """All retry attempts exhausted due to rate limiting. Ledger code: RATE_LIMITED."""


_DEFAULT_MAX_RETRIES = 5
# OpenRouter: only 1 retry — 429s count against the 50 RPD quota
OPENROUTER_MAX_RETRIES = 1


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "on", "yes"}


def _parse_retry_after(exc: Exception) -> float | None:
    """Extract Retry-After seconds from a 429 response, or None."""
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if headers and "retry-after" in headers:
        try:
            return float(headers["retry-after"])
        except (ValueError, TypeError):
            pass
    return None


class OpenAICompatProvider:
    """OpenAI-compatible REST API provider (Gemini, Groq, OpenRouter, Ollama)."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        rpm: int = 9999,
        tpm: int = 9_999_999,
        max_tokens: int = 8192,
        max_retries: int = _DEFAULT_MAX_RETRIES,
    ) -> None:
        self.provider = "openai_compat"
        self.base_url = base_url
        self.model = model
        self._max_tokens = max_tokens
        self._max_retries = max_retries
        self._client = openai.OpenAI(
            base_url=base_url,
            api_key=api_key,
            max_retries=0,  # we handle retries ourselves
        )
        self._rate_limiter: RateLimiter | NoopRateLimiter = (
            RateLimiter(rpm, tpm) if (rpm < 9999 or tpm < 9_999_999) else NoopRateLimiter()
        )
        # None = unknown, True = confirmed works, False = confirmed unsupported
        self._supports_json_mode: bool | None = None

    def complete(self, system: str, user: str) -> CompletionResult:
        self._rate_limiter.acquire()

        for attempt in range(self._max_retries):
            try:
                result = self._complete_once(system, user)
                self._rate_limiter.record_actual_tokens(
                    result.input_tokens + result.output_tokens
                )
                logger.debug(
                    "completion model=%s finish_reason=%s in=%d out=%d reasoning=%s",
                    result.model, result.finish_reason,
                    result.input_tokens, result.output_tokens, result.reasoning_tokens,
                )
                return result
            except openai.RateLimitError as exc:
                if attempt == self._max_retries - 1:
                    raise RateLimitedError(
                        f"RATE_LIMITED after {self._max_retries} attempts"
                    ) from exc
                retry_after = _parse_retry_after(exc) or (2 ** attempt + random.uniform(0, 1))
                time.sleep(retry_after)
            except (openai.NotFoundError, openai.AuthenticationError) as exc:
                # Non-retriable: wrong model name or bad key — surface immediately
                raise ProviderError(f"{type(exc).__name__}: {exc}") from exc

        raise RateLimitedError("RATE_LIMITED: exhausted retries")  # unreachable but mypy needs it

    def _complete_once(self, system: str, user: str) -> CompletionResult:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": self._max_tokens,
        }
        if self._supports_json_mode is not False:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = self._client.chat.completions.create(**kwargs)
            if self._supports_json_mode is None:
                self._supports_json_mode = True
        except openai.BadRequestError as exc:
            err_str = str(exc).lower()
            if self._supports_json_mode is not False and (
                "json" in err_str or "response_format" in err_str or "json_object" in err_str
            ):
                # Provider doesn't support response_format=json_object; retry without
                self._supports_json_mode = False
                kwargs.pop("response_format", None)
                response = self._client.chat.completions.create(**kwargs)
            else:
                raise ProviderError(str(exc)) from exc

        choice = response.choices[0]
        usage = response.usage
        reasoning_tokens: int | None = None
        if usage:
            details = getattr(usage, "completion_tokens_details", None)
            if details:
                reasoning_tokens = getattr(details, "reasoning_tokens", None)

        text = choice.message.content or ""
        if not text:
            finish = getattr(choice, "finish_reason", "") or ""
            logger.warning(
                "empty content from model=%s finish_reason=%s reasoning_tokens=%s",
                self.model, finish, reasoning_tokens,
            )

        return CompletionResult(
            text=text,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            provider="openai_compat",
            model=self.model,
            base_url=self.base_url,
            finish_reason=getattr(choice, "finish_reason", "") or "",
            reasoning_tokens=reasoning_tokens,
        )


class AnthropicProvider:
    """Anthropic Messages API provider (legacy path)."""

    def __init__(self, api_key: str, model: str) -> None:
        self.provider = "anthropic"
        self.base_url = "https://api.anthropic.com"
        self.model = model
        self._client = anthropic.Anthropic(api_key=api_key)
        self._rate_limiter: NoopRateLimiter = NoopRateLimiter()

    def complete(self, system: str, user: str) -> CompletionResult:
        for attempt in range(_DEFAULT_MAX_RETRIES):
            try:
                msg = self._client.messages.create(
                    model=self.model,
                    max_tokens=1024,
                    temperature=0,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                text = msg.content[0].text if msg.content else ""
                return CompletionResult(
                    text=text,
                    input_tokens=msg.usage.input_tokens,
                    output_tokens=msg.usage.output_tokens,
                    provider="anthropic",
                    model=self.model,
                    base_url="https://api.anthropic.com",
                )
            except anthropic.RateLimitError as exc:
                if attempt == _DEFAULT_MAX_RETRIES - 1:
                    raise RateLimitedError("RATE_LIMITED after {_DEFAULT_MAX_RETRIES} attempts") from exc
                retry_after = _parse_retry_after(exc) or (2 ** attempt + random.uniform(0, 1))
                time.sleep(retry_after)
        raise RateLimitedError("RATE_LIMITED: exhausted retries")


def load_provider(
    *,
    profile: str | None = None,
    provider_type: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    rpm: int | None = None,
    tpm: int | None = None,
    max_tokens: int | None = None,
    max_retries: int | None = None,
) -> OpenAICompatProvider | AnthropicProvider | None:
    """
    Build a provider from explicit args or from a named profile in config/llm_limits.yml.
    Returns None if the provider is not configured (missing key).
    """
    from pathlib import Path

    import yaml

    cfg: dict = {}
    if profile:
        limits_file = Path(__file__).parent.parent.parent / "config" / "llm_limits.yml"
        if limits_file.exists():
            data = yaml.safe_load(limits_file.read_text())
            cfg = (data.get("profiles") or {}).get(profile, {})

    effective_provider = provider_type or "openai_compat"
    effective_base_url = base_url or cfg.get("base_url", "")
    effective_api_key = api_key or cfg.get("api_key", "")
    effective_model = model or cfg.get("model", "")
    effective_rpm = rpm if rpm is not None else cfg.get("rpm", 9999)
    effective_tpm = tpm if tpm is not None else cfg.get("tpm", 9_999_999)
    effective_max_tokens = max_tokens if max_tokens is not None else cfg.get("max_tokens", 8192)
    effective_max_retries = (
        max_retries if max_retries is not None else cfg.get("max_retries", _DEFAULT_MAX_RETRIES)
    )

    if not effective_api_key:
        return None

    if effective_provider == "anthropic":
        return AnthropicProvider(api_key=effective_api_key, model=effective_model)

    return OpenAICompatProvider(
        base_url=effective_base_url,
        api_key=effective_api_key,
        model=effective_model,
        rpm=effective_rpm,
        tpm=effective_tpm,
        max_tokens=effective_max_tokens,
        max_retries=effective_max_retries,
    )


def build_analyzer_provider() -> OpenAICompatProvider | AnthropicProvider | None:
    """
    Build analyzer provider: Gemini direct → OpenRouter fallback.

    Primary: PAYGUARD_LLM_* (Gemini direct, AIza... key, 8 rpm free tier)
    Fallback: PAYGUARD_FALLBACK_* (OpenRouter, last-resort, max_retries=1)
    """
    ptype = os.environ.get("PAYGUARD_LLM_PROVIDER", "openai_compat")
    burl = os.environ.get("PAYGUARD_LLM_BASE_URL", "")
    key = os.environ.get("PAYGUARD_LLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
    mdl = os.environ.get("PAYGUARD_LLM_MODEL", "")
    rpm = int(os.environ.get("PAYGUARD_LLM_RPM", "9999"))
    tpm = int(os.environ.get("PAYGUARD_LLM_TPM", "9999999"))
    max_tokens = int(os.environ.get("PAYGUARD_LLM_MAX_TOKENS", "8192"))
    primary = load_provider(
        provider_type=ptype, base_url=burl, api_key=key, model=mdl,
        rpm=rpm, tpm=tpm, max_tokens=max_tokens,
    )
    if primary is not None:
        return primary

    # Last-resort: OpenRouter (50 RPD unfunded; max_retries=1 to not burn quota)
    fb_key = os.environ.get("PAYGUARD_FALLBACK_API_KEY", "")
    fb_burl = os.environ.get("PAYGUARD_FALLBACK_BASE_URL", "https://openrouter.ai/api/v1")
    fb_mdl = os.environ.get("PAYGUARD_FALLBACK_MODEL", "google/gemini-2.5-flash")
    fb_rpm = int(os.environ.get("PAYGUARD_FALLBACK_RPM", "20"))
    fb_tpm = int(os.environ.get("PAYGUARD_FALLBACK_TPM", "20000"))
    if fb_key:
        logger.warning("Primary analyzer key not set — falling back to OpenRouter (50 RPD limit)")
        return load_provider(
            base_url=fb_burl, api_key=fb_key, model=fb_mdl,
            rpm=fb_rpm, tpm=fb_tpm, max_tokens=8192,
            max_retries=OPENROUTER_MAX_RETRIES,
        )

    # Opt-in local fallback: Ollama. Keeps the console analyzer AVAILABLE offline (no key)
    # so it never shows "unavailable" just because a hosted key is absent. Gated by
    # PAYGUARD_OLLAMA_FALLBACK so it does NOT change eval semantics — the eval systems must
    # still report UNAVAILABLE without a hosted key (reproducibility). The worker/demo set
    # the flag; eval and tests do not. If Ollama isn't running the scan degrades to
    # static-only — never a silent gap.
    if _flag("PAYGUARD_OLLAMA_FALLBACK"):
        ollama = load_provider(profile="ollama", max_retries=1)
        if ollama is not None:
            logger.info("Analyzer falling through to local Ollama (%s)", ollama.model)
            return ollama
    return None


def build_generator_provider() -> OpenAICompatProvider | AnthropicProvider | None:
    """
    Build generator provider: Groq direct → OpenRouter fallback.

    Primary: PAYGUARD_GEN_* (Groq direct, GROQ_API_KEY)
    Fallback: PAYGUARD_FALLBACK_* (OpenRouter, last-resort)
    """
    ptype = os.environ.get("PAYGUARD_GEN_PROVIDER", "openai_compat")
    burl = os.environ.get("PAYGUARD_GEN_BASE_URL", "")
    key = os.environ.get("PAYGUARD_GEN_API_KEY") or os.environ.get("GROQ_API_KEY", "")
    mdl = os.environ.get("PAYGUARD_GEN_MODEL", "")
    rpm = int(os.environ.get("PAYGUARD_GEN_RPM", "9999"))
    tpm = int(os.environ.get("PAYGUARD_GEN_TPM", "9999999"))
    primary = load_provider(
        provider_type=ptype, base_url=burl, api_key=key, model=mdl, rpm=rpm, tpm=tpm,
    )
    if primary is not None:
        return primary

    # Last-resort: OpenRouter
    fb_key = os.environ.get("PAYGUARD_FALLBACK_API_KEY", "")
    fb_burl = os.environ.get("PAYGUARD_FALLBACK_BASE_URL", "https://openrouter.ai/api/v1")
    fb_mdl = os.environ.get("PAYGUARD_FALLBACK_MODEL", "meta-llama/llama-3.3-70b-instruct")
    fb_rpm = int(os.environ.get("PAYGUARD_FALLBACK_RPM", "20"))
    fb_tpm = int(os.environ.get("PAYGUARD_FALLBACK_TPM", "20000"))
    if fb_key:
        logger.warning("Generator key not set — falling back to OpenRouter")
        return load_provider(
            base_url=fb_burl, api_key=fb_key, model=fb_mdl,
            rpm=fb_rpm, tpm=fb_tpm,
            max_retries=OPENROUTER_MAX_RETRIES,
        )
    return None
