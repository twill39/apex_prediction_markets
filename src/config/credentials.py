"""API credentials management"""

import os
from typing import Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class KalshiCredentials(BaseModel):
    """Kalshi API credentials (PEM private key file)"""
    api_key: str = Field(..., description="Kalshi API key ID")
    private_key_path: str = Field(..., description="Path to .pem private key file")
    base_url: str = Field(
        default="https://api.elections.kalshi.com/trade-api/v2",
        description="Kalshi API base URL"
    )
    ws_url: str = Field(
        default="wss://api.elections.kalshi.com/trade-api/ws/v2",
        description="Kalshi WebSocket URL"
    )


class PolymarketCredentials(BaseModel):
    """Polymarket API credentials.
    Market channel: no auth. User channel: needs api_key + secret + passphrase (from Polymarket SDK).
    """
    api_key: Optional[str] = Field(default=None, description="Polymarket API key (user channel)")
    secret: Optional[str] = Field(default=None, description="Polymarket API secret (user channel)")
    passphrase: Optional[str] = Field(default=None, description="Polymarket API passphrase (user channel)")
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
        kalshi_pem_path = os.getenv("KALSHI_PRIVATE_KEY_PATH") or os.getenv("KALSHI_PEM_PATH")
        
        kalshi = None
        if kalshi_key and kalshi_pem_path:
            base_url = os.getenv("KALSHI_BASE_URL", "https://api.elections.kalshi.com/trade-api/v2")
            # Derive WebSocket URL from base URL if not set
            ws_url = os.getenv("KALSHI_WS_URL")
            if not ws_url and base_url.startswith("https://"):
                ws_url = base_url.replace("https://", "wss://", 1).rstrip("/")
                if ws_url.endswith("/v2"):
                    ws_url = ws_url[:-3] + "/ws/v2"
                else:
                    ws_url = ws_url + "/ws/v2"
            if not ws_url:
                ws_url = "wss://api.elections.kalshi.com/trade-api/ws/v2"
            kalshi = KalshiCredentials(
                api_key=kalshi_key,
                private_key_path=kalshi_pem_path,
                base_url=base_url,
                ws_url=ws_url
            )
        
        polymarket_key = os.getenv("POLYMARKET_API_KEY")
        polymarket_secret = os.getenv("POLYMARKET_SECRET")
        polymarket_passphrase = os.getenv("POLYMARKET_PASSPHRASE")
        polymarket = PolymarketCredentials(
            api_key=polymarket_key or None,
            secret=polymarket_secret or None,
            passphrase=polymarket_passphrase or None,
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
