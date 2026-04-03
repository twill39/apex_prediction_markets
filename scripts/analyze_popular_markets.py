import asyncio
import os
import sys
from collections import Counter
from pathlib import Path

# Add src to path just in case
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.strategies.screeners import ConsistentGrinderScreener, WhaleConvictionTracker
from src.discovery.trader_discovery import get_closed_positions, get_user_trades

async def main():
    print("Running screeners to find tracked traders...")
    
    grinder = ConsistentGrinderScreener()
    # Temporarily relaxing the strict requirements slightly for analysis purposes
    # so we get enough data points
    grinder.min_positions = 20
    grinder.min_win_rate = 0.50
    
    traders_grinder = await grinder.get_tracked_traders()
    
    whale = WhaleConvictionTracker()
    whale.min_trade_size_usd = 5000.0
    
    traders_whale = await whale.get_tracked_traders()
    
    traders = set(traders_grinder) | set(traders_whale)
    
    if not traders:
        print("No traders found with current settings.")
        return
        
    print(f"Found {len(traders)} top traders from Grinder and Whale screeners. Analyzing their recent activity...")
    
    market_title_counter = Counter()
    slug_counter = {}
    category_counter = Counter() 
    
    # We will look at both closed and recent trades for these users
    for trader_id in traders:
        positions = get_closed_positions(trader_id, limit=300)
        trades = get_user_trades(trader_id, limit=300)
        
        # Combine markets they traded in
        all_activities = positions + trades
        
        seen_markets_for_trader = set()
        
        for activity in all_activities:
            title = activity.get('title')
            condition_id = activity.get('conditionId')
            slug = activity.get('slug', '')
            
            if title and slug and slug not in seen_markets_for_trader:
                seen_markets_for_trader.add(slug)
                market_title_counter[title] += 1
                slug_counter[title] = slug
                
                # Guess category from slug prefix (e.g. 'epl-mac-not' -> 'EPL')
                parts = slug.split('-')
                if parts:
                    category = parts[0].upper()
                    # Some common prefixes
                    if category in ['EPL', 'NBA', 'NFL', 'NHL', 'FL1', 'BUNDESLIGA', 'UCL']:
                        category_counter['SPORTS'] += 1
                    elif 'TRUMP' in slug.upper() or 'ELECTION' in slug.upper():
                        category_counter['POLITICS'] += 1
                    elif category in ['BTC', 'ETH', 'SOL', 'CRYPTO']:
                        category_counter['CRYPTO'] += 1
                    else:
                        category_counter[category] += 1

    print("\n=== Most Popular Markets among Screened Traders ===")
    most_common_markets = market_title_counter.most_common(20)
    for title, count in most_common_markets:
        print(f"({count} top traders traded this) | {title}")
        
    print("\n=== Guessed Categories of Interest ===")
    for cat, count in category_counter.most_common(10):
        print(f"[{count} unique trader interactions] {cat}")

    # Write a market list file so the user can easily subscribe to these high-value markets
    print("\nSaving the top 50 markets to simulator/screener_market_list.txt ...")
    os.makedirs('simulator', exist_ok=True)
    with open('simulator/screener_market_list.txt', 'w') as f:
        for title, count in market_title_counter.most_common(50):
            slug = slug_counter[title]
            f.write(f"{slug}\n")
            
    print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
