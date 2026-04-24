# Twitter × Polymarket: niche, repeatable research ideas

Each idea is **slow-moving** (daily or weekly pulls are enough), **niche** (less efficient than major macro markets), and **testable** with **scheduled `pull_twitter.py` JSONL** plus Polymarket **`prices-history`** / saved `prices.json` (see `data_gathering_poly/`). X **Recent Search** is short-horizon; long backtests require accumulating pulls over time or higher-tier X access.

1. **Regulatory rumor volume** — FDA / EPA / FTC rulemaking or approval markets — chatter spikes before formal dockets move; **test:** daily tweet counts + sentiment vs next-day price change.

2. **Earnings whisper keywords** — single-name or sector “EPS beat” style events on Polymarket — “guidance,” “miss,” “raise”; **test:** mean sentiment vs daily return on token tied to that earnings window.

3. **Weather station / city keywords** — regional temperature or storm markets — hashtags for a city + “record heat”; **test:** mention_count vs price on daily resolution.

4. **Sports injury report accounts** — player or team conditional markets — team name + “injury” OR “out”; **test:** engagement_score vs price, lag 0–2 days.

5. **Fed speaker names + “dot plot”** — rates / CPI markets — speaker surname + “hawkish” / “dovish”; **test:** sentiment vs logit(price), weekly aggregation.

6. **Court case nicknames** — litigation / Supreme Court markets — case shorthand + “oral argument”; **test:** volume of mentions vs price around argument date.

7. **Oil rig / OPEC chatter** — energy level markets — “OPEC+” OR “cut” OR “spare capacity”; **test:** daily mention_count vs token over OPEC meeting weeks.

8. **Shipping / freight terms** — supply-chain or recession proxies — “Baltic Dry” OR “container rates”; **test:** correlate with macro-linked Polymarket baskets, weekly.

9. **Local election hashtags** — mayor or ballot measure markets — city + “election”; **test:** cross-section: same query across cycles if repeatable slugs exist.

10. **Crypto exchange / ETF keywords** — BTC ETF or regulatory approval markets — “ETF” + issuer name; **test:** engagement spikes vs daily return.

11. **AI lab + product names** — tech milestone markets — “GPT” OR “Claude” + “release”; **test:** tweets_analyzed vs price (niche, noisy).

12. **Space launch windows** — launch success or schedule markets — rocket + “scrub” OR “launch”; **test:** mention burst vs price before window.

13. **Film / Oscar buzz** — entertainment outcome markets — title + “box office” OR “Oscar”; **test:** weekly sentiment vs price.

14. **TV show + “finale”** — renewal or rating proxies — show name + “ratings”; **test:** daily series with lag around finale air date.

15. **University / research lab + “paper”** — science milestone markets — topic + “Nature” OR “preprint”; **test:** low-frequency, monthly aggregation.

16. **Disease surveillance terms** — public-health style events — pathogen name + “cases” (careful: sensitive topics); **test:** mention trend vs price on weekly bars.

17. **Congress bill nicknames** — legislative passage markets — acronym + “vote”; **test:** event study: correlate 3-day tweet sum with price before vote.

18. **Central bank non-Fed** — ECB / BoE markets — “ECB” + “Lagarde”; **test:** same template as Fed idea with different handles.

19. **Real estate / city + “rent”** — housing CPI or city economy markets — city + “rent” OR “lease”; **test:** slow variables, monthly resample in correlate script (`--freq`).

20. **Agriculture / crop reports** — WASDE-adjacent themes if markets exist — “corn” + “USDA”; **test:** report-week mention spike vs price.

21. **Labor strike keywords** — company or industry strike markets — company + “strike” OR “UAW”; **test:** lagged correlation (labor news is sticky).

22. **Geopolitical chokepoints** — canal / strait disruption markets — canal name + “traffic”; **test:** daily engagement vs price (episodic).

23. **Conference hashtags** — “Consensus” / industry conf + asset — **test:** conference-week mention density vs niche token.

24. **Podcast / influencer names** — small narrative markets driven by one show — host + topic keyword; **test:** weekly sum engagement vs price.

25. **Cross-market “arbitrage” chatter** — same theme on X vs Polymarket wording — query mirrors **exact** market title keywords; **test:** end-to-end pipeline: `pull_twitter.py` with title-derived query + `correlate_polymarket.py` on that market’s token.

---

**Operational notes**

- Prefer **one pull per UTC day** per query to avoid overlapping tweet sets skewing aggregates.
- Use **`--lag-days`** when theory says X leads Polymarket (or vice versa: experiment with sign by shifting price instead in a notebook).
- Respect **X Developer Policy** on storage and display if using `--dump-raw-tweets`.
