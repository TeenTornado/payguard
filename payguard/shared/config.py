import re
from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_TEST_KEY_RE = re.compile(r"^rzp_test_")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    payguard_env: str = "TEST"
    database_url: str = "postgresql+asyncpg://payguard:payguard@localhost:5432/payguard"

    # Razorpay — test credentials only
    razorpay_test_key_id: str = ""
    razorpay_test_key_secret: str = ""
    razorpay_test_webhook_secret: str = ""

    # Gateway
    gateway_mode: str = "EMULATE"
    gateway_url: str = "http://localhost:8001"
    gateway_port: int = 8001

    # LLM
    payguard_llm_provider: str = "anthropic"
    anthropic_api_key: str = ""
    payguard_llm_model: str = "claude-haiku-4-5-20251001"
    payguard_llm_cache_dir: str = "dataset/llm_cache"

    # Feature flags
    payguard_demo: bool = False
    sandbox_runtime: str = "docker"
    console_bind: str = "127.0.0.1"
    api_port: int = 8000

    # Thresholds (overridden by config/thresholds.yml at runtime)
    advisory_threshold: float = 0.3
    verify_threshold: float = 0.6

    @field_validator("razorpay_test_key_id")
    @classmethod
    def key_id_must_be_test(cls, v: str) -> str:
        if v and not _TEST_KEY_RE.match(v):
            raise ValueError(
                f"RAZORPAY_TEST_KEY_ID must start with 'rzp_test_', got: {v[:12]}..."
            )
        return v

    @model_validator(mode="after")
    def env_must_be_test(self) -> "Settings":
        if self.payguard_env.upper() != "TEST":
            raise ValueError(
                "PAYGUARD_ENV must be TEST. PayGuard has no live-mode code path."
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    return s


def validate_key_prefix(key_id: str) -> None:
    """Raise ValueError if key_id is not a test key. Called at the gateway level too."""
    if key_id and not _TEST_KEY_RE.match(key_id):
        raise ValueError(
            f"Credential rejected: key_id must start with 'rzp_test_'. Got prefix: {key_id[:8]}..."
        )
