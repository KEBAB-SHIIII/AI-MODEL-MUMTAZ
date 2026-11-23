"""
Skema Pydantic v2 untuk Endpoint Generative AI Ringkasan Belajar Orang Tua.

Kontrak Request & Response di sini diselaraskan 100% dengan Zod strict schema
di `@mumtaz/contracts` (`packages/contracts/src/learning-summary.ts`).
"""

from datetime import date
from typing import Annotated, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

SummaryScope = Literal["session", "monthly"]
OverallStatus = Literal["very_good", "good", "needs_attention"]

BoundedBulletItem = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=240),
]


# ==============================================================================
# Skema Request (Backend Dashboard -> FastAPI) — Zero-PII & extra="forbid"
# ==============================================================================


class LearningSummarySessionInput(BaseModel):
    """Satu sesi belajar `approved` (tanpa PII: tanpa nama murid/tutor/sekolah/UUID)."""

    model_config = ConfigDict(extra="forbid")

    lesson_date: date
    subjects: list[str] = Field(min_length=1, max_length=5)
    duration_minutes: int = Field(gt=0)
    learning_material: str = Field(min_length=1)
    learning_notes: Optional[str] = None

    @field_validator("subjects")
    @classmethod
    def validate_subjects(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in values:
            trimmed = item.strip()
            if not trimmed or len(trimmed) > 80:
                raise ValueError("Setiap nama mata pelajaran harus 1..80 karakter")
            cleaned.append(trimmed)
        return cleaned

    @field_validator("learning_material")
    @classmethod
    def strip_learning_material(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("learning_material tidak boleh kosong")
        return trimmed

    @field_validator("learning_notes")
    @classmethod
    def normalize_learning_notes(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed if trimmed else None


class LearningSummaryRequest(BaseModel):
    """Payload utama `POST /v1/learning-summary/summarize`."""

    model_config = ConfigDict(extra="forbid")

    scope: SummaryScope
    period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    student_grade: str = Field(min_length=1, max_length=60)
    sessions: list[LearningSummarySessionInput] = Field(min_length=1, max_length=100)

    @field_validator("student_grade")
    @classmethod
    def strip_grade(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed or len(trimmed) > 60:
            raise ValueError("student_grade harus 1..60 karakter")
        return trimmed

    @model_validator(mode="after")
    def validate_scope_session_count(self) -> "LearningSummaryRequest":
        if self.scope == "session" and len(self.sessions) != 1:
            raise ValueError("Scope 'session' wajib mengirim tepat 1 sesi")
        return self


# ==============================================================================
# Skema Structured Output untuk LLM (tanpa `extra="forbid"` agar kompatibel SDK)
# ==============================================================================


class LLMSubjectHighlight(BaseModel):
    """Schema ringkas per mata pelajaran untuk Structured Output LLM."""

    subject_name: str
    highlight: str


class LLMOutputSchema(BaseModel):
    """
    Schema polos yang dikirim ke `response_schema` LLM (tanpa field `model`,
    karena `model` diisi deterministik oleh server dari konfigurasi).
    """

    overall_status: OverallStatus
    summary: str
    strengths: list[str]
    areas_to_improve: list[str]
    subjects_covered: list[LLMSubjectHighlight]


# ==============================================================================
# Skema Response Final (FastAPI -> Backend Dashboard) — Strict 100% Zod Match
# ==============================================================================


class SubjectHighlight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
    ]
    highlight: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)
    ]


class LearningSummaryResponse(BaseModel):
    """Payload balasan HTTP 200 yang wajib lolos `z.strictObject` di Backend."""

    model_config = ConfigDict(extra="forbid")

    overall_status: OverallStatus
    summary: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
    ]
    strengths: list[BoundedBulletItem] = Field(default_factory=list, max_length=5)
    areas_to_improve: list[BoundedBulletItem] = Field(
        default_factory=list, max_length=5
    )
    subjects_covered: list[SubjectHighlight] = Field(
        default_factory=list, max_length=15
    )
    model: Optional[
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
        ]
    ] = None
