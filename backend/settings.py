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

    # --- CORS / public deployments -----------------------------------------

    # Comma-separated list of extra origins that the API should accept (in
    # addition to the built-in localhost + RFC1918 LAN regex). Set this when
    # serving the frontend from a public IP / hostname so the browser does
    # not refuse the cross-origin /api and /ws calls. Example for the shared
    # KVM:  CORS_EXTRA_ORIGINS=http://72.62.15.111:3057
    cors_extra_origins: str = ""

    # --- ntfy.sh push notifications --------------------------------------

    # Secret topic name the backend will POST breakout alerts to. Leave
    # empty to disable push notifications entirely. Anyone who knows this
    # topic can subscribe to your messages, so treat it like a password
    # (long random string).
    ntfy_topic: SecretStr | None = None
    # Override only if self-hosting an ntfy server.
    ntfy_server: str = "https://ntfy.sh"

    # --- Order flow (live MT5 DOM / footprint / tape) ----------------------

    # Master switch. When False the ingest WebSocket rejects connections and
    # the frontend simply shows the panel empty. Turn on once the Windows
    # collector is configured.
    orderflow_enabled: bool = False
    # Shared secret the collector must present to push data to the ingest
    # socket. Treat like a password (long random string). If empty while
    # orderflow_enabled is True, the ingest socket refuses every connection.
    orderflow_ingest_token: SecretStr | None = None
    # Symbols that carry order flow. Subset of AssetSymbol — the six FTMO
    # instruments the trader works. Each one also needs a matching entry in the
    # Windows collector's config.json (backend name → MT5 name).
    orderflow_symbols: str = "USTEC,SPX,GOLD,US30,GER40,EURUSD"
    # Footprint bar width in seconds (60 = 1-minute footprint bars).
    orderflow_footprint_interval_seconds: int = 60
    # How many footprint bars to retain / broadcast per symbol.
    orderflow_footprint_bars: int = 30
    # How many recent trades to keep on the tape per symbol.
    orderflow_tape_maxlen: int = 200
    # Default whole-account auto-close target in USD. When > 0, the account
    # auto-close arms itself at this target as soon as the collector connects
    # with close capability, and re-arms after each fire (so it stays on across
    # UI refreshes / backend restarts). 0 disables auto-arming. A manual disarm
    # in the UI turns auto-arming off until you arm again. Sized for the
    # ActivTrades account (about $1k), traded with 0.01 lots.
    orderflow_autoclose_default_usd: float = 35.0
    # Directory for the raw ingest tape: every book/trades/liquidity message is
    # appended verbatim to one JSONL file per UTC day, so real sessions can be
    # replayed through the aggregator to backtest the scalper. Relative paths
    # resolve against the backend working dir (in Docker: /app, bind-mounted to
    # the repo's ./data/orderflow_tape). Empty string disables recording.
    orderflow_record_dir: str = "data/orderflow_tape"
    # Directory for the account balance/equity time-series (one JSONL per UTC
    # day) that feeds the UI balance chart. Same working-dir semantics as
    # `orderflow_record_dir`. Empty string keeps the series in memory only
    # (chart resets on backend restart).
    account_balance_dir: str = "data/account_balance"
    # Directory for the closed-trade history (one JSON file) that feeds the
    # Performance tab. The collector re-pushes a rolling window of trades; the
    # store keeps everything it has ever seen, so this file is the long-term
    # record. Same working-dir semantics as the two dirs above; empty string
    # keeps the history in memory only (lost on backend restart).
    trade_history_dir: str = "data/trade_history"

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

    @property
    def orderflow_symbol_list(self) -> list[str]:
        """Parsed, upper-cased order-flow symbols (validated against AssetSymbol
        at the call site to avoid importing enums into settings)."""
        return [s.strip().upper() for s in self.orderflow_symbols.split(",") if s.strip()]

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
