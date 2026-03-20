import hashlib
import hmac
import os
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlencode

import numpy as np
import pandas as pd

from preprocessing import prepare_dataset
from production_hardening.security import decrypt_bytes, encrypt_bytes
from trading_strategy import execute_order
from walk_forward_validation import run_walk_forward


class TestPreprocessingLeakageFix(unittest.TestCase):
    def test_scaler_fits_train_only(self):
        n = 220
        idx = pd.date_range("2024-01-01", periods=n, freq="D")

        close = np.concatenate(
            [
                np.linspace(100, 260, 180),
                np.linspace(10, 49, 40),
            ]
        )
        df = pd.DataFrame(
            {
                "Open": close + 0.5,
                "High": close + 1.0,
                "Low": close - 1.0,
                "Close": close,
                "Volume": np.linspace(1_000, 5_000, n),
            },
            index=idx,
        )

        train_ratio = 0.7
        out = prepare_dataset(df, lookback=20, forecast_horizon=1, train_ratio=train_ratio, normalization="minmax")

        processed = out["processed_df"]
        split_row = int(len(processed) * train_ratio)
        close_idx = out["feature_cols"].index("Close")

        train_close_min = processed["Close"].values[:split_row].min()
        all_close_min = processed["Close"].values.min()
        fitted_min = out["scaler_params"]["mins"][close_idx]

        self.assertAlmostEqual(float(fitted_min), float(train_close_min), places=8)
        self.assertGreater(float(fitted_min), float(all_close_min))


class TestAesEncryptionFix(unittest.TestCase):
    def test_aes_roundtrip(self):
        plaintext = b"sensitive trading audit payload"
        passphrase = "unit-test-passphrase"

        encrypted = encrypt_bytes(plaintext, passphrase)
        decrypted = decrypt_bytes(encrypted, passphrase)

        self.assertNotEqual(encrypted, plaintext)
        self.assertEqual(decrypted, plaintext)


class TestLiveApiAuthFix(unittest.TestCase):
    @patch("trading_strategy.requests.post")
    def test_live_request_has_auth_header_and_signature(self, mock_post):
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.text = "{}"
        mock_response.json.return_value = {"ok": True}
        mock_post.return_value = mock_response

        with patch.dict(os.environ, {"BINANCE_API_KEY": "test-key", "BINANCE_API_SECRET": "test-secret"}, clear=False):
            result = execute_order(symbol="BTCUSDT", side="BUY", quantity=0.01, mode="live")

        self.assertEqual(result["status"], "ACCEPTED")
        kwargs = mock_post.call_args.kwargs
        headers = kwargs["headers"]
        payload = kwargs["data"]

        self.assertIn("X-MBX-APIKEY", headers)
        self.assertEqual(headers["X-MBX-APIKEY"], "test-key")
        self.assertIn("signature", payload)

        unsigned_payload = dict(payload)
        signature = unsigned_payload.pop("signature")
        expected = hmac.new(
            b"test-secret",
            urlencode(unsigned_payload).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(signature, expected)


class TestWalkForwardParameterizationFix(unittest.TestCase):
    @patch("walk_forward_validation.inverse_transform_close", side_effect=lambda arr, _: arr)
    @patch("walk_forward_validation.compute_metrics", return_value={"RMSE": 1.0, "MAPE (%)": 1.0, "R²": 0.5})
    @patch("walk_forward_validation.predict", side_effect=lambda model, X, device: np.ones(len(X), dtype=np.float32))
    @patch("walk_forward_validation.build_model", return_value=object())
    @patch("walk_forward_validation.fetch_data")
    @patch("walk_forward_validation.prepare_dataset")
    def test_walk_forward_uses_configurable_split_ratios(
        self,
        mock_prepare,
        _mock_fetch,
        _mock_build,
        _mock_predict,
        _mock_metrics,
        _mock_inverse,
    ):
        lookback = 5
        n_features = 3
        n_train = 60
        n_test = 40

        mock_prepare.return_value = {
            "X_train": np.zeros((n_train, lookback, n_features), dtype=np.float32),
            "y_train": np.linspace(1, 2, n_train).astype(np.float32),
            "X_test": np.zeros((n_test, lookback, n_features), dtype=np.float32),
            "y_test": np.linspace(2, 3, n_test).astype(np.float32),
            "close_scaler": {"mode": "minmax", "min": 0.0, "max": 1.0},
        }

        seen_fold_sizes = []

        def fake_train_model(**kwargs):
            seen_fold_sizes.append((len(kwargs["X_train"]), len(kwargs["X_test"])))
            return {"train_loss": [1.0], "val_loss": [1.0], "lr": [1e-3]}

        with patch("walk_forward_validation.train_model", side_effect=fake_train_model):
            summary = run_walk_forward(
                ticker="BTC-USD",
                model_type="lstm",
                activation="relu",
                lookback=lookback,
                epochs=1,
                source="yahoo",
                period="1y",
                interval="1d",
                normalization="minmax",
                train_ratio=0.5,
                test_ratio=0.2,
                step_ratio=0.1,
                min_train_size=10,
                min_test_size=10,
                min_step_size=5,
                fee_bps=1.0,
                slippage_bps=1.0,
                spread_bps=1.0,
                latency_bps=0.5,
                funding_bps=0.1,
                borrow_bps=0.1,
            )

        self.assertTrue(seen_fold_sizes)
        self.assertEqual(seen_fold_sizes[0], (50, 20))
        self.assertIn("avg_rmse", summary)
        self.assertIn("production_ready", summary)


if __name__ == "__main__":
    unittest.main()
