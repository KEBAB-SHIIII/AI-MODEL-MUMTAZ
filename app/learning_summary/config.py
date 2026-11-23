"""
Konfigurasi Environment untuk Endpoint Generative AI Ringkasan Belajar.

Memuat `.env` di root proyek (jika ada) tanpa menimpa environment variable OS / Docker
yang sudah di-set lebih dulu (`override=False`).
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE_PATH = BASE_DIR / ".env"

# Muat .env lokal saat modul diimpor; env OS/Docker/test tetap menjadi prioritas utama
load_dotenv(dotenv_path=ENV_FILE_PATH, override=False)


def _parse_float_env(
    name: str, default: float, min_value: float, max_value: float
) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        parsed = float(raw.strip())
    except ValueError:
        return default
    return max(min_value, min(max_value, parsed))


def _parse_int_env(name: str, default: int, min_value: int, max_value: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        parsed = int(raw.strip())
    except ValueError:
        return default
    return max(min_value, min(max_value, parsed))


@dataclass(frozen=True)
class LearningSummarySettings:
    provider: str
    gemini_api_key: str
    model: str
    timeout_seconds: float
    temperature: float
    max_output_tokens: int
    thinking_level: str | None

    @property
    def is_configured(self) -> bool:
        if self.provider == "gemini":
            return bool(self.gemini_api_key)
        return False


def get_learning_summary_settings() -> LearningSummarySettings:
    """Membaca konfigurasi terbaru dari environment variables."""
    provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower() or "gemini"
    gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model = (
        os.getenv("LEARNING_SUMMARY_MODEL", "gemini-3.5-flash-lite").strip()
        or "gemini-3.5-flash-lite"
    )
    timeout_seconds = _parse_float_env(
        "LEARNING_SUMMARY_LLM_TIMEOUT_SECONDS",
        default=24.0,
        min_value=1.0,
        max_value=29.0,
    )
    temperature = _parse_float_env(
        "LEARNING_SUMMARY_TEMPERATURE",
        default=0.25,
        min_value=0.0,
        max_value=1.0,
    )
    max_output_tokens = _parse_int_env(
        "LEARNING_SUMMARY_MAX_OUTPUT_TOKENS",
        default=1536,
        min_value=256,
        max_value=4096,
    )
    raw_thinking = os.getenv("LEARNING_SUMMARY_THINKING_LEVEL", "").strip().upper()
    thinking_level = raw_thinking if raw_thinking else None

    return LearningSummarySettings(
        provider=provider,
        gemini_api_key=gemini_api_key,
        model=model,
        timeout_seconds=timeout_seconds,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        thinking_level=thinking_level,
    )
