"""Alternative data collectors"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from datetime import datetime
import requests


class DataCollector(ABC):
    """Base class for data collectors"""
    
    @abstractmethod
    async def collect(self, keywords: List[str]) -> Dict[str, Any]:
        """Collect data based on keywords"""
        pass


class TwitterCollector(DataCollector):
    """Twitter/X data collector"""
    
    def __init__(self, bearer_token: str):
        """Initialize Twitter collector"""
        self.bearer_token = bearer_token
        self.base_url = "https://api.twitter.com/2"
        self.headers = {
            "Authorization": f"Bearer {bearer_token}",
            "User-Agent": "ApexPredictionMarkets/1.0"
        }
    
    async def collect_query(
        self,
        query: str,
        *,
        return_tweets: bool = False,
    ) -> Dict[str, Any]:
        """Run recent search for a raw X query string; optional tweet payloads for offline export."""
        query = (query or "").strip()
        if not query:
            return {
                "query": query,
                "sentiment_score": 0.0,
                "mention_count": 0,
                "engagement_score": 0.0,
                "tweets_analyzed": 0,
                "error": "empty query",
                "collected_at": datetime.utcnow().isoformat(),
                **({"tweets": []} if return_tweets else {}),
            }

        try:
            url = f"{self.base_url}/tweets/search/recent"
            params = {
                "query": query,
                "max_results": 100,
                "tweet.fields": "created_at,public_metrics,text",
                "expansions": "author_id",
            }

            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            tweets = data.get("data") or []

            sentiment_score = self._calculate_sentiment(tweets)
            total_mentions = len(tweets)
            total_engagement = sum(
                t.get("public_metrics", {}).get("like_count", 0)
                + t.get("public_metrics", {}).get("retweet_count", 0)
                for t in tweets
            )

            out: Dict[str, Any] = {
                "query": query,
                "sentiment_score": sentiment_score,
                "mention_count": total_mentions,
                "engagement_score": total_engagement,
                "tweets_analyzed": len(tweets),
                "collected_at": datetime.utcnow().isoformat(),
            }
            if return_tweets:
                out["tweets"] = [
                    {
                        "id": t.get("id"),
                        "created_at": t.get("created_at"),
                        "text": t.get("text"),
                        "public_metrics": t.get("public_metrics"),
                    }
                    for t in tweets
                ]
            return out

        except Exception as e:
            err: Dict[str, Any] = {
                "query": query,
                "sentiment_score": 0.0,
                "mention_count": 0,
                "engagement_score": 0.0,
                "tweets_analyzed": 0,
                "error": str(e),
                "collected_at": datetime.utcnow().isoformat(),
            }
            if return_tweets:
                err["tweets"] = []
            return err

    async def collect(self, keywords: List[str]) -> Dict[str, Any]:
        """Collect Twitter data for keywords (first five joined with OR)."""
        query = " OR ".join(keywords[:5])
        result = await self.collect_query(query, return_tweets=False)
        return {k: v for k, v in result.items() if k != "tweets"}
    
    def _calculate_sentiment(self, tweets: List[Dict]) -> float:
        """Calculate sentiment score from tweets (simple keyword-based)"""
        if not tweets:
            return 0.0
        
        positive_words = ["good", "great", "excellent", "positive", "up", "bullish", "win", "success"]
        negative_words = ["bad", "terrible", "negative", "down", "bearish", "loss", "fail"]
        
        positive_count = 0
        negative_count = 0
        
        for tweet in tweets:
            text = tweet.get("text", "").lower()
            positive_count += sum(1 for word in positive_words if word in text)
            negative_count += sum(1 for word in negative_words if word in text)
        
        total = positive_count + negative_count
        if total == 0:
            return 0.0
        
        # Normalize to -1 to 1, then to 0 to 1
        sentiment = (positive_count - negative_count) / total
        return (sentiment + 1) / 2  # Convert to 0-1 range


class SatelliteCollector(DataCollector):
    """Satellite imagery data collector (placeholder)"""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize satellite collector"""
        self.api_key = api_key
    
    async def collect(self, keywords: List[str]) -> Dict[str, Any]:
        """Collect satellite data (placeholder)"""
        # This would integrate with satellite imagery APIs
        # For now, return placeholder data
        return {
            "data_available": False,
            "message": "Satellite collector not yet implemented",
            "collected_at": datetime.utcnow().isoformat()
        }
