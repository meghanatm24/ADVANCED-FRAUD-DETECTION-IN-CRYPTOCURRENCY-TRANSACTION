import os, time
from pathlib import Path
from typing import List, Dict, Any

import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from db import Base, engine
from models import User
from routers.auth import router as auth_router


from fastapi.responses import StreamingResponse, JSONResponse, PlainTextResponse, Response
from io import BytesIO
import csv

# multi-chain tx fetcher
from services.blockchain import get_normal_tx_chain

# feature/model helpers
from services.features import tx_to_features
from services.model import load_trained_model, LazyIF

# Optional: for /debug/etherscan (remove if not needed)
from services.adapters.ethereum import get_eth_normal_tx

from fastapi import Body
from datetime import datetime, timedelta
from collections import defaultdict

# -------------------
# Env & App bootstrap
# -------------------
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")
print("Loaded key?", bool(os.getenv("ETHERSCAN_API_KEY")), "Value prefix:", str(os.getenv("ETHERSCAN_API_KEY") or "")[:5])

app = FastAPI(title="Crypto Fraud Detection API (Combined)", version="3.0.0")

origins = [os.getenv("ALLOWED_ORIGIN", "http://localhost:8080")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)
app.include_router(auth_router)

# --------------
# Model loading
# --------------
TRAINED = load_trained_model()
IFALLBACK = LazyIF()

# ----------
# Utilities
# ----------
def _recent_window(all_tx: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return all_tx[:200] if len(all_tx) > 200 else all_tx

def _score_with_model(feats: list[float]) -> float:
    """Return risk score 0..100."""
    if TRAINED is not None:
        try:
            X = np.array(feats, dtype=float).reshape(1, -1)
            if hasattr(TRAINED, "predict_proba"):
                proba = TRAINED.predict_proba(X)[0]
                return float(proba[-1] * 100.0)
            elif hasattr(TRAINED, "decision_function"):
                raw = float(TRAINED.decision_function(X)[0])
                # normalize -3..3 to 0..1
                norm = (raw - (-3.0)) / (3.0 - (-3.0))
                norm = max(0.0, min(1.0, norm))
                return float(norm * 100.0)
        except Exception:
            pass
    return IFALLBACK.score(feats)

def _score_tx(tx: Dict[str, Any], window: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build API-ready transaction record with risk metrics.

    ETH adapter provides 'value' (wei), BTC adapter sets '_value_btc' (in BTC).
    """
    feats = tx_to_features(tx, window)
    risk = _score_with_model(feats)

    if risk >= 75:
        label = "high"
    elif risk >= 45:
        label = "medium"
    else:
        label = "low"

    # value display: prefer BTC if provided
    if "_value_btc" in tx:
        value_display = float(tx.get("_value_btc") or 0.0)  # BTC in BTC
    else:
        # ETH in ETH (value is wei)
        value_display = int(tx.get("value", "0") or 0) / 1e18

    # some chains may not have gasPrice (BTC)
    gas_gwei = 0.0
    if tx.get("gasPrice"):
        try:
            gas_gwei = int(tx.get("gasPrice") or 0) / 1e9
        except Exception:
            gas_gwei = 0.0

    # timeStamp normalized to int (seconds)
    ts = 0
    try:
        ts = int(tx.get("timeStamp", 0) or 0)
    except Exception:
        ts = 0

    return {
        "txHash": tx.get("hash", ""),
        "from": tx.get("from", ""),
        "to": tx.get("to", ""),
        "value": value_display,          # ETH or BTC (native)
        "timeStamp": ts,
        "riskScore": round(risk, 2),
        "riskLevel": label,
        "gasPriceGwei": gas_gwei,
        "isMixerInvolved": False,
    }

# ------
# Routes
# ------
@app.get("/health")
def health():
    return {"ok": True, "trained_model": bool(TRAINED)}

# Backward-compat: ETH default
@app.get("/api/analyze/{address}")
def analyze_eth_default(address: str, page: int = 1, offset: int = 50):
    return analyze_chain("eth", address, page, offset)

@app.get("/api/analyze/{chain}/{address}")
def analyze_chain(chain: str, address: str, page: int = 1, offset: int = 50):
    try:
        all_tx = get_normal_tx_chain(chain, address, page=page, offset=offset)
        if not all_tx:
            return {"count": 0, "items": []}
        window = _recent_window(all_tx)
        scored = [_score_tx(t, window) for t in all_tx]
        return {"count": len(scored), "items": scored}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Optional debug route for ETH only (remove if you don't need it)
@app.get("/debug/etherscan")
def debug_etherscan(address: str = Query(..., description="ETH address")):
    try:
        items = get_eth_normal_tx(address, page=1, offset=3)
        return {"ok": True, "items": items}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/reports/monthly")
def monthly(chain: str, address: str, months: int = 6):
    # fetch recent tx (you can increase offset if you want more coverage)
    tx = get_normal_tx_chain(chain, address, page=1, offset=500)
    # bucket by month name
    buckets = defaultdict(lambda: {"transactions": 0, "fraudDetected": 0, "falsePositives": 0})
    for t in tx:
        ts = int(t.get("timeStamp", 0) or 0)
        if not ts: continue
        m = datetime.utcfromtimestamp(ts).strftime("%b")
        buckets[m]["transactions"] += 1
        # classify risk using same scoring
        feats = tx_to_features(t, tx[:200])
        score = _score_with_model(feats)
        if score >= 80:
            buckets[m]["fraudDetected"] += 1
        # naive FP proxy (medium-risk treated as potential FP in demo)
        if 50 <= score < 80:
            buckets[m]["falsePositives"] += 1

    # last N months in calendar order
    now = datetime.utcnow().replace(day=15)  # neutralize end-of-month variance
    order = []
    cur = now
    for _ in range(months):
        order.append(cur.strftime("%b"))
        # go to previous month
        cur = (cur.replace(day=1) - timedelta(days=1)).replace(day=15)
    order.reverse()

    points = []
    for m in order:
        b = buckets[m]
        points.append({
            "month": m,
            "transactions": b["transactions"],
            "fraudDetected": b["fraudDetected"],
            "falsePositives": b["falsePositives"],
        })
    return {"points": points}

@app.get("/api/reports/quick-stats")
def quick_stats(chain: str, address: str):
    tx = get_normal_tx_chain(chain, address, page=1, offset=200)
    if not tx:
        return {
            "detectionRatePct": 0.0,
            "falsePositivePct": 0.0,
            "responseP95Ms": 2000,
            "criticalCount": 0,
            "activeCount": 0,
            "resolvedToday": 0,
        }

    window = _recent_window(tx)
    scores = []
    critical = active = resolved_today = 0
    medium = 0
    today = datetime.utcnow().date()
    for t in tx:
        s = _score_with_model(tx_to_features(t, window))
        scores.append(s)
        if s >= 80:
            critical += 1
            active += 1
        elif 50 <= s < 80:
            medium += 1
            active += 1
        # resolved: simple heuristic — older than 24h and <50
        ts = int(t.get("timeStamp", 0) or 0)
        if ts and s < 50:
            dt = datetime.utcfromtimestamp(ts).date()
            if dt == today:
                resolved_today += 1

    total = len(tx)
    fraud = sum(1 for s in scores if s >= 80)
    detection_rate = (fraud / total) * 100.0 if total else 0.0
    false_positive = (medium / total) * 100.0 if total else 0.0

    return {
        "detectionRatePct": round(detection_rate, 1),
        "falsePositivePct": round(false_positive, 1),
        "responseP95Ms": 1800,  # static demo value; plug real p95 if you collect timings
        "criticalCount": critical,
        "activeCount": active,
        "resolvedToday": resolved_today,
    }

@app.get("/api/reports/templates")
def templates():
    # return a few canned templates; attach downloadUrl if you have pre-rendered files
    return {
        "templates": [
            {
                "id": "fraud-summary",
                "name": "Fraud Detection Summary",
                "description": "Comprehensive overview of fraud detection activities",
                "type": "summary",
                "icon": "Shield",
                "lastGenerated": datetime.utcnow().date().isoformat(),
                "size": "2.1 MB",
            },
            {
                "id": "transaction-analysis",
                "name": "Transaction Analysis Report",
                "description": "Detailed analysis of transaction patterns and risks",
                "type": "analysis",
                "icon": "BarChart3",
                "lastGenerated": datetime.utcnow().date().isoformat(),
                "size": "4.2 MB",
            },
            {
                "id": "risk-assessment",
                "name": "Risk Assessment Report",
                "description": "Risk level breakdown and trend analysis",
                "type": "assessment",
                "icon": "TrendingUp",
                "lastGenerated": datetime.utcnow().date().isoformat(),
                "size": "1.8 MB",
            },
            {
                "id": "compliance-audit",
                "name": "Compliance Audit Report",
                "description": "Regulatory compliance and audit trail documentation",
                "type": "compliance",
                "icon": "FileText",
                "lastGenerated": datetime.utcnow().date().isoformat(),
                "size": "3.0 MB",
            },
        ]
    }

class GenerateBody(BaseModel):
    from_: str | None = None
    to: str | None = None
    reportType: str
    format: str
    chain: str
    address: str | None = None

@app.post("/api/reports/generate")
def generate_report(payload: dict = Body(...)):
    # Accept either {from: "..."} or {from_: "..."} from FE
    from_str = payload.get("from") or payload.get("from_")
    to_str = payload.get("to")
    # You can perform real generation here (PDF/CSV/etc.)
    # For demo, pretend it's ready and return download URL.
    report_id = f"rep_{int(time.time())}"
    url = f"/api/reports/download/{report_id}"
    return {"reportId": report_id, "status": "ready", "downloadUrl": url}

@app.get("/api/reports/download/{report_id}")
def download_report(report_id: str):
    # Return a simple JSON file or stream a PDF in real impl.
    from fastapi.responses import JSONResponse
    data = {"reportId": report_id, "generatedAt": datetime.utcnow().isoformat()}
    return JSONResponse(data, media_type="application/json")