"""Application configuration. All env vars flow through here.

`Settings()` is constructed once at boot in `container.py` and injected into
adapters and use cases. Tests build their own Settings instances with overrides.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Top-level settings, loaded from environment / `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Required ----------------------------------------------------------

    claude_api_key: SecretStr = Field(default=SecretStr(""))

    # --- Optional ----------------------------------------------------------

    fred_api_key: SecretStr | None = None
    newsapi_key: SecretStr | None = None

    # --- Postgres ----------------------------------------------------------

    postgres_user: str = "dtb"
    postgres_password: SecretStr = SecretStr("dtb_dev_password")
    postgres_db: str = "day_trading_buddy"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    # --- Redis -------------------------------------------------------------

    redis_host: str = "localhost"
    redis_port: int = 6379

    # --- Application tuning -----------------------------------------------

    tick_interval_seconds: int = 300
    # How often the dashboard redraws itself with the same data so `docker
    # attach` (which only streams future output) sees a live screen instead
    # of waiting up to a full tick interval for the next render.
    display_refresh_seconds: int = 10
    output_language: Literal["pt", "en"] = "pt"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    bias_weight_technical: float = 0.40
    bias_weight_macro: float = 0.30
    bias_weight_sentiment: float = 0.30

    bias_threshold_bullish: float = 60.0
    bias_threshold_bearish: float = 40.0

    anthropic_model_briefing: str = "claude-opus-4-7"
    anthropic_model_classifier: str = "claude-haiku-4-5-20251001"

    # --- Day-trade signal tuning ------------------------------------------

    # Account size in USD used by `dtb signal` to compute position sizing.
    # 0 = skip position sizing in the output (only stop levels are shown).
    account_size_usd: float = 0.0
    # Risk per trade as percentage of account_size_usd (default 2%).
    risk_per_trade_pct: float = 2.0
    # Buffer added to the swing-based stop, in ATR multiples (0.5 = half an ATR).
    stop_buffer_atr_multiple: float = 0.5
    # Opening-range window in minutes for the OR levels.
    opening_range_minutes: int = 30

    # --- Breakout detector tuning -----------------------------------------

    # If True, the detector only emits signals when ATR(14) was below its
    # 20-bar SMA on the bar *before* the break — i.e. volatility was
    # contracting. Catches "coil + explosion" setups beautifully BUT misses
    # violent reversals that happen in already-volatile sessions (e.g. a
    # 2-day move ending in a reversal). Default False so breakouts also fire
    # on aggressive reversals; the `squeeze=true` flag is still set on the
    # event itself when conditions hold, so the frontend keeps the quality
    # badge for setups that did come out of a true squeeze.
    breakout_require_squeeze: bool = False
    # Minimum range expansion vs ATR(14) for a signal. Lower = more signals
    # (some marginal), higher = stricter. Default 1.3 matches the original
    # "true expansion" rule of thumb.
    breakout_expansion_atr_multiple: float = 1.3
    # Donchian window length on each timeframe.
    breakout_donchian_n: int = 20

    # --- Derived -----------------------------------------------------------

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:"
            f"{self.postgres_password.get_secret_value()}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def postgres_dsn_sync(self) -> str:
        """Sync DSN for Alembic (which does not support asyncpg)."""
        return (
            f"postgresql+psycopg://{self.postgres_user}:"
            f"{self.postgres_password.get_secret_value()}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    # --- Validation --------------------------------------------------------

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> Settings:
        total = self.bias_weight_technical + self.bias_weight_macro + self.bias_weight_sentiment
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"Bias weights must sum to 1.0, got {total:.4f}. "
                "Check BIAS_WEIGHT_TECHNICAL / _MACRO / _SENTIMENT in .env."
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor. Tests should construct `Settings()` directly."""
    return Settings()


__all__ = ["Settings", "get_settings"]
