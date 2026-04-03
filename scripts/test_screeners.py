import asyncio
import sys
import os

# Add the project root to the PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.strategies.screeners.grinder_screener import ConsistentGrinderScreener
from src.strategies.screeners.trendsetter_screener import TrendsetterScreener
from src.strategies.screeners.whale_screener import WhaleConvictionTracker
from src.utils.logger import get_logger
import logging

async def test():
    get_logger()
    
    print("================ Testing ConsistentGrinderScreener ================")
    gs = ConsistentGrinderScreener()
    # Speed up test by overriding candidates pool size or we just wait 10s
    grinders = await gs.get_tracked_traders()
    print(f"Discovered Grinders: {grinders}")
    
    print("\n================ Testing TrendsetterScreener ================")
    ts = TrendsetterScreener()
    # Maybe limit to a few to speed up execution
    # ts.get_tracked_traders = ... no wait, let's just run it, it's fast enough
    trendsetters = await ts.get_tracked_traders()
    print(f"Discovered Trendsetters: {trendsetters}")
    
    print("\n================ Testing WhaleConvictionTracker ================")
    ws = WhaleConvictionTracker()
    whales = await ws.get_tracked_traders()
    print(f"Discovered Whales: {whales}")

if __name__ == "__main__":
    asyncio.run(test())
