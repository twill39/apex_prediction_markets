"""Performance metrics calculation"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import numpy as np
from pydantic import BaseModel, Field

from src.data.models import Trade, Position
from src.data.models import OrderSide


class PerformanceMetrics(BaseModel):
    """Performance metrics"""
    total_trades: int = Field(default=0, description="Total number of trades")
    closed_trades: int = Field(default=0, description="Number of closed FIFO match outcomes")
    winning_trades: int = Field(default=0, description="Number of winning trades")
    losing_trades: int = Field(default=0, description="Number of losing trades")
    win_rate: float = Field(default=0.0, description="Win rate (0-1)")
    starting_capital: float = Field(default=0.0, description="Starting cash allocated to the strategy")
    cash_balance: float = Field(default=0.0, description="Ending cash balance")
    inventory_value: float = Field(default=0.0, description="Mark-to-market value of open inventory")
    ending_equity: float = Field(default=0.0, description="Cash plus marked inventory value")
    realized_pnl: float = Field(default=0.0, description="Realized profit and loss")
    unrealized_pnl: float = Field(default=0.0, description="Unrealized profit and loss on open inventory")
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
    if not trades:
        inventory_value = sum(
            (position.current_price if position.current_price is not None else position.average_price) * position.size
            for position in positions
        )
        total_pnl = current_balance + inventory_value - initial_balance
        return PerformanceMetrics(
            starting_capital=initial_balance,
            cash_balance=current_balance,
            inventory_value=inventory_value,
            ending_equity=current_balance + inventory_value,
            unrealized_pnl=total_pnl,
            total_pnl=total_pnl,
            total_return=(total_pnl / initial_balance * 100) if initial_balance > 0 else 0.0,
            start_time=start_time,
            end_time=end_time,
            duration=end_time - start_time
        )

    # Match buys and sells per market using FIFO lots so we can split
    # realized and unrealized P&L while keeping open inventory marked.
    long_queues: Dict[str, list] = {}
    short_queues: Dict[str, list] = {}
    trade_pnls: List[float] = []
    balance_curve: List[float] = [initial_balance]
    running_balance = initial_balance

    for trade in sorted(trades, key=lambda t: t.timestamp):
        market_id = trade.market_id
        if market_id not in long_queues:
            long_queues[market_id] = []
        if market_id not in short_queues:
            short_queues[market_id] = []

        if trade.side == OrderSide.BUY:
            fee_per_unit = trade.fees / trade.size if trade.size > 0 else 0.0
            remaining_size = trade.size

            while remaining_size > 0 and short_queues[market_id]:
                short_lot = short_queues[market_id][0]
                matched_size = min(remaining_size, short_lot["size"])
                pnl = (
                    (short_lot["price"] - trade.price) * matched_size
                    - (short_lot["fee_per_unit"] + fee_per_unit) * matched_size
                )
                trade_pnls.append(pnl)
                short_lot["size"] -= matched_size
                remaining_size -= matched_size
                if short_lot["size"] <= 0:
                    short_queues[market_id].pop(0)

            if remaining_size > 0:
                long_queues[market_id].append({
                    "price": trade.price,
                    "size": remaining_size,
                    "fee_per_unit": fee_per_unit,
                })
            running_balance -= trade.price * trade.size + trade.fees
            balance_curve.append(running_balance)

        elif trade.side == OrderSide.SELL:
            remaining_size = trade.size
            sell_price = trade.price
            sell_fee_per_unit = trade.fees / trade.size if trade.size > 0 else 0.0

            while remaining_size > 0 and long_queues[market_id]:
                buy_lot = long_queues[market_id][0]
                buy_price = buy_lot["price"]
                buy_size = buy_lot["size"]
                matched_size = min(remaining_size, buy_size)
                pnl = (
                    (sell_price - buy_price) * matched_size
                    - (buy_lot["fee_per_unit"] + sell_fee_per_unit) * matched_size
                )

                trade_pnls.append(pnl)

                remaining_size -= matched_size
                if matched_size >= buy_size:
                    long_queues[market_id].pop(0)
                else:
                    buy_lot["size"] = buy_size - matched_size

            if remaining_size > 0:
                short_queues[market_id].append({
                    "price": sell_price,
                    "size": remaining_size,
                    "fee_per_unit": sell_fee_per_unit,
                })
            running_balance += sell_price * trade.size - trade.fees
            balance_curve.append(running_balance)

    # Classify wins/losses
    winning_count = sum(1 for p in trade_pnls if p > 0)
    losing_count = sum(1 for p in trade_pnls if p < 0)
    closed_trades = winning_count + losing_count
    total_win = sum(p for p in trade_pnls if p > 0)
    total_loss = sum(abs(p) for p in trade_pnls if p < 0)
    realized_pnl = sum(trade_pnls)

    position_map = {position.market_id: position for position in positions}
    inventory_value = 0.0
    unrealized_pnl = 0.0
    for market_id, lots in long_queues.items():
        position = position_map.get(market_id)
        mark_price = None
        if position is not None:
            mark_price = position.current_price if position.current_price is not None else position.average_price
        if mark_price is None:
            mark_price = lots[-1]["price"] if lots else 0.0

        for lot in lots:
            inventory_value += mark_price * lot["size"]
            unrealized_pnl += (
                (mark_price - lot["price"]) * lot["size"]
                - lot["fee_per_unit"] * lot["size"]
            )

    for market_id, lots in short_queues.items():
        position = position_map.get(market_id)
        mark_price = None
        if position is not None:
            mark_price = position.current_price if position.current_price is not None else position.average_price
        if mark_price is None:
            mark_price = lots[-1]["price"] if lots else 0.0

        for lot in lots:
            inventory_value -= mark_price * lot["size"]
            unrealized_pnl += (
                (lot["price"] - mark_price) * lot["size"]
                - lot["fee_per_unit"] * lot["size"]
            )

    cash_balance = current_balance
    total_pnl = cash_balance + inventory_value - initial_balance
    total_return = (total_pnl / initial_balance * 100) if initial_balance > 0 else 0.0
    win_rate = winning_count / closed_trades if closed_trades > 0 else 0.0
    average_trade_size = float(np.mean([t.price * t.size for t in trades])) if trades else 0.0
    average_win = total_win / winning_count if winning_count > 0 else 0.0
    average_loss = total_loss / losing_count if losing_count > 0 else 0.0
    profit_factor = total_win / total_loss if total_loss > 0 else float('inf')

    # Sharpe ratio from closed outcome PnLs
    sharpe_ratio = None
    if closed_trades > 1:
        returns = np.array([p for p in trade_pnls if p != 0.0]) / initial_balance
        if np.std(returns) > 0:
            sharpe_ratio = float(np.mean(returns) / np.std(returns) * np.sqrt(252))

    # Max drawdown from balance curve
    max_drawdown = 0.0
    max_drawdown_pct = 0.0
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
        closed_trades=closed_trades,
        winning_trades=winning_count,
        losing_trades=losing_count,
        win_rate=win_rate,
        starting_capital=initial_balance,
        cash_balance=cash_balance,
        inventory_value=inventory_value,
        ending_equity=cash_balance + inventory_value,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
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
    sharpe_str = f"{metrics.sharpe_ratio:.2f}" if metrics.sharpe_ratio is not None else "N/A"
    pf_str = f"{metrics.profit_factor:.2f}" if metrics.profit_factor != float('inf') else "∞"
    report = f"""
Performance Report
=================
Period: {metrics.start_time.strftime('%Y-%m-%d %H:%M:%S')} to {metrics.end_time.strftime('%Y-%m-%d %H:%M:%S')}
Duration: {metrics.duration}

Trading Statistics
------------------
Total Trades: {metrics.total_trades}
Closed Trades: {metrics.closed_trades}
Winning Trades: {metrics.winning_trades}
Losing Trades: {metrics.losing_trades}
Win Rate (Closed): {metrics.win_rate:.2%}

Performance
-----------
Starting Capital: ${metrics.starting_capital:,.2f}
Cash Balance: ${metrics.cash_balance:,.2f}
Open Inventory Value: ${metrics.inventory_value:,.2f}
Ending Equity: ${metrics.ending_equity:,.2f}
Realized P&L: ${metrics.realized_pnl:,.2f}
Unrealized P&L: ${metrics.unrealized_pnl:,.2f}
Total P&L: ${metrics.total_pnl:,.2f}
Total Return: {metrics.total_return:.2f}%
Sharpe Ratio: {sharpe_str}
Max Drawdown: ${metrics.max_drawdown:,.2f} ({metrics.max_drawdown_pct:.2f}%)

Trade Analysis
--------------
Average Trade Size: ${metrics.average_trade_size:,.2f}
Average Win: ${metrics.average_win:,.2f}
Average Loss: ${metrics.average_loss:,.2f}
Profit Factor: {pf_str}
"""
    return report
