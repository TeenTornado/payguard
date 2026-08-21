"""
Non-negotiable test (ADR-003): both layers must reject live keys.
Never skip, xfail, or delete this test.
"""
import os

import pytest
from pydantic import ValidationError

from payguard.shared.config import Settings, validate_key_prefix


class TestKeyPrefixConfigLayer:
    """Layer 1: Settings object rejects live keys at construction."""

    def test_live_key_rejected(self) -> None:
        with pytest.raises(ValidationError, match="rzp_test_"):
            Settings(
                payguard_env="TEST",
                razorpay_test_key_id="rzp_live_ABCDEF",
                database_url="postgresql+asyncpg://x:x@localhost/x",
            )

    def test_test_key_accepted(self) -> None:
        s = Settings(
            payguard_env="TEST",
            razorpay_test_key_id="rzp_test_ABCDEF",
            database_url="postgresql+asyncpg://x:x@localhost/x",
        )
        assert s.razorpay_test_key_id == "rzp_test_ABCDEF"

    def test_empty_key_accepted(self) -> None:
        # Empty key = no credentials configured; that's allowed (EMULATE mode)
        s = Settings(
            payguard_env="TEST",
            razorpay_test_key_id="",
            database_url="postgresql+asyncpg://x:x@localhost/x",
        )
        assert s.razorpay_test_key_id == ""

    def test_non_test_env_rejected(self) -> None:
        with pytest.raises(ValidationError, match="TEST"):
            Settings(
                payguard_env="PRODUCTION",
                database_url="postgresql+asyncpg://x:x@localhost/x",
            )

    def test_live_env_rejected(self) -> None:
        with pytest.raises(ValidationError, match="TEST"):
            Settings(
                payguard_env="LIVE",
                database_url="postgresql+asyncpg://x:x@localhost/x",
            )


class TestKeyPrefixGatewayLayer:
    """Layer 2: validate_key_prefix() called at the gateway level."""

    def test_live_key_rejected(self) -> None:
        with pytest.raises(ValueError, match="rzp_test_"):
            validate_key_prefix("rzp_live_ABCDEF123")

    def test_test_key_accepted(self) -> None:
        validate_key_prefix("rzp_test_ABCDEF123")  # must not raise

    def test_empty_key_accepted(self) -> None:
        validate_key_prefix("")  # no key configured = EMULATE mode

    def test_partial_prefix_rejected(self) -> None:
        with pytest.raises(ValueError, match="rzp_test_"):
            validate_key_prefix("rzp_test")  # missing trailing underscore

    def test_key_with_wrong_prefix_rejected(self) -> None:
        with pytest.raises(ValueError, match="rzp_test_"):
            validate_key_prefix("sk_live_ABCDEF")
