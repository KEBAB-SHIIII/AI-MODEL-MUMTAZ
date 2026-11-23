"""
Entrypoint Utama Layanan FastAPI Mumtaz Bimbel:
1. `POST /v1/anomaly/analyze`          : Deteksi Anomali Absen Tutor (LightGBM + Guardrail).
2. `POST /v1/learning-summary/summarize`: Ringkasan Belajar Orang Tua (Generative AI Gemini).

Alur eksekusi endpoint anomaly `POST /v1/anomaly/analyze`:
1. Tahap 1 (schemas.py)           : Validasi JSON request dari Backend (`HttpAnomalyDetector`).
2. Tahap 2 (feature_extractor.py) : Ubah JSON (target, comparisons, config) -> 19 fitur angka.
3. Tahap 3 (anomaly_model.pkl)    : Prediksi status awal menggunakan model LightGBM.
4. Tahap 4 (guardrail.py)         : Guardrail deterministik untuk akurasi 100% di titik batas.
5. Tahap 5 (response_builder.py)  : Susun response JSON `{ validity, validity_reason, findings }`.
"""

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException

from .feature_extractor import FEATURE_NAMES, extract_features_and_meta
from .guardrail import apply_business_guardrail
from .learning_summary.config import get_learning_summary_settings
from .learning_summary.router import router as learning_summary_router
from .response_builder import build_analyze_response
from .schemas import AnalyzeRequest, AnalyzeResponse, HealthResponse

# Lokasi folder artefak model ML (relatif terhadap root proyek C:\AI-MODEL-MUMTAZ)
BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_PATH = BASE_DIR / "artifacts" / "anomaly_model.pkl"
METADATA_PATH = BASE_DIR / "artifacts" / "feature_metadata.json"

# Penyimpanan model di memori agar hanya di-load 1 kali saat server menyala
ml_state: dict[str, Any] = {
    "model": None,
    "metadata": None,
}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """
    Lifecycle handler FastAPI:
    Memuat `anomaly_model.pkl` dan `feature_metadata.json` ke RAM satu kali saat startup,
    lalu membersihkannya saat server dimatikan.
    """
    if not MODEL_PATH.exists():
        raise RuntimeError(
            f"File model ML tidak ditemukan di: {MODEL_PATH}. "
            "Pastikan anomaly_model.pkl sudah disalin ke folder artifacts/."
        )

    ml_state["model"] = joblib.load(MODEL_PATH)
    if METADATA_PATH.exists():
        ml_state["metadata"] = json.loads(METADATA_PATH.read_text(encoding="utf-8"))

    yield
    ml_state.clear()


app = FastAPI(
    title="Mumtaz Bimbel - AI Service (Anomaly Detection & Learning Summary)",
    description=(
        "Layanan AI FastAPI Mumtaz Bimbel: deteksi anomali absensi tutor (LightGBM + Guardrail) "
        "dan ringkasan perkembangan belajar orang tua berbasis Generative AI."
    ),
    version="1.1.0",
    lifespan=lifespan,
)

app.include_router(learning_summary_router)


@app.get("/", tags=["Info"])
def root():
    """Endpoint informasi dasar layanan & link dokumentasi Swagger."""
    return {
        "service": "Mumtaz Bimbel AI Service",
        "health_endpoint": "/health",
        "analyze_endpoint": "/v1/anomaly/analyze",
        "learning_summary_endpoint": "/v1/learning-summary/summarize",
        "docs": "/docs",
    }


@app.get("/health", response_model=HealthResponse, tags=["Health"])
def health_check() -> HealthResponse:
    """
    Endpoint untuk memastikan server FastAPI hidup dan model ML sudah termuat di memori.
    Tidak memanggil API LLM eksternal agar healthcheck selalu cepat dan gratis.
    """
    model_loaded = ml_state.get("model") is not None
    metadata = ml_state.get("metadata") or {}
    summary_settings = get_learning_summary_settings()
    return HealthResponse(
        status="ok" if model_loaded else "degraded",
        model_loaded=model_loaded,
        model_name=str(metadata.get("model_name", "LightGBM")),
        feature_count=len(FEATURE_NAMES),
        learning_summary_configured=summary_settings.is_configured,
    )


@app.post(
    "/v1/anomaly/analyze", response_model=AnalyzeResponse, tags=["Anomaly Detection"]
)
def analyze_anomaly(payload: AnalyzeRequest) -> AnalyzeResponse:
    """
    Endpoint utama yang dipanggil oleh `HttpAnomalyDetector` di Backend Node.js
    setiap kali tutor mengirim (submit) atau merevisi absensi sesi les.
    """
    model = ml_state.get("model")
    if model is None:
        raise HTTPException(status_code=503, detail="Model ML belum siap di memori.")

    # Tahap 2: Ekstraksi 19 fitur numerik + helper_meta dari JSON Backend
    features, helper_meta = extract_features_and_meta(
        target=payload.target,
        comparisons=payload.comparisons,
        config=payload.config,
    )

    # Tahap 3: Susun DataFrame 1 baris sesuai urutan baku FEATURE_NAMES lalu prediksi dg LightGBM
    row_df = pd.DataFrame(
        [[features[col] for col in FEATURE_NAMES]], columns=FEATURE_NAMES
    )
    raw_prediction = str(model.predict(row_df)[0])

    # Tahap 4: Terapkan Guardrail deterministik untuk memastikan akurasi 100% di garis batas
    final_validity = apply_business_guardrail(raw_prediction, features)

    # Tahap 5: Bangun response JSON (validity, validity_reason, findings Bahasa Indonesia)
    return build_analyze_response(
        target=payload.target,
        config=payload.config,
        features=features,
        helper_meta=helper_meta,
        final_validity=final_validity,
    )
