"""Application settings and configuration"""

import os
from typing import Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class DatabaseSettings(BaseModel):
    """Database configuration"""
    path: str = Field(default="./data/trading_fund.db", description="Database file path")


class LoggingSettings(BaseModel):
    """Logging configuration"""
    level: str = Field(default="INFO", description="Log level (DEBUG, INFO, WARNING, ERROR)")
    file: Optional[str] = Field(default="./logs/trading_fund.log", description="Log file path")


class CopyTradingSettings(BaseModel):
    """Copy trading strategy settings"""
    max_position_size: float = Field(default=1000.0, description="Maximum position size per trade")
    max_traders: int = Field(default=10, description="Maximum number of traders to copy")
    use_kalshi: bool = Field(default=False, description="Enable Kalshi WebSocket")
    # Trader discovery: low volume + high PnL (edge)
    trader_max_volume: Optional[float] = Field(default=None, description="Max leaderboard volume to consider (None = no cap)")
    trader_min_pnl: Optional[float] = Field(default=None, description="Min PnL to consider (None = no floor)")
    trader_min_pnl_per_vol: Optional[float] = Field(default=None, description="Min PnL/vol ratio (None = no floor)")
    trader_discovery_time_period: str = Field(default="WEEK", description="Leaderboard period: DAY, WEEK, MONTH, ALL")


class MarketMakingSettings(BaseModel):
    """Market making strategy settings"""
    max_spread: float = Field(default=2.00, description="Maximum spread to market make on")
    min_volume: float = Field(default=100.0, description="Minimum daily volume")
    max_position: float = Field(default=5000.0, description="Maximum position size")
    # Market discovery: high spread + decent liquidity
    discovery_min_liquidity: float = Field(default=0.0, description="Min liquidity (Polymarket) for discovery")
    discovery_min_spread_pct: float = Field(default=0.005, description="Min spread as fraction (e.g. 0.01 = 1%)")
    discovery_min_volume_24h_kalshi: float = Field(default=0.0, description="Min 24h volume (Kalshi) for discovery")
    discovery_max_markets: int = Field(default=50, description="Max markets to discover per platform")
    quote_spread: float = Field(default=0.02, description="Fixed quote spread fallback around fair value")


class MarketMakingAsSettings(BaseModel):
    """Avellaneda-Stoikov market making strategy settings."""
    max_spread: float = Field(default=2.0, description="Maximum spread to market make on")
    min_volume: float = Field(default=100.0, description="Minimum daily volume")
    max_position: float = Field(default=50.0, description="Maximum signed inventory per market")
    quote_spread: float = Field(default=0.02, description="Fallback quote spread if A-S output invalid")
    discovery_min_liquidity: float = Field(default=0.0, description="Min liquidity (Polymarket) for discovery")
    discovery_min_spread_pct: float = Field(default=0.005, description="Min spread as fraction for discovery")
    discovery_min_volume_24h_kalshi: float = Field(default=0.0, description="Min 24h volume (Kalshi) for discovery")
    discovery_max_markets: int = Field(default=50, description="Max markets to discover per platform")
    quote_update_interval_seconds: float = Field(default=5.0, description="Minimum seconds between repricing")
    quote_reprice_threshold: float = Field(default=0.02, description="Minimum fair-value move to trigger repricing")
    base_size_fraction: float = Field(default=0.1, description="Base order size as fraction of max_position")
    regime_size_beta: float = Field(default=0.7, description="How aggressively stress shrinks sizes")
    inventory_size_eta: float = Field(default=0.8, description="How aggressively inventory pressure shrinks size")
    min_size_fraction: float = Field(default=0.2, description="Minimum quote size multiplier floor")
    cauchy_x0: float = Field(default=0.0, description="Cauchy location for band fair value model")
    cauchy_gamma_base: float = Field(default=0.000005, description="Base Cauchy scale for return distribution")
    gamma_base: float = Field(default=0.05, description="Baseline A-S risk aversion")
    gamma_alpha: float = Field(default=0.5, description="A-S stress scaling weight used to cap adaptive gamma")
    kappa: float = Field(default=1.5, description="A-S liquidity parameter")
    session_horizon_seconds: float = Field(default=3600.0, description="A-S horizon used for reservation/spread")
    regime_buckets: int = Field(default=10, description="Number of bins for reversal-based regime scoring")
    inventory_hard_gate_fraction: float = Field(
        default=0.9,
        description="Stop bidding when long inventory >= this fraction of max_position; stop offering when short",
    )
    inventory_size_taper_exponent: float = Field(
        default=2.0,
        description="Power on normalized inventory pressure for size taper (higher = smaller size near limits)",
    )
    inventory_min_size_fraction: float = Field(
        default=0.0,
        description="Floor on inventory-driven size multiplier (0 allows full taper toward zero before hard gate)",
    )
    inventory_quote_skew_coeff: float = Field(
        default=0.03,
        description="Extra reservation shift (prob points) per unit normalized inventory for faster unwind",
    )
    band_quote_skew_coeff: float = Field(
        default=0.015,
        description="Additional skew scaled by band z-score and normalized inventory",
    )
    session_flatten_seconds: float = Field(
        default=1800.0,
        description="Within this many seconds of eod_timestamp, quote only to flatten inventory",
    )


class AltDataSettings(BaseModel):
    """Alt data strategy settings"""
    confidence_threshold: float = Field(default=0.7, description="Minimum confidence to trade")
    twitter_api_key: Optional[str] = Field(default=None, description="Twitter API key")
    twitter_api_secret: Optional[str] = Field(default=None, description="Twitter API secret")
    twitter_bearer_token: Optional[str] = Field(default=None, description="Twitter bearer token")


class SimulatorSettings(BaseModel):
    """Simulator settings"""
    slippage: float = Field(default=0.001, description="Simulated slippage (0.1%)")
    latency_ms: int = Field(default=50, description="Simulated latency in milliseconds")
    use_polymarket: bool = Field(default=True, description="Enable Polymarket WebSocket")
    use_kalshi: bool = Field(default=True, description="Enable Kalshi WebSocket")
    historical_rth_only: bool = Field(default=False, description="Limit historical replay to regular session hours")
    trading_timezone: str = Field(default="America/New_York", description="Timezone used for session-hour filters")
    regular_session_start: str = Field(default="09:30", description="Regular session start HH:MM in trading_timezone")
    regular_session_end: str = Field(default="16:00", description="Regular session end HH:MM in trading_timezone")
    enforce_signed_inventory_cap: bool = Field(
        default=True,
        description="If true, simulators clamp fills so signed inventory stays within max_signed_inventory",
    )
    initial_balance: float = Field(default=100.0, description="Starting cash for paper/historical simulators")
    max_signed_inventory: float = Field(
        default=50.0,
        description="Absolute cap on |signed contracts| per market in simulation (backstop vs strategy)",
    )
    use_schwab_spx: bool = Field(
        default=False,
        description="Enable live Schwab SPX spot feed in paper trading",
    )
    schwab_symbol: str = Field(
        default="$SPX",
        description="Schwab symbol for underlying spot feed",
    )
    bounds_file: str = Field(
        default="data/kalshi_market_bounds.json",
        description="JSON file with lower/upper/eod bounds for paper trading markets",
    )
    spx_stale_seconds: float = Field(
        default=120.0,
        description="Warn if no SPX update received within this many seconds",
    )
    spx_poll_interval_seconds: float = Field(
        default=5.0,
        description="REST poll interval when Schwab stream is unavailable",
    )


class Settings(BaseModel):
    """Application settings"""
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    copy_trading: CopyTradingSettings = Field(default_factory=CopyTradingSettings)
    market_making: MarketMakingSettings = Field(default_factory=MarketMakingSettings)
    market_making_as: MarketMakingAsSettings = Field(default_factory=MarketMakingAsSettings)
    alt_data: AltDataSettings = Field(default_factory=AltDataSettings)
    simulator: SimulatorSettings = Field(default_factory=SimulatorSettings)

    @classmethod
    def from_env(cls) -> "Settings":
        """Create settings from environment variables"""
        mm_as_max = float(os.getenv("MARKET_MAKING_AS_MAX_POSITION", os.getenv("MARKET_MAKING_MAX_POSITION", "50")))
        return cls(
            database=DatabaseSettings(
                path=os.getenv("DATABASE_PATH", "./data/trading_fund.db")
            ),
            logging=LoggingSettings(
                level=os.getenv("LOG_LEVEL", "INFO"),
                file=os.getenv("LOG_FILE", "./logs/trading_fund.log")
            ),
            copy_trading=CopyTradingSettings(
                max_position_size=float(os.getenv("COPY_TRADING_MAX_POSITION_SIZE", "1000")),
                max_traders=int(os.getenv("COPY_TRADING_MAX_TRADERS", "10")),
                use_kalshi=os.getenv("COPY_TRADING_USE_KALSHI", "False").lower() in ("true", "1", "t", "yes"),
                trader_max_volume=float(os.getenv("COPY_TRADING_TRADER_MAX_VOLUME")) if os.getenv("COPY_TRADING_TRADER_MAX_VOLUME") else None,
                trader_min_pnl=float(os.getenv("COPY_TRADING_TRADER_MIN_PNL")) if os.getenv("COPY_TRADING_TRADER_MIN_PNL") else None,
                trader_min_pnl_per_vol=float(os.getenv("COPY_TRADING_TRADER_MIN_PNL_PER_VOL")) if os.getenv("COPY_TRADING_TRADER_MIN_PNL_PER_VOL") else None,
                trader_discovery_time_period=os.getenv("COPY_TRADING_TRADER_TIME_PERIOD", "WEEK"),
            ),
            market_making=MarketMakingSettings(
                max_spread=float(os.getenv("MARKET_MAKING_MAX_SPREAD", "2.0")),
                min_volume=float(os.getenv("MARKET_MAKING_MIN_VOLUME", "100")),
                max_position=float(os.getenv("MARKET_MAKING_MAX_POSITION", "5000")),
                discovery_min_liquidity=float(os.getenv("MARKET_MAKING_DISCOVERY_MIN_LIQUIDITY", "0")),
                discovery_min_spread_pct=float(os.getenv("MARKET_MAKING_DISCOVERY_MIN_SPREAD_PCT", "0.005")),
                discovery_min_volume_24h_kalshi=float(os.getenv("MARKET_MAKING_DISCOVERY_MIN_VOLUME_24H_KALSHI", "0")),
                discovery_max_markets=int(os.getenv("MARKET_MAKING_DISCOVERY_MAX_MARKETS", "50")),
                quote_spread=float(os.getenv("MARKET_MAKING_QUOTE_SPREAD", "0.02")),
            ),
            market_making_as=MarketMakingAsSettings(
                max_spread=float(os.getenv("MARKET_MAKING_AS_MAX_SPREAD", os.getenv("MARKET_MAKING_MAX_SPREAD", "2.0"))),
                min_volume=float(os.getenv("MARKET_MAKING_AS_MIN_VOLUME", os.getenv("MARKET_MAKING_MIN_VOLUME", "100"))),
                max_position=mm_as_max,
                quote_spread=float(os.getenv("MARKET_MAKING_AS_QUOTE_SPREAD", os.getenv("MARKET_MAKING_QUOTE_SPREAD", "0.02"))),
                discovery_min_liquidity=float(os.getenv("MARKET_MAKING_AS_DISCOVERY_MIN_LIQUIDITY", os.getenv("MARKET_MAKING_DISCOVERY_MIN_LIQUIDITY", "0"))),
                discovery_min_spread_pct=float(os.getenv("MARKET_MAKING_AS_DISCOVERY_MIN_SPREAD_PCT", os.getenv("MARKET_MAKING_DISCOVERY_MIN_SPREAD_PCT", "0.005"))),
                discovery_min_volume_24h_kalshi=float(os.getenv("MARKET_MAKING_AS_DISCOVERY_MIN_VOLUME_24H_KALSHI", os.getenv("MARKET_MAKING_DISCOVERY_MIN_VOLUME_24H_KALSHI", "0"))),
                discovery_max_markets=int(os.getenv("MARKET_MAKING_AS_DISCOVERY_MAX_MARKETS", os.getenv("MARKET_MAKING_DISCOVERY_MAX_MARKETS", "50"))),
                quote_update_interval_seconds=float(os.getenv("MARKET_MAKING_AS_QUOTE_UPDATE_INTERVAL_SECONDS", "5.0")),
                quote_reprice_threshold=float(os.getenv("MARKET_MAKING_AS_QUOTE_REPRICE_THRESHOLD", "0.02")),
                base_size_fraction=float(os.getenv("MARKET_MAKING_AS_BASE_SIZE_FRACTION", "0.1")),
                regime_size_beta=float(os.getenv("MARKET_MAKING_AS_REGIME_SIZE_BETA", "0.7")),
                inventory_size_eta=float(os.getenv("MARKET_MAKING_AS_INVENTORY_SIZE_ETA", "0.8")),
                min_size_fraction=float(os.getenv("MARKET_MAKING_AS_MIN_SIZE_FRACTION", "0.2")),
                cauchy_x0=float(os.getenv("MARKET_MAKING_AS_CAUCHY_X0", "0.0")),
                cauchy_gamma_base=float(os.getenv("MARKET_MAKING_AS_CAUCHY_GAMMA_BASE", "0.000005")),
                gamma_base=float(os.getenv("MARKET_MAKING_AS_GAMMA_BASE", "0.05")),
                gamma_alpha=float(os.getenv("MARKET_MAKING_AS_GAMMA_ALPHA", "0.5")),
                kappa=float(os.getenv("MARKET_MAKING_AS_KAPPA", "1.5")),
                session_horizon_seconds=float(os.getenv("MARKET_MAKING_AS_SESSION_HORIZON_SECONDS", "3600.0")),
                regime_buckets=int(os.getenv("MARKET_MAKING_AS_REGIME_BUCKETS", "10")),
                inventory_hard_gate_fraction=float(os.getenv("MARKET_MAKING_AS_INVENTORY_HARD_GATE_FRACTION", "0.9")),
                inventory_size_taper_exponent=float(os.getenv("MARKET_MAKING_AS_INVENTORY_SIZE_TAPER_EXPONENT", "2.0")),
                inventory_min_size_fraction=float(os.getenv("MARKET_MAKING_AS_INVENTORY_MIN_SIZE_FRACTION", "0.0")),
                inventory_quote_skew_coeff=float(os.getenv("MARKET_MAKING_AS_INVENTORY_QUOTE_SKEW_COEFF", "0.03")),
                band_quote_skew_coeff=float(os.getenv("MARKET_MAKING_AS_BAND_QUOTE_SKEW_COEFF", "0.015")),
                session_flatten_seconds=float(os.getenv("MARKET_MAKING_AS_SESSION_FLATTEN_SECONDS", "1800.0")),
            ),
            alt_data=AltDataSettings(
                confidence_threshold=float(os.getenv("ALT_DATA_CONFIDENCE_THRESHOLD", "0.7")),
                twitter_api_key=os.getenv("TWITTER_API_KEY"),
                twitter_api_secret=os.getenv("TWITTER_API_SECRET"),
                twitter_bearer_token=os.getenv("TWITTER_BEARER_TOKEN")
            ),
            simulator=SimulatorSettings(
                initial_balance=float(os.getenv("SIMULATOR_INITIAL_BALANCE", "100")),
                slippage=float(os.getenv("SIMULATOR_SLIPPAGE", "0.001")),
                latency_ms=int(os.getenv("SIMULATOR_LATENCY_MS", "50")),
                use_polymarket=os.getenv("SIMULATOR_USE_POLYMARKET", "True").lower() in ("true", "1", "t", "yes"),
                use_kalshi=os.getenv("SIMULATOR_USE_KALSHI", "False").lower() in ("true", "1", "t", "yes"),
                historical_rth_only=os.getenv("SIMULATOR_HISTORICAL_RTH_ONLY", "False").lower() in ("true", "1", "t", "yes"),
                trading_timezone=os.getenv("SIMULATOR_TRADING_TIMEZONE", "America/New_York"),
                regular_session_start=os.getenv("SIMULATOR_REGULAR_SESSION_START", "09:30"),
                regular_session_end=os.getenv("SIMULATOR_REGULAR_SESSION_END", "16:00"),
                enforce_signed_inventory_cap=os.getenv("SIMULATOR_ENFORCE_SIGNED_INVENTORY_CAP", "true").lower()
                in ("true", "1", "t", "yes"),
                max_signed_inventory=float(os.getenv("SIMULATOR_MAX_SIGNED_INVENTORY", str(mm_as_max))),
                use_schwab_spx=os.getenv("SIMULATOR_USE_SCHWAB_SPX", "False").lower() in ("true", "1", "t", "yes"),
                schwab_symbol=os.getenv("SIMULATOR_SCHWAB_SYMBOL", "$SPX"),
                bounds_file=os.getenv("SIMULATOR_BOUNDS_FILE", "data/kalshi_market_bounds.json"),
                spx_stale_seconds=float(os.getenv("SIMULATOR_SPX_STALE_SECONDS", "120")),
                spx_poll_interval_seconds=float(os.getenv("SIMULATOR_SPX_POLL_INTERVAL_SECONDS", "5")),
            )
        )


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get or create global settings instance"""
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings
