"""
Adapter Pemanggilan LLM (Google Gemini via `google-genai`) dengan Structured Output.

Mengisolasi panggilan jaringan eksternal, timeout, retry terbatas + fallback model
otomatis untuk error 5xx transien (`503 UNAVAILABLE` high demand), dan error upstream
agar tidak pernah membocorkan API key maupun stack trace ke respons HTTP.
"""

import asyncio
import json
import logging
import re
from collections.abc import Sequence
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel

from .config import LearningSummarySettings, get_learning_summary_settings
from .prompt_builder import SYSTEM_PROMPT, build_user_prompt
from .schemas import LearningSummaryRequest, LLMOutputSchema

logger = logging.getLogger(__name__)

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_PER_MODEL_RETRY_DELAYS = (0.5,)


class LLMNotConfiguredError(RuntimeError):
    """Dilempar bila provider/API key LLM belum dikonfigurasi pada environment server."""


class LLMTimeoutError(RuntimeError):
    """Dilempar bila permintaan ke LLM melebihi batas waktu konfigurasi."""


class LLMProviderError(RuntimeError):
    """Dilempar bila terjadi kegagalan komunikasi atau respons tidak valid dari LLM."""


def _extract_json_dict(response: Any) -> dict[str, Any]:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, BaseModel):
        return parsed.model_dump()
    if isinstance(parsed, dict):
        return parsed

    raw_text = getattr(response, "text", None)
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise LLMProviderError("Respons LLM kosong")

    cleaned_text = _CODE_FENCE_RE.sub("", raw_text.strip()).strip()
    try:
        data = json.loads(cleaned_text)
    except json.JSONDecodeError as exc:
        raise LLMProviderError("Respons LLM tidak berupa JSON valid") from exc

    if not isinstance(data, dict):
        raise LLMProviderError("Respons JSON LLM bukan objek")
    return data


def _parse_thinking_level(raw_level: str | None) -> types.ThinkingLevel | None:
    if not raw_level:
        return None
    normalized = raw_level.strip().upper()
    level = types.ThinkingLevel.__members__.get(normalized)
    if level is None:
        logger.warning(
            "LEARNING_SUMMARY_THINKING_LEVEL=%r tidak valid; menggunakan default model",
            raw_level,
        )
    return level


def _build_gemini_config(
    settings: LearningSummarySettings,
) -> types.GenerateContentConfig:
    thinking_level = _parse_thinking_level(settings.thinking_level)
    thinking_config = (
        types.ThinkingConfig(thinking_level=thinking_level)
        if thinking_level is not None
        else None
    )
    return types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        temperature=settings.temperature,
        max_output_tokens=settings.max_output_tokens,
        response_mime_type="application/json",
        response_schema=LLMOutputSchema,
        thinking_config=thinking_config,
    )


async def _generate_with_retry_and_fallback(
    client: genai.Client,
    models: Sequence[str],
    user_prompt: str,
    gen_config: types.GenerateContentConfig,
    scope: str,
) -> tuple[Any, str]:
    """
    Mencoba model utama terlebih dahulu (dengan retry singkat untuk error 5xx transien),
    lalu otomatis beralih ke `fallback_models` bila model utama sedang 503 high demand
    atau tidak tersedia (404). Seluruh rantai dibatasi total deadline `asyncio.wait_for`.
    """
    max_attempts = 1 + len(_PER_MODEL_RETRY_DELAYS)
    last_error: Exception | None = None

    async with client.aio as async_client:
        for model_index, model_name in enumerate(models):
            has_next_model = model_index < len(models) - 1
            for attempt in range(1, max_attempts + 1):
                try:
                    response = await async_client.models.generate_content(
                        model=model_name,
                        contents=user_prompt,
                        config=gen_config,
                    )
                    return response, model_name
                except genai_errors.ServerError as exc:
                    last_error = exc
                    status_code = getattr(exc, "code", None)
                    if attempt < max_attempts:
                        delay = _PER_MODEL_RETRY_DELAYS[attempt - 1]
                        logger.warning(
                            "Error 5xx transien dari LLM (code=%s, attempt=%d/%d, model=%s, scope=%s); "
                            "mencoba ulang dalam %.1fs",
                            status_code,
                            attempt,
                            max_attempts,
                            model_name,
                            scope,
                            delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    if has_next_model:
                        next_model = models[model_index + 1]
                        logger.warning(
                            "Model %s gagal (code=%s, scope=%s); beralih ke fallback model %s",
                            model_name,
                            status_code,
                            scope,
                            next_model,
                        )
                        break
                    raise
                except genai_errors.ClientError as exc:
                    status_code = getattr(exc, "code", None)
                    if status_code == 404 and has_next_model:
                        last_error = exc
                        next_model = models[model_index + 1]
                        logger.warning(
                            "Model %s tidak tersedia (code=404, scope=%s); beralih ke fallback model %s",
                            model_name,
                            scope,
                            next_model,
                        )
                        break
                    raise

    if last_error is not None:
        raise last_error
    raise LLMProviderError("Tidak ada model LLM yang tersedia")


async def summarize_with_llm(
    payload: LearningSummaryRequest,
    allowed_subjects: Sequence[str] | None = None,
    settings: LearningSummarySettings | None = None,
) -> tuple[dict[str, Any], str]:
    """
    Memanggil model Gemini secara async dengan batas waktu total `settings.timeout_seconds`.
    Mengembalikan tuple `(raw_output_dict, model_name_used)`.
    """
    cfg = settings or get_learning_summary_settings()

    if cfg.provider != "gemini":
        raise LLMNotConfiguredError(f"LLM_PROVIDER '{cfg.provider}' belum didukung")
    if not cfg.is_configured:
        raise LLMNotConfiguredError("GEMINI_API_KEY belum dikonfigurasi")

    user_prompt = build_user_prompt(payload, allowed_subjects=allowed_subjects)
    gen_config = _build_gemini_config(cfg)

    client = genai.Client(api_key=cfg.gemini_api_key)
    try:
        response, model_used = await asyncio.wait_for(
            _generate_with_retry_and_fallback(
                client=client,
                models=cfg.candidate_models,
                user_prompt=user_prompt,
                gen_config=gen_config,
                scope=payload.scope,
            ),
            timeout=cfg.timeout_seconds,
        )
    except (asyncio.TimeoutError, TimeoutError) as exc:
        logger.warning(
            "Permintaan LLM timeout setelah %.1f detik (models=%s, scope=%s)",
            cfg.timeout_seconds,
            ",".join(cfg.candidate_models),
            payload.scope,
        )
        raise LLMTimeoutError("Layanan LLM melebihi batas waktu") from exc
    except Exception as exc:
        # Log hanya nama kelas error dan HTTP code (tanpa repr lengkap yang berisiko membawa key)
        logger.error(
            "Gagal memanggil provider LLM (type=%s, code=%s, models=%s, scope=%s)",
            type(exc).__name__,
            getattr(exc, "code", None),
            ",".join(cfg.candidate_models),
            payload.scope,
        )
        raise LLMProviderError("Gagal memanggil layanan LLM") from exc

    raw_output = _extract_json_dict(response)
    return raw_output, model_used
