# Crypto Fraud Detection — Combined (Backend + Pretrained ML)

This bundle contains:
- FastAPI backend (`app.py`) with endpoints:
  - `GET /health`
  - `GET /api/analyze/{address}`
- A **pretrained supervised model** at `ml/model.joblib` (trained on synthetic data)
- Scripts to regenerate data & retrain: `ml/generate_synthetic.py`, `ml/train_model.py`

## Run (local)
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# set ETHERSCAN_API_KEY and ALLOWED_ORIGIN (e.g., http://localhost:8080)
uvicorn app:app --reload --port 8000
```

Test:
- http://localhost:8000/health
- http://localhost:8000/api/analyze/0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045

## Retrain (optional)
```bash
python ml/generate_synthetic.py
python ml/train_model.py
```
This overwrites `ml/model.joblib`, which the API will auto-load.


<!-- ETH: 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045 -->
<!-- ETH: 0x742d35Cc6634C0532925a3b844Bc454e4438f44e -->
<!-- BTC: bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh -->
<!-- ETH: 0x53d284357ec70ce289d6d64134dfac8e511c8a3d -->

<!-- argon database using sqlite -->
