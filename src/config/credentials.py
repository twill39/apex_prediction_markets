"""API credentials management"""

import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Load repository credentials regardless of the process working directory.
load_dotenv(PROJECT_ROOT / ".env")


def _credential_path(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return str(path.resolve())


class KalshiCredentials(BaseModel):
    """Kalshi API credentials (PEM private key file)"""
    api_key: str = Field(..., description="Kalshi API key ID")
    private_key_path: str = Field(..., description="Path to .pem private key file")
    base_url: str = Field(
        default="https://api.calendar.kalshi.com/trade-api/v2",
        description="Kalshi API base URL"
    )
    ws_url: str = Field(
        default="wss://api.calendar.kalshi.com/trade-api/ws/v2",
        description="Kalshi WebSocket URL"
    )


class SchwabCredentials(BaseModel):
    """Charles Schwab API credentials (schwabdev OAuth)."""
    app_key: str = Field(..., description="Schwab app key (APP_KEY)")
    app_secret: str = Field(..., description="Schwab app secret (APP_SECRET)")
    callback_url: Optional[str] = Field(
        default=None,
        description="OAuth callback URL (CALLBACK_URL); optional if tokens already exist",
    )
    token_path: Optional[str] = Field(
        default=None,
        description="Optional path to schwabdev tokens directory or file",
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
    schwab: Optional[SchwabCredentials] = None

    @classmethod
    def from_env(cls) -> "Credentials":
        """Create credentials from environment variables"""
        kalshi_key = os.getenv("KALSHI_API_KEY")
        kalshi_pem_path = os.getenv("KALSHI_PRIVATE_KEY_PATH") or os.getenv("KALSHI_PEM_PATH")
        
        kalshi = None
        if kalshi_key and kalshi_pem_path:
            base_url = os.getenv("KALSHI_BASE_URL", "https://api.calendar.kalshi.com/trade-api/v2")
            # Derive WebSocket URL from base URL if not set
            ws_url = os.getenv("KALSHI_WS_URL")
            if not ws_url and base_url.startswith("https://"):
                ws_url = base_url.replace("https://", "wss://", 1).rstrip("/")
                if ws_url.endswith("/v2"):
                    ws_url = ws_url[:-3] + "/ws/v2"
                else:
                    ws_url = ws_url + "/ws/v2"
            if not ws_url:
                ws_url = "wss://api.calendar.kalshi.com/trade-api/ws/v2"
            kalshi = KalshiCredentials(
                api_key=kalshi_key,
                private_key_path=_credential_path(kalshi_pem_path),
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

        schwab_key = os.getenv("APP_KEY") or os.getenv("SCHWAB_APP_KEY")
        schwab_secret = os.getenv("APP_SECRET") or os.getenv("SCHWAB_APP_SECRET")
        schwab = None
        if schwab_key and schwab_secret:
            schwab = SchwabCredentials(
                app_key=schwab_key,
                app_secret=schwab_secret,
                callback_url=os.getenv("CALLBACK_URL") or os.getenv("SCHWAB_CALLBACK_URL"),
                token_path=_credential_path(os.getenv("SCHWAB_TOKEN_PATH")),
            )
        
        return cls(kalshi=kalshi, polymarket=polymarket, schwab=schwab)


# Global credentials instance
_credentials: Optional[Credentials] = None


def get_credentials() -> Credentials:
    """Get or create global credentials instance"""
    global _credentials
    if _credentials is None:
        _credentials = Credentials.from_env()
    return _credentials
