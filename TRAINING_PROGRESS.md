# Training Progress Monitor

Training started at: 2026-03-21 (current session)

## Active Training

**Model:** GRU (Gated Recurrent Unit)
- Simpler than LSTM (fewer parameters → less overfitting)
- Expected training time: 30-60 minutes

**Configuration:**
- Ticker: AAPL (Apple Inc.)
- Data Period: 5 years (~1,250 trading days)
- Lookback: 20 days
- Epochs: 50 per fold
- Folds: ~5-6 (walk-forward validation)

**Improvements over LSTM:**
- ✅ GRU parameters: ~12K vs LSTM: 214K (18x simpler)
- ✅ Training data: 1,250 samples vs LSTM: 500 samples (2.5x more)
- ✅ Lookback: 20 vs LSTM: 60 days (simpler patterns)

---

## Expected Results

**Good outcome (likely):**
- R² = -50 to 0 (still negative, but smaller than -380)
- MAPE = 10-20% (worse than ideal but better than 79%)
- Model may be suitable for ensemble voting

**Best outcome (possible):**
- R² = 0.10-0.30 (small positive signal!)
- MAPE = 3-7%
- Model becomes production-ready

---

## What Happens After Training Completes

1. **Results saved to:** `output/training_summary.json`
2. **Models saved to:** Multiple fold checkpoints
3. **Validation metrics:** RMSE, MAPE, R² per fold
4. **Next step:** Compare to LSTM results

---

## If GRU Succeeds

→ Train ensemble (LSTM + GRU + HybridNet)
→ Deploy to paper trading
→ Monitor webhook.site for alerts
→ Validate production gates work

## If GRU Also Fails

→ Try return-based models (predict returns, not prices)
→ Increase training data (5+ tickers)
→ Use multi-asset ensemble voting
→ Consider alternative architectures

---

Status: ⏳ TRAINING IN PROGRESS (Session 5)
