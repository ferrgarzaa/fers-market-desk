"""Runtime configuration. Everything is read from environment variables so
that tests and the live demo can run the same code with different settings.
No credentials are needed: Yahoo Finance streaming is unauthenticated."""
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

# Instruments shown in the watchlist. Crypto trades 24/7, so the live stream
# can be demonstrated even when the US stock market is closed.
SYMBOLS = [s.strip() for s in os.getenv(
    "SYMBOLS", "BTC-USD,ETH-USD,AAPL,TSLA,NVDA").split(",") if s.strip()]

# Candle intervals the aggregator maintains, in seconds.
INTERVALS = {"1m": 60, "5m": 300, "15m": 900}

DB_PATH = Path(os.getenv("DB_PATH", str(BACKEND_DIR / "data" / "market.db")))

# "yahoo" = live Yahoo Finance WebSocket (the graded live path)
# "fake"  = deterministic synthetic ticks, ONLY for automated tests / offline UI work.
FEED_MODE = os.getenv("FEED_MODE", "yahoo").lower()

YAHOO_WS_URL = os.getenv("YAHOO_WS_URL", "wss://streamer.finance.yahoo.com/?version=2")

# Seconds without any message before a connected feed is reported as STALE.
STALE_AFTER_S = float(os.getenv("STALE_AFTER_S", "30"))
# Seconds after an interval ends before the candle is finalized by the clock.
FINALIZE_GRACE_S = float(os.getenv("FINALIZE_GRACE_S", "3"))
# Seconds to wait between reconnect attempts (doubles up to the max).
RECONNECT_MIN_S = float(os.getenv("RECONNECT_MIN_S", "2"))
RECONNECT_MAX_S = float(os.getenv("RECONNECT_MAX_S", "30"))
# Whether to load recent historical bars on startup (yahoo mode).
BACKFILL = os.getenv("BACKFILL", "1") == "1"
