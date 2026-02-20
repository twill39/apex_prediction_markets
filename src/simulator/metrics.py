"""Performance metrics calculation"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import numpy as np
from pydantic import BaseModel, Field

from src.data.models import Trade, Position


class PerformanceMetrics(BaseModel):
    """Performance metrics"""
    total_trades: int = Field(default=0, description="Total number of trades")
    winning_trades: int = Field(default=0, description="Number of winning trades")
    losing_trades: int = Field(default=0, description="Number of losing trades")
    win_rate: float = Field(default=0.0, description="Win rate (0-1)")
    total_pnl: float = Field(default=0.0, description="Total profit and loss")
    total_return: float = Field(default=0.0, description="Total return (%)")
    sharpe_ratio: Optional[float] = Field(default=None, description="Sharpe ratio")
    max_drawdown: float = Field(default=0.0, description="Maximum drawdown")
    max_drawdown_pct: float = Field(default=0.0, description="Maximum drawdown (%)")
    average_trade_size: float = Field(default=0.0, description="Average trade size")
    average_win: float = Field(default=0.0, description="Average winning trade")
    average_loss: float = Field(default=0.0, description="Average losing trade")
    profit_factor: float = Field(default=0.0, description="Profit factor")
    start_time: datetime = Field(..., description="Start time")
    end_time: datetime = Field(..., description="End time")
    duration: timedelta = Field(..., description="Trading duration")


def calculate_metrics(
    trades: List[Trade],
    positions: List[Position],
    initial_balance: float,
    current_balance: float,
    start_time: datetime,
    end_time: datetime
) -> PerformanceMetrics:
    """Calculate comprehensive performance metrics"""
    
    if not trades:
        return PerformanceMetrics(
            start_time=start_time,
            end_time=end_time,
            duration=end_time - start_time
        )
    
    # Calculate PnL from trades (simplified)
    # In a real implementation, you'd track actual PnL from closed positions
    trade_pnls = []
    winning_count = 0
    losing_count = 0
    total_win = 0.0
    total_loss = 0.0
    
    for trade in trades:
        # Simplified PnL calculation
        # In production, you'd calculate based on position entry/exit
        pnl = 0.0  # Placeholder
        trade_pnls.append(pnl)
        
        if pnl > 0:
            winning_count += 1
            total_win += pnl
        elif pnl < 0:
            losing_count += 1
            total_loss += abs(pnl)
    
    # Calculate from balance change
    total_pnl = current_balance - initial_balance
    total_return = (total_pnl / initial_balance * 100) if initial_balance > 0 else 0.0
    
    # Win rate
    win_rate = winning_count / len(trades) if trades else 0.0
    
    # Average trade size
    average_trade_size = np.mean([t.size for t in trades]) if trades else 0.0
    
    # Average win/loss
    average_win = total_win / winning_count if winning_count > 0 else 0.0
    average_loss = total_loss / losing_count if losing_count > 0 else 0.0
    
    # Profit factor
    profit_factor = total_win / total_loss if total_loss > 0 else 0.0
    
    # Sharpe ratio
    sharpe_ratio = None
    if len(trade_pnls) > 1:
        returns = np.array(trade_pnls) / initial_balance if initial_balance > 0 else np.array(trade_pnls)
        if np.std(returns) > 0:
            sharpe_ratio = np.mean(returns) / np.std(returns) * np.sqrt(252)  # Annualized
    
    # Maximum drawdown
    balance_curve = [initial_balance]
    for trade in trades:
        # Simplified - would track actual balance over time
        balance_curve.append(balance_curve[-1] + (trade.price * trade.size * 0.001))  # Placeholder
    
    max_drawdown = 0.0
    max_drawdown_pct = 0.0
    if len(balance_curve) > 1:
        peak = balance_curve[0]
        for balance in balance_curve[1:]:
            if balance > peak:
                peak = balance
            drawdown = peak - balance
            drawdown_pct = (drawdown / peak * 100) if peak > 0 else 0.0
            if drawdown > max_drawdown:
                max_drawdown = drawdown
                max_drawdown_pct = drawdown_pct
    
    return PerformanceMetrics(
        total_trades=len(trades),
        winning_trades=winning_count,
        losing_trades=losing_count,
        win_rate=win_rate,
        total_pnl=total_pnl,
        total_return=total_return,
        sharpe_ratio=sharpe_ratio,
        max_drawdown=max_drawdown,
        max_drawdown_pct=max_drawdown_pct,
        average_trade_size=average_trade_size,
        average_win=average_win,
        average_loss=average_loss,
        profit_factor=profit_factor,
        start_time=start_time,
        end_time=end_time,
        duration=end_time - start_time
    )


def generate_report(metrics: PerformanceMetrics) -> str:
    """Generate a text report from metrics"""
    report = f"""
Performance Report
=================
Period: {metrics.start_time.strftime('%Y-%m-%d %H:%M:%S')} to {metrics.end_time.strftime('%Y-%m-%d %H:%M:%S')}
Duration: {metrics.duration}

Trading Statistics
------------------
Total Trades: {metrics.total_trades}
Winning Trades: {metrics.winning_trades}
Losing Trades: {metrics.losing_trades}
Win Rate: {metrics.win_rate:.2%}

Performance
-----------
Total P&L: ${metrics.total_pnl:,.2f}
Total Return: {metrics.total_return:.2f}%
Sharpe Ratio: {metrics.sharpe_ratio:.2f if metrics.sharpe_ratio else 'N/A'}
Max Drawdown: ${metrics.max_drawdown:,.2f} ({metrics.max_drawdown_pct:.2f}%)

Trade Analysis
--------------
Average Trade Size: ${metrics.average_trade_size:,.2f}
Average Win: ${metrics.average_win:,.2f}
Average Loss: ${metrics.average_loss:,.2f}
Profit Factor: {metrics.profit_factor:.2f}
"""
    return report
