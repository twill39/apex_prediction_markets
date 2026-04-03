import urllib.request
import json
import os

URL = "https://gamma-api.polymarket.com/events?limit=500&active=true&closed=false"
try:
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
        
    insider_keywords = ["youtube", "subscriber", "mrbeast", "twitch", "spotify", "box office", "airdrop", "token", "release", "leak", "announcement", "hbo", "netflix", "followers", "views"]
    
    found_markets = []
    for event in data:
        title = event.get("title", "").lower()
        slug = event.get("slug", "")
        if any(kw in title or kw in slug.lower() for kw in insider_keywords):
            if slug:
                # Add the event slug and title
                found_markets.append((slug, event.get("title") or title))
                    
    print(f"Found {len(found_markets)} markets. Writing to market_list.txt...")
    
    with open("market_list.txt", "w") as f:
        for market_id, title in found_markets:
            f.write(f"{market_id}\n")
            print(f"- {title}")
except Exception as e:
    print(f"Error: {e}")
