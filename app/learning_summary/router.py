"""Router FastAPI untuk Endpoint `POST /v1/learning-summary/summarize`."""

import logging

from fastapi import APIRouter, HTTPException

from .llm_client import (
    LLMNotConfiguredError,
    LLMProviderError,
    LLMTimeoutError,
    summarize_with_llm,
)
from .postprocessor import extract_allowed_subjects, sanitize_llm_output
from .schemas import LearningSummaryRequest, LearningSummaryResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/learning-summary", tags=["Learning Summary"])


@router.post("/summarize", response_model=LearningSummaryResponse)
async def summarize_learning(
    payload: LearningSummaryRequest,
) -> LearningSummaryResponse:
    """
    Meringkas perkembangan belajar anak untuk Orang Tua (`scope: "session"` atau `"monthly"`).
    Dipanggil secara stateless oleh Backend Dashboard (`HttpLearningSummaryProvider`).
    """
    allowed_subjects = extract_allowed_subjects(payload.sessions)
    try:
        raw_output, model_used = await summarize_with_llm(
            payload, allowed_subjects=allowed_subjects
        )
        return sanitize_llm_output(
            raw_output,
            allowed_subjects=allowed_subjects,
            model_name=model_used,
        )
    except LLMNotConfiguredError as exc:
        logger.warning(
            "Endpoint learning-summary dipanggil namun belum terkonfigurasi."
        )
        raise HTTPException(
            status_code=503,
            detail="Layanan ringkasan belajar AI belum dikonfigurasi",
        ) from exc
    except LLMTimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail="Layanan LLM melebihi batas waktu",
        ) from exc
    except (LLMProviderError, ValueError) as exc:
        logger.warning(
            "Gagal memproses output ringkasan belajar (type=%s)", type(exc).__name__
        )
        raise HTTPException(
            status_code=502,
            detail="Gagal menghasilkan ringkasan belajar",
        ) from exc
