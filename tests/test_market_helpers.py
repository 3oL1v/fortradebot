import unittest

from fastapi.testclient import TestClient

from backend import config
from backend import main


class MarketHelperTests(unittest.TestCase):
    def test_parse_candle_accepts_dict_aliases(self):
        candle = main._parse_candle(
            {
                "openTime": 1710000000000,
                "o": "10",
                "h": "12",
                "l": "9",
                "c": "11",
                "quoteVolume": "12345.6",
            }
        )

        self.assertEqual(candle["time"], 1710000000000)
        self.assertEqual(candle["open"], 10.0)
        self.assertEqual(candle["high"], 12.0)
        self.assertEqual(candle["low"], 9.0)
        self.assertEqual(candle["close"], 11.0)
        self.assertEqual(candle["volume"], 12345.6)

    def test_parse_candle_accepts_array_format(self):
        candle = main._parse_candle([1710000000000, "10", "12", "9", "11", "7.5"])

        self.assertEqual(
            candle,
            {
                "time": 1710000000000,
                "open": 10.0,
                "high": 12.0,
                "low": 9.0,
                "close": 11.0,
                "volume": 7.5,
            },
        )

    def test_first_float_uses_first_available_numeric_field(self):
        data = {"quoteVolume": "100.5", "volume": "1"}

        self.assertEqual(main._first_float(data, "missing", "quoteVolume", "volume"), 100.5)

    def test_liquidations_returns_mock_without_coinglass_key(self):
        original_key = config.COINGLASS_API_KEY
        config.COINGLASS_API_KEY = ""
        try:
            with TestClient(main.app) as client:
                response = client.get("/api/liquidations/BTC")
        finally:
            config.COINGLASS_API_KEY = original_key

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total24h"], 0)
        self.assertEqual(payload["longsDominance"], 50)
        self.assertEqual(len(payload["longs"]), 24)
        self.assertEqual(len(payload["shorts"]), 24)

    def test_health_and_index_load(self):
        with TestClient(main.app) as client:
            self.assertEqual(client.get("/health").json(), {"status": "ok"})
            self.assertEqual(client.get("/").status_code, 200)


if __name__ == "__main__":
    unittest.main()
