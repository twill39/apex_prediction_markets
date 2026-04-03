"""Application settings and configuration"""

import os
from typing import Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import yaml

# Load environment variables
load_dotenv()


class DatabaseSettings(BaseModel):
    """Database configuration"""
    path: str = Field(default="./data/trading_fund.db", description="Database file path")


class LoggingSettings(BaseModel):
    """Logging configuration"""
    level: str = Field(default="INFO", description="Log level (DEBUG, INFO, WARNING, ERROR)")
    file: Optional[str] = Field(default="./logs/trading_fund.log", description="Log file path")


class GrinderScreenerSettings(BaseModel):
    enabled: bool = Field(default=True, description="Enable grinder screener")
    min_positions: int = Field(default=50, description="Minimum positions for grinder")
    max_positions: int = Field(default=500, description="Maximum positions (filters out noise traders)")
    min_win_rate: float = Field(default=0.55, description="Minimum win rate for grinder")
    min_total_pnl: float = Field(default=500.0, description="Minimum total realized PnL in USD")
    min_avg_pnl_per_trade: float = Field(default=5.0, description="Minimum average PnL per closed position")


class WhaleScreenerSettings(BaseModel):
    enabled: bool = Field(default=True, description="Enable whale screener")
    min_trade_size_usd: float = Field(default=10000.0, description="Minimum trade size USD for whale")
    min_days_to_resolution: int = Field(default=3, description="Minimum days to resolution for whale")
    max_unique_markets: int = Field(default=20, description="Max unique markets (insiders are concentrated)")
    min_total_pnl: float = Field(default=1000.0, description="Minimum total realized PnL in USD")
    min_win_rate: float = Field(default=0.40, description="Minimum win rate for whale")
    min_closed_positions: int = Field(default=3, description="Minimum closed positions required")


class TrendsetterScreenerSettings(BaseModel):
    enabled: bool = Field(default=True, description="Enable trendsetter screener")
    min_capture_margin: float = Field(default=0.30, description="Minimum capture margin for trendsetter")
    min_hold_time_hours: float = Field(default=1.0, description="Minimum hold time hours for trendsetter")
    min_round_trips: int = Field(default=5, description="Minimum round trips for trendsetter")
    min_win_rate: float = Field(default=0.50, description="Minimum win rate on round trips")
    min_avg_trade_size: float = Field(default=50.0, description="Minimum avg trade size USD to filter micro-traders")


class ScreenersSettings(BaseModel):
    grinder: GrinderScreenerSettings = Field(default_factory=GrinderScreenerSettings)
    whale: WhaleScreenerSettings = Field(default_factory=WhaleScreenerSettings)
    trendsetter: TrendsetterScreenerSettings = Field(default_factory=TrendsetterScreenerSettings)


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
    screeners: ScreenersSettings = Field(default_factory=ScreenersSettings)


class MarketMakingSettings(BaseModel):
    """Market making strategy settings"""
    max_spread: float = Field(default=0.05, description="Maximum spread to market make on")
    min_volume: float = Field(default=100.0, description="Minimum daily volume")
    max_position: float = Field(default=5000.0, description="Maximum position size")
    # Market discovery: high spread + decent liquidity
    discovery_min_liquidity: float = Field(default=0.0, description="Min liquidity (Polymarket) for discovery")
    discovery_min_spread_pct: float = Field(default=0.005, description="Min spread as fraction (e.g. 0.01 = 1%)")
    discovery_min_volume_24h_kalshi: float = Field(default=0.0, description="Min 24h volume (Kalshi) for discovery")
    discovery_max_markets: int = Field(default=50, description="Max markets to discover per platform")


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


class Settings(BaseModel):
    """Application settings"""
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    copy_trading: CopyTradingSettings = Field(default_factory=CopyTradingSettings)
    market_making: MarketMakingSettings = Field(default_factory=MarketMakingSettings)
    alt_data: AltDataSettings = Field(default_factory=AltDataSettings)
    simulator: SimulatorSettings = Field(default_factory=SimulatorSettings)

    @classmethod
    def from_env(cls) -> "Settings":
        """Create settings from environment variables and YAML configs"""
        
        # Load Copy Trading YAML Configuration
        copy_trading_kwargs = {
            "max_position_size": float(os.getenv("COPY_TRADING_MAX_POSITION_SIZE", "1000")),
            "max_traders": int(os.getenv("COPY_TRADING_MAX_TRADERS", "10")),
            "use_kalshi": os.getenv("COPY_TRADING_USE_KALSHI", "False").lower() in ("true", "1", "t", "yes"),
            "trader_max_volume": float(os.getenv("COPY_TRADING_TRADER_MAX_VOLUME")) if os.getenv("COPY_TRADING_TRADER_MAX_VOLUME") else None,
            "trader_min_pnl": float(os.getenv("COPY_TRADING_TRADER_MIN_PNL")) if os.getenv("COPY_TRADING_TRADER_MIN_PNL") else None,
            "trader_min_pnl_per_vol": float(os.getenv("COPY_TRADING_TRADER_MIN_PNL_PER_VOL")) if os.getenv("COPY_TRADING_TRADER_MIN_PNL_PER_VOL") else None,
            "trader_discovery_time_period": os.getenv("COPY_TRADING_TRADER_TIME_PERIOD", "WEEK")
        }
        
        # Attempt to override with YAML config if it exists
        yaml_config_path = os.getenv("COPY_TRADING_CONFIG_PATH", "./config/copy_trading.yml")
        if os.path.exists(yaml_config_path):
            try:
                with open(yaml_config_path, "r") as f:
                    yaml_data = yaml.safe_load(f)
                    if yaml_data:
                        # Map base keys
                        for key in ["max_position_size", "max_traders", "use_kalshi"]:
                            if key in yaml_data:
                                copy_trading_kwargs[key] = yaml_data[key]
                        
                        # Map discovery keys
                        if "discovery" in yaml_data and isinstance(yaml_data["discovery"], dict):
                            discovery = yaml_data["discovery"]
                            if "trader_max_volume" in discovery:
                                copy_trading_kwargs["trader_max_volume"] = discovery["trader_max_volume"]
                            if "trader_min_pnl" in discovery:
                                copy_trading_kwargs["trader_min_pnl"] = discovery["trader_min_pnl"]
                            if "trader_min_pnl_per_vol" in discovery:
                                copy_trading_kwargs["trader_min_pnl_per_vol"] = discovery["trader_min_pnl_per_vol"]
                            if "time_period" in discovery:
                                copy_trading_kwargs["trader_discovery_time_period"] = discovery["time_period"]

                        # Map screener keys
                        if "screeners" in yaml_data and isinstance(yaml_data["screeners"], dict):
                            screeners = yaml_data["screeners"]
                            copy_trading_kwargs["screeners"] = ScreenersSettings(
                                grinder=GrinderScreenerSettings(**screeners.get("grinder", {})),
                                whale=WhaleScreenerSettings(**screeners.get("whale", {})),
                                trendsetter=TrendsetterScreenerSettings(**screeners.get("trendsetter", {}))
                            )
            except Exception as e:
                print(f"Failed to load copy trading YAML config: {e}")

        return cls(
            database=DatabaseSettings(
                path=os.getenv("DATABASE_PATH", "./data/trading_fund.db")
            ),
            logging=LoggingSettings(
                level=os.getenv("LOG_LEVEL", "INFO"),
                file=os.getenv("LOG_FILE", "./logs/trading_fund.log")
            ),
            copy_trading=CopyTradingSettings(**copy_trading_kwargs),
            market_making=MarketMakingSettings(
                max_spread=float(os.getenv("MARKET_MAKING_MAX_SPREAD", "0.05")),
                min_volume=float(os.getenv("MARKET_MAKING_MIN_VOLUME", "100")),
                max_position=float(os.getenv("MARKET_MAKING_MAX_POSITION", "5000")),
                discovery_min_liquidity=float(os.getenv("MARKET_MAKING_DISCOVERY_MIN_LIQUIDITY", "0")),
                discovery_min_spread_pct=float(os.getenv("MARKET_MAKING_DISCOVERY_MIN_SPREAD_PCT", "0.005")),
                discovery_min_volume_24h_kalshi=float(os.getenv("MARKET_MAKING_DISCOVERY_MIN_VOLUME_24H_KALSHI", "0")),
                discovery_max_markets=int(os.getenv("MARKET_MAKING_DISCOVERY_MAX_MARKETS", "50")),
            ),
            alt_data=AltDataSettings(
                confidence_threshold=float(os.getenv("ALT_DATA_CONFIDENCE_THRESHOLD", "0.7")),
                twitter_api_key=os.getenv("TWITTER_API_KEY"),
                twitter_api_secret=os.getenv("TWITTER_API_SECRET"),
                twitter_bearer_token=os.getenv("TWITTER_BEARER_TOKEN")
            ),
            simulator=SimulatorSettings(
                slippage=float(os.getenv("SIMULATOR_SLIPPAGE", "0.001")),
                latency_ms=int(os.getenv("SIMULATOR_LATENCY_MS", "50")),
                use_polymarket=os.getenv("SIMULATOR_USE_POLYMARKET", "True").lower() in ("true", "1", "t", "yes"),
                use_kalshi=os.getenv("SIMULATOR_USE_KALSHI", "False").lower() in ("true", "1", "t", "yes")
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
