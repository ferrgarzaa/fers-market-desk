"""End-to-end through FastAPI: fake feed -> store -> REST and WebSocket."""
import time

from fastapi.testclient import TestClient

from app.main import create_app


def test_ws_snapshot_live_candles_and_outage(tmp_path):
    app = create_app(db_path=tmp_path / "t.db", feed_mode="fake")
    with TestClient(app) as client:
        assert client.get("/api/health").json()["ok"] is True
        with client.websocket_connect("/ws") as ws:
            first = ws.receive_json()
            assert first["type"] == "snapshot" and first["symbol"] == "BTC-USD"
            assert len(first["candles"]) > 50                      # backfilled history
            ws.send_json({"action": "subscribe", "symbol": "ETH-USD", "interval": "5m"})
            got_candle = got_tick = False
            for _ in range(400):
                m = ws.receive_json()
                if m["type"] == "candle":
                    assert m["candle"]["symbol"] == "ETH-USD" and m["candle"]["interval"] == "5m"
                    got_candle = True
                if m["type"] == "tick":
                    got_tick = True
                if got_candle and got_tick:
                    break
            assert got_candle and got_tick

        st = client.get("/api/status").json()
        assert st["feed"]["state"] == "live" and st["db"]["ticks"] > 0

        r = client.post("/api/feed/outage", json={"enabled": True}).json()
        assert r["state"] == "unavailable" and r["simulated_outage"] is True
        ticks_before = client.get("/api/status").json()["db"]["ticks"]
        time.sleep(1.2)
        assert client.get("/api/status").json()["db"]["ticks"] == ticks_before
        events = [e["state"] for e in client.get("/api/feed-events").json()]
        assert "unavailable" in events

        client.post("/api/feed/outage", json={"enabled": False})
        time.sleep(1.2)
        assert client.get("/api/status").json()["feed"]["state"] == "live"

        rep = client.get("/api/replay", params={"symbol": "BTC-USD", "interval": "1m"}).json()
        assert len(rep) > 0 and rep == sorted(rep, key=lambda r: r["id"])


def test_rejects_unknown_symbol(tmp_path):
    app = create_app(db_path=tmp_path / "t.db", feed_mode="fake", start_feed=False)
    with TestClient(app) as client:
        assert client.get("/api/candles", params={"symbol": "NOPE"}).status_code == 404
        assert client.get("/api/candles", params={"symbol": "BTC-USD", "interval": "2h"}).status_code == 400
