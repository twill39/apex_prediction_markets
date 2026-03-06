"""Data persistence layer"""

import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
import json
from src.config import get_settings
from src.data.models import (
    Market, Order, Position, Trade, MarketEvent, TraderPerformance, Platform
)


class DataStorage:
    """Data storage using SQLite"""
    
    def __init__(self, db_path: Optional[str] = None):
        """Initialize data storage"""
        settings = get_settings()
        self.db_path = db_path or settings.database.path
        
        # Create database directory if it doesn't exist
        db_file = Path(self.db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize database
        self._init_database()
    
    def _init_database(self):
        """Initialize database schema"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Markets table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS markets (
                market_id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                outcome_tokens TEXT,
                resolution_date TEXT,
                created_at TEXT,
                volume REAL DEFAULT 0.0,
                open_interest REAL DEFAULT 0.0,
                is_active INTEGER DEFAULT 1,
                metadata TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Orders table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                market_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                side TEXT NOT NULL,
                order_type TEXT NOT NULL,
                price REAL,
                size REAL NOT NULL,
                filled_size REAL DEFAULT 0.0,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                strategy_id TEXT,
                metadata TEXT
            )
        """)
        
        # Positions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                position_id TEXT PRIMARY KEY,
                market_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                side TEXT NOT NULL,
                size REAL NOT NULL,
                average_price REAL NOT NULL,
                current_price REAL,
                unrealized_pnl REAL DEFAULT 0.0,
                realized_pnl REAL DEFAULT 0.0,
                opened_at TEXT NOT NULL,
                closed_at TEXT,
                strategy_id TEXT,
                metadata TEXT
            )
        """)
        
        # Trades table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                trade_id TEXT PRIMARY KEY,
                market_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                size REAL NOT NULL,
                timestamp TEXT NOT NULL,
                order_id TEXT,
                strategy_id TEXT,
                fees REAL DEFAULT 0.0,
                metadata TEXT
            )
        """)
        
        # Market events table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS market_events (
                event_id TEXT PRIMARY KEY,
                market_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                event_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                data TEXT
            )
        """)
        
        # Trader performance table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trader_performance (
                trader_id TEXT,
                platform TEXT NOT NULL,
                total_trades INTEGER DEFAULT 0,
                winning_trades INTEGER DEFAULT 0,
                losing_trades INTEGER DEFAULT 0,
                win_rate REAL DEFAULT 0.0,
                total_pnl REAL DEFAULT 0.0,
                roi REAL DEFAULT 0.0,
                sharpe_ratio REAL,
                max_drawdown REAL DEFAULT 0.0,
                average_trade_size REAL DEFAULT 0.0,
                last_updated TEXT NOT NULL,
                metadata TEXT,
                PRIMARY KEY (trader_id, platform)
            )
        """)
        
        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_market ON orders(market_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_strategy ON orders(strategy_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_market ON trades(market_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_market ON market_events(market_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON market_events(timestamp)")
        
        conn.commit()
        conn.close()
    
    def save_market(self, market: Market):
        """Save market to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO markets 
            (market_id, platform, title, description, outcome_tokens, resolution_date,
             created_at, volume, open_interest, is_active, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            market.market_id,
            market.platform.value,
            market.title,
            market.description,
            json.dumps(market.outcome_tokens),
            market.resolution_date.isoformat() if market.resolution_date else None,
            market.created_at.isoformat() if market.created_at else None,
            market.volume,
            market.open_interest,
            1 if market.is_active else 0,
            json.dumps(market.metadata)
        ))
        
        conn.commit()
        conn.close()
    
    def get_market(self, market_id: str) -> Optional[Market]:
        """Get market by ID"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM markets WHERE market_id = ?", (market_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        return Market(
            market_id=row["market_id"],
            platform=Platform(row["platform"]),
            title=row["title"],
            description=row["description"],
            outcome_tokens=json.loads(row["outcome_tokens"] or "[]"),
            resolution_date=datetime.fromisoformat(row["resolution_date"]) if row["resolution_date"] else None,
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
            volume=row["volume"],
            open_interest=row["open_interest"],
            is_active=bool(row["is_active"]),
            metadata=json.loads(row["metadata"] or "{}")
        )
    
    def save_order(self, order: Order):
        """Save order to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO orders 
            (order_id, market_id, platform, side, order_type, price, size,
             filled_size, status, created_at, updated_at, strategy_id, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            order.order_id,
            order.market_id,
            order.platform.value,
            order.side.value,
            order.order_type.value,
            order.price,
            order.size,
            order.filled_size,
            order.status.value,
            order.created_at.isoformat(),
            order.updated_at.isoformat() if order.updated_at else None,
            order.strategy_id,
            json.dumps(order.metadata)
        ))
        
        conn.commit()
        conn.close()
    
    def save_trade(self, trade: Trade):
        """Save trade to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO trades 
            (trade_id, market_id, platform, side, price, size, timestamp,
             order_id, strategy_id, fees, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trade.trade_id,
            trade.market_id,
            trade.platform.value,
            trade.side.value,
            trade.price,
            trade.size,
            trade.timestamp.isoformat(),
            trade.order_id,
            trade.strategy_id,
            trade.fees,
            json.dumps(trade.metadata)
        ))
        
        conn.commit()
        conn.close()
    
    def save_trader_performance(self, performance: TraderPerformance):
        """Save trader performance to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO trader_performance 
            (trader_id, platform, total_trades, winning_trades, losing_trades,
             win_rate, total_pnl, roi, sharpe_ratio, max_drawdown,
             average_trade_size, last_updated, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            performance.trader_id,
            performance.platform.value,
            performance.total_trades,
            performance.winning_trades,
            performance.losing_trades,
            performance.win_rate,
            performance.total_pnl,
            performance.roi,
            performance.sharpe_ratio,
            performance.max_drawdown,
            performance.average_trade_size,
            performance.last_updated.isoformat(),
            json.dumps(performance.metadata)
        ))
        
        conn.commit()
        conn.close()
    
    def get_trader_performance(self, trader_id: str, platform: Platform) -> Optional[TraderPerformance]:
        """Get trader performance"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT * FROM trader_performance WHERE trader_id = ? AND platform = ?",
            (trader_id, platform.value)
        )
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        return TraderPerformance(
            trader_id=row["trader_id"],
            platform=Platform(row["platform"]),
            total_trades=row["total_trades"],
            winning_trades=row["winning_trades"],
            losing_trades=row["losing_trades"],
            win_rate=row["win_rate"],
            total_pnl=row["total_pnl"],
            roi=row["roi"],
            sharpe_ratio=row["sharpe_ratio"],
            max_drawdown=row["max_drawdown"],
            average_trade_size=row["average_trade_size"],
            last_updated=datetime.fromisoformat(row["last_updated"]),
            metadata=json.loads(row["metadata"] or "{}")
        )


# Global storage instance
_storage: Optional[DataStorage] = None


def get_storage() -> DataStorage:
    """Get or create global storage instance"""
    global _storage
    if _storage is None:
        _storage = DataStorage()
    return _storage
