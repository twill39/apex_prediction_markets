"""API credentials management"""

import os
from typing import Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class KalshiCredentials(BaseModel):
    """Kalshi API credentials"""
    api_key: str = Field(..., description="Kalshi API key")
    api_secret: str = Field(..., description="Kalshi API secret")
    base_url: str = Field(
        default="https://api.calendar.kalshi.com/trade-api/v2",
        description="Kalshi API base URL"
    )


class PolymarketCredentials(BaseModel):
    """Polymarket API credentials"""
    api_key: Optional[str] = Field(default=None, description="Polymarket API key (if required)")
    base_url: str = Field(
        default="https://clob.polymarket.com",
        description="Polymarket API base URL"
    )


class Credentials(BaseModel):
    """All API credentials"""
    kalshi: Optional[KalshiCredentials] = None
    polymarket: Optional[PolymarketCredentials] = None

    @classmethod
    def from_env(cls) -> "Credentials":
        """Create credentials from environment variables"""
        kalshi_key = os.getenv("KALSHI_API_KEY")
        kalshi_secret = os.getenv("KALSHI_API_SECRET")
        
        kalshi = None
        if kalshi_key and kalshi_secret:
            kalshi = KalshiCredentials(
                api_key=kalshi_key,
                api_secret=kalshi_secret,
                base_url=os.getenv("KALSHI_BASE_URL", "https://api.calendar.kalshi.com/trade-api/v2")
            )
        
        polymarket_key = os.getenv("POLYMARKET_API_KEY")
        polymarket = None
        if polymarket_key:
            polymarket = PolymarketCredentials(
                api_key=polymarket_key,
                base_url=os.getenv("POLYMARKET_BASE_URL", "https://clob.polymarket.com")
            )
        else:
            # Polymarket may not require API key for public data
            polymarket = PolymarketCredentials(
                base_url=os.getenv("POLYMARKET_BASE_URL", "https://clob.polymarket.com")
            )
        
        return cls(kalshi=kalshi, polymarket=polymarket)


# Global credentials instance
_credentials: Optional[Credentials] = None


def get_credentials() -> Credentials:
    """Get or create global credentials instance"""
    global _credentials
    if _credentials is None:
        _credentials = Credentials.from_env()
    return _credentials
