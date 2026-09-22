"""
backend/test_chart_endpoints.py — Test chart endpoints: /previous-close and /history
"""

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_previous_close_us():
    resp = client.get("/api/prices/AAPL/previous-close")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ticker"] == "AAPL"
    assert "previous_close" in data
    assert isinstance(data["previous_close"], (int, float))
    assert data["previous_close"] > 0
    assert data["currency"] == "USD"
    print(f"PASS: AAPL previous_close: {data}")


def test_previous_close_in():
    resp = client.get("/api/prices/RELIANCE.NS/previous-close")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ticker"] == "RELIANCE.NS"
    assert "previous_close" in data
    assert isinstance(data["previous_close"], (int, float))
    assert data["previous_close"] > 0
    assert data["currency"] == "INR"
    print(f"PASS: RELIANCE.NS previous_close: {data}")


def test_history_ranges():
    for r, interval in [("1d", "5m"), ("1w", "15m"), ("1m", "1d")]:
        resp = client.get(f"/api/prices/AAPL/history?range={r}&interval={interval}")
        assert resp.status_code == 200, resp.text
        candles = resp.json()
        assert isinstance(candles, list)
        assert len(candles) > 0, f"Expected candles for AAPL range {r}"
        c = candles[0]
        for field in ("time", "open", "high", "low", "close", "volume"):
            assert field in c, f"Missing {field} in candle"
        print(f"PASS: AAPL range {r} yielded {len(candles)} candles")


if __name__ == "__main__":
    test_previous_close_us()
    test_previous_close_in()
    test_history_ranges()
    print("ALL CHART ENDPOINT TESTS PASSED!")
