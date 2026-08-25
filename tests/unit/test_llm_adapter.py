"""
Unit tests for LLM adapter, cache, providers, and rate limiter.
No real network calls — all providers are mocked.
"""
from __future__ import annotations

import json
import os
import time
from unittest.mock import MagicMock, patch

import pytest

from payguard.llm.schema import LLMAnalysis, LLMFinding


# ─── Schema tests ─────────────────────────────────────────────────────────────

class TestLLMSchema:
    def test_valid_finding(self):
        f = LLMFinding(defect_class="DUPLICATE_PAYMENT", confidence=0.9,
                       explanation="No event-id dedup", evidence_lines=[10, 11])
        assert f.defect_class == "DUPLICATE_PAYMENT"

    def test_invalid_defect_class_rejected(self):
        with pytest.raises(Exception):
            LLMFinding(defect_class="UNKNOWN", confidence=0.9, explanation="x")

    def test_confidence_out_of_range_rejected(self):
        with pytest.raises(Exception):
            LLMFinding(defect_class="DUPLICATE_PAYMENT", confidence=1.5, explanation="x")

    def test_empty_analysis(self):
        a = LLMAnalysis()
        assert a.findings == []

    def test_analysis_round_trip(self):
        a = LLMAnalysis(findings=[LLMFinding(defect_class="WEBHOOK_INTEGRITY", confidence=0.85,
                                              explanation="No sig")])
        a2 = LLMAnalysis.model_validate(a.model_dump())
        assert a2.findings[0].defect_class == "WEBHOOK_INTEGRITY"


# ─── Cache tests ──────────────────────────────────────────────────────────────

class TestLLMCache:
    CKWARGS = dict(provider="openai_compat", base_url="http://test/v1",
                   model="test-model", temperature=0.0,
                   prompt_version="v1", user_prompt="hello")

    def test_miss_returns_none(self, tmp_path):
        import payguard.llm.cache as c
        with patch.object(c, "_cache_root", return_value=tmp_path / "cache"):
            assert c.cache_get(**self.CKWARGS) is None

    def test_put_then_get(self, tmp_path):
        import payguard.llm.cache as c
        data = {"analysis": {"findings": [], "analysis_notes": "ok"}}
        with patch.object(c, "_cache_root", return_value=tmp_path / "cache"):
            c.cache_put(**self.CKWARGS, response=data)
            result = c.cache_get(**self.CKWARGS)
        assert result == data

    def test_different_prompts_different_keys(self):
        from payguard.llm.cache import cache_key_hex
        k1 = cache_key_hex(**{**self.CKWARGS, "user_prompt": "A"})
        k2 = cache_key_hex(**{**self.CKWARGS, "user_prompt": "B"})
        assert k1 != k2

    def test_different_providers_different_keys(self):
        from payguard.llm.cache import cache_key_hex
        k1 = cache_key_hex(**{**self.CKWARGS, "provider": "anthropic"})
        k2 = cache_key_hex(**{**self.CKWARGS, "provider": "openai_compat"})
        assert k1 != k2

    def test_different_prompt_versions_different_keys(self):
        from payguard.llm.cache import cache_key_hex
        k1 = cache_key_hex(**{**self.CKWARGS, "prompt_version": "v1"})
        k2 = cache_key_hex(**{**self.CKWARGS, "prompt_version": "v2"})
        assert k1 != k2


# ─── Rate limiter tests ───────────────────────────────────────────────────────

class TestRateLimiter:
    def test_under_limit_does_not_block(self):
        from payguard.llm.rate_limiter import RateLimiter
        rl = RateLimiter(rpm=100, tpm=100000)
        start = time.monotonic()
        for _ in range(5):
            rl.acquire(estimated_tokens=100)
        assert time.monotonic() - start < 1.0

    def test_noop_never_blocks(self):
        from payguard.llm.rate_limiter import NoopRateLimiter
        rl = NoopRateLimiter()
        start = time.monotonic()
        for _ in range(100):
            rl.acquire(1000000)
        assert time.monotonic() - start < 0.1


# ─── Provider tests (mocked) ──────────────────────────────────────────────────

def _openai_response(text: str, in_tok: int = 100, out_tok: int = 50):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = text
    resp.usage = MagicMock(prompt_tokens=in_tok, completion_tokens=out_tok)
    return resp


class TestOpenAICompatProvider:
    def _make_provider(self, mock_client):
        from payguard.llm.providers import OpenAICompatProvider, _DEFAULT_MAX_RETRIES
        from payguard.llm.rate_limiter import NoopRateLimiter
        p = OpenAICompatProvider.__new__(OpenAICompatProvider)
        p.provider = "openai_compat"
        p.base_url = "http://test/v1"
        p.model = "test-model"
        p._max_tokens = 8192
        p._max_retries = _DEFAULT_MAX_RETRIES
        p._client = mock_client
        p._rate_limiter = NoopRateLimiter()
        p._supports_json_mode = None
        return p

    def test_successful_completion(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _openai_response('{"x":1}')
        p = self._make_provider(mock_client)
        result = p.complete("sys", "user")
        assert result.text == '{"x":1}'
        assert result.input_tokens == 100

    def test_json_mode_fallback_on_bad_request(self):
        import openai as _openai
        mock_client = MagicMock()
        bad_req = _openai.BadRequestError(
            message="json_object not supported",
            response=MagicMock(status_code=400, headers={}),
            body=None,
        )
        # First call (with json mode) raises, second call (without) succeeds
        mock_client.chat.completions.create.side_effect = [
            bad_req,
            _openai_response("fallback"),
        ]
        p = self._make_provider(mock_client)
        result = p.complete("sys", "user")
        assert result.text == "fallback"
        assert p._supports_json_mode is False

    def test_rate_limit_retry_then_success(self):
        import openai as _openai
        mock_client = MagicMock()
        rate_exc = _openai.RateLimitError(
            message="429",
            response=MagicMock(status_code=429, headers={"retry-after": "0.01"}),
            body=None,
        )
        mock_client.chat.completions.create.side_effect = [
            rate_exc, _openai_response("ok after retry")
        ]
        p = self._make_provider(mock_client)
        result = p.complete("sys", "user")
        assert result.text == "ok after retry"

    def test_rate_limit_exhaustion_raises(self):
        import openai as _openai
        from payguard.llm.providers import RateLimitedError
        mock_client = MagicMock()
        rate_exc = _openai.RateLimitError(
            message="429",
            response=MagicMock(status_code=429, headers={"retry-after": "0.01"}),
            body=None,
        )
        mock_client.chat.completions.create.side_effect = [rate_exc] * 10
        p = self._make_provider(mock_client)
        with pytest.raises(RateLimitedError):
            p.complete("sys", "user")


# ─── Adapter tests (mocked provider) ─────────────────────────────────────────

class _FakeProvider:
    provider = "openai_compat"
    base_url = "http://fake/v1"
    model = "fake-model"

    def __init__(self, text: str):
        self._text = text

    def complete(self, system: str, user: str):
        from payguard.llm.providers import CompletionResult
        return CompletionResult(text=self._text, input_tokens=10, output_tokens=5,
                                provider="openai_compat", model="fake-model",
                                base_url="http://fake/v1")


class TestAdapter:
    def setup_method(self):
        import payguard.llm.cache as cache_mod
        import payguard.llm.adapter as adapter_mod
        import tempfile
        from pathlib import Path
        self._tmp = tempfile.mkdtemp()
        self._cache_patch = patch.object(cache_mod, "_cache_root",
                                          return_value=Path(self._tmp) / "cache")
        self._cache_patch.start()
        adapter_mod.LEDGER_PATH = Path(self._tmp) / "ledger.jsonl"

    def teardown_method(self):
        self._cache_patch.stop()

    def test_valid_json_parsed(self):
        from payguard.llm.adapter import analyze
        text = json.dumps({"findings": [{"defect_class": "DUPLICATE_PAYMENT",
                                          "confidence": 0.85, "explanation": "x",
                                          "evidence_lines": [], "scenario_ids": []}],
                            "analysis_notes": ""})
        analysis, hit = analyze("sys", "user", provider=_FakeProvider(text))
        assert not hit
        assert len(analysis.findings) == 1
        assert analysis.findings[0].defect_class == "DUPLICATE_PAYMENT"

    def test_parse_error_returns_empty(self):
        from payguard.llm.adapter import analyze
        analysis, _ = analyze("sys", "user", provider=_FakeProvider("not json"))
        assert analysis.findings == []
        assert "PARSE_ERROR" in analysis.analysis_notes or "ERROR" in analysis.analysis_notes

    def test_none_provider_returns_unavailable(self):
        from payguard.llm.adapter import analyze
        # build_analyzer_provider is imported inside the function body in adapter.py,
        # so patch it at the providers module level.
        with patch("payguard.llm.providers.build_analyzer_provider", return_value=None):
            with patch.dict(os.environ, {"PAYGUARD_LLM_API_KEY": "", "ANTHROPIC_API_KEY": ""}):
                analysis, hit = analyze("sys", "user none provider test", provider=None)
        assert analysis.findings == []
        assert "provider not configured" in analysis.analysis_notes
        assert not hit

    def test_cache_hit_on_second_call(self):
        from payguard.llm.adapter import analyze
        text = json.dumps({"findings": [], "analysis_notes": "cached"})
        call_count = 0

        class CountingProvider(_FakeProvider):
            def complete(self, system, user):
                nonlocal call_count
                call_count += 1
                return super().complete(system, user)

        analyze("sys", "same user prompt", provider=CountingProvider(text))
        _, hit = analyze("sys", "same user prompt", provider=CountingProvider(text))
        assert hit is True
        assert call_count == 1

    def test_rate_limited_returns_rate_limited_note(self):
        from payguard.llm.adapter import analyze
        from payguard.llm.providers import RateLimitedError

        class RateLimitProvider:
            provider = "openai_compat"
            base_url = "http://fake/v1"
            model = "fake"
            def complete(self, s, u):
                raise RateLimitedError("exhausted")

        analysis, _ = analyze("sys", "user rl test", provider=RateLimitProvider())
        assert "RATE_LIMITED" in analysis.analysis_notes

    def test_ledger_written(self):
        import payguard.llm.adapter as adapter_mod
        from pathlib import Path
        from payguard.llm.adapter import analyze
        text = json.dumps({"findings": [], "analysis_notes": ""})
        analyze("sys", "ledger test prompt", provider=_FakeProvider(text), sample_id="s-1")
        entries = [json.loads(l) for l in adapter_mod.LEDGER_PATH.read_text().splitlines()]
        assert entries[-1]["sample_id"] == "s-1"
        assert "cost_usd" in entries[-1]


# ─── System rename check ──────────────────────────────────────────────────────

class TestSystemNaming:
    """Smoke-test that A/B/C map to the correct logic."""

    def test_system_a_uses_static_only(self):
        from payguard.eval.runner import evaluate_system
        # With no samples, result should be empty but llm_status=OK for A
        result = evaluate_system([], "val", system="A")
        assert result.llm_status == "OK"
        assert result.llm_api_calls == 0

    def test_system_b_unavailable_without_key(self):
        from payguard.eval.runner import evaluate_system
        with patch.dict(os.environ, {
            "PAYGUARD_LLM_API_KEY": "", "ANTHROPIC_API_KEY": "",
            "PAYGUARD_FALLBACK_API_KEY": "", "PAYGUARD_OLLAMA_FALLBACK": "",
        }):
            result = evaluate_system([], "val", system="B")
        assert result.llm_status == "UNAVAILABLE"

    def test_system_c_unavailable_without_key(self):
        from payguard.eval.runner import evaluate_system
        with patch.dict(os.environ, {
            "PAYGUARD_LLM_API_KEY": "", "ANTHROPIC_API_KEY": "",
            "PAYGUARD_FALLBACK_API_KEY": "", "PAYGUARD_OLLAMA_FALLBACK": "",
        }):
            result = evaluate_system([], "val", system="C")
        assert result.llm_status == "UNAVAILABLE"
