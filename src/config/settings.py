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


class MarketMakingSettings(BaseModel):
    """Market making strategy settings"""
    max_spread: float = Field(default=0.05, description="Maximum spread to market make on")
    min_volume: float = Field(default=100.0, description="Minimum daily volume")
    max_position: float = Field(default=5000.0, description="Maximum position size")


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
        """Create settings from environment variables"""
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
                use_kalshi=os.getenv("COPY_TRADING_USE_KALSHI", "False").lower() in ("true", "1", "t", "yes")
            ),
            market_making=MarketMakingSettings(
                max_spread=float(os.getenv("MARKET_MAKING_MAX_SPREAD", "0.05")),
                min_volume=float(os.getenv("MARKET_MAKING_MIN_VOLUME", "100")),
                max_position=float(os.getenv("MARKET_MAKING_MAX_POSITION", "5000"))
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
