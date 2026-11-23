"""
Post-Processor & Guardrail Deterministik untuk Output Generative AI.

Memastikan output mentah dari LLM selalu dibersihkan, dibatasi panjangnya,
bebas key liar (seperti `parent_tips`), dan 100% lolos kontrak ketat
`LearningSummaryResponse` sebelum dikembalikan ke Backend Dashboard.
"""

from collections.abc import Sequence
from typing import cast

from .schemas import (
    LearningSummaryResponse,
    LearningSummarySessionInput,
    OverallStatus,
    SubjectHighlight,
)

VALID_OVERALL_STATUSES: tuple[OverallStatus, ...] = (
    "very_good",
    "good",
    "needs_attention",
)


def extract_allowed_subjects(
    sessions: Sequence[LearningSummarySessionInput],
) -> list[str]:
    """Mengambil daftar mata pelajaran unik dari input sesi dalam urutan stabil."""
    result: list[str] = []
    seen: set[str] = set()
    for session in sessions:
        for subject in session.subjects:
            cleaned = " ".join(subject.strip().split())
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(cleaned)
    return result


def _truncate(text: str, max_len: int) -> str:
    cleaned = " ".join(text.strip().split())
    if len(cleaned) <= max_len:
        return cleaned
    if max_len <= 1:
        return cleaned[:max_len]
    return cleaned[: max_len - 1].rstrip() + "…"


def _clean_string_list(items: object, max_items: int, max_len: int) -> list[str]:
    if not isinstance(items, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, str):
            continue
        cleaned = _truncate(raw, max_len)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
        if len(result) >= max_items:
            break
    return result


def sanitize_llm_output(
    raw: object,
    allowed_subjects: Sequence[str] | None = None,
    model_name: str | None = None,
) -> LearningSummaryResponse:
    """
    Membersihkan dan memvalidasi output mentah LLM agar 100% sesuai kontrak strict:
    - Whitelist field (otomatis membuang key liar seperti `parent_tips`).
    - Validasi enum `overall_status` & `summary` tidak kosong.
    - Deduplikasi & pemotongan aman sesuai batas karakter & jumlah item Zod.
    - Normalisasi `subjects_covered` agar hanya memuat mata pelajaran valid dari input.
    """
    if not isinstance(raw, dict):
        raise ValueError("Output LLM bukan objek JSON (dict)")

    raw_status = raw.get("overall_status")
    if isinstance(raw_status, str):
        raw_status = raw_status.strip()
    if raw_status not in VALID_OVERALL_STATUSES:
        raise ValueError(f"overall_status tidak valid: {raw_status!r}")
    overall_status = cast(OverallStatus, raw_status)

    raw_summary = raw.get("summary")
    if not isinstance(raw_summary, str) or not raw_summary.strip():
        raise ValueError("summary kosong dari LLM")
    summary = _truncate(raw_summary, 1000)

    strengths = _clean_string_list(raw.get("strengths"), max_items=5, max_len=240)
    areas_to_improve = _clean_string_list(
        raw.get("areas_to_improve"), max_items=5, max_len=240
    )

    canonical_subject_map: dict[str, str] = {}
    if allowed_subjects:
        for subject in allowed_subjects:
            cleaned_subject = _truncate(subject, 80)
            if cleaned_subject:
                canonical_subject_map[cleaned_subject.lower()] = cleaned_subject

    subjects_covered: list[SubjectHighlight] = []
    seen_subjects: set[str] = set()
    raw_subjects = raw.get("subjects_covered")
    if isinstance(raw_subjects, list):
        for entry in raw_subjects:
            if not isinstance(entry, dict):
                continue
            name = entry.get("subject_name")
            highlight = entry.get("highlight")
            if not isinstance(name, str) or not isinstance(highlight, str):
                continue
            clean_name = _truncate(name, 80)
            clean_highlight = _truncate(highlight, 240)
            if not clean_name or not clean_highlight:
                continue

            key = clean_name.lower()
            if canonical_subject_map:
                if key not in canonical_subject_map:
                    # Buang mata pelajaran halusinasi yang tidak ada pada input sesi
                    continue
                clean_name = canonical_subject_map[key]

            if key in seen_subjects:
                continue
            seen_subjects.add(key)
            subjects_covered.append(
                SubjectHighlight(subject_name=clean_name, highlight=clean_highlight)
            )
            if len(subjects_covered) >= 15:
                break

    clean_model = (
        _truncate(model_name, 80) if model_name and model_name.strip() else None
    )

    return LearningSummaryResponse(
        overall_status=overall_status,
        summary=summary,
        strengths=strengths,
        areas_to_improve=areas_to_improve,
        subjects_covered=subjects_covered,
        model=clean_model,
    )
