"""
Tahap 1: Skema Kontrak Data (Request & Response) untuk Layanan FastAPI.

File ini mendefinisikan struktur JSON yang diterima dari Backend Node.js
(`HttpAnomalyDetector`) dan struktur JSON yang dikembalikan oleh FastAPI.
Jika suatu saat ada perubahan field di kontrak `@mumtaz/contracts` (Backend),
cukup sesuaikan kelas-kelas Pydantic di file ini.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

# ==============================================================================
# Tipe Enum Baku (Wajib cocok 100% dengan schema Zod & PostgreSQL di Backend)
# ==============================================================================

# Status validitas akhir sesi absen (Urutan prioritas: rejected > needs_revision > valid)
SessionValidity = Literal["valid", "needs_revision", "rejected"]

# 4 kategori temuan yang tersedia di enum database PostgreSQL (tabel anomaly_flags)
FindingType = Literal[
    "suspected_duplicate",  # Duplikat 100% persis (rejected) atau duplikat samar (needs_revision)
    "duration_outlier",  # Durasi < batas minimal (30 mnt) atau > batas maksimal (180 mnt)
    "late_start",  # Jam mulai < batas pagi (07:00) atau > batas malam (21:00)
    "unusual_pattern",  # Jadwal bentrok / tumpang tindih (tutor, murid, atau diri sendiri)
]

FindingSeverity = Literal["low", "medium", "high"]
SuggestedAction = Literal["review"]


# ==============================================================================
# Skema Input (Dari Backend -> FastAPI)
# ==============================================================================


class SessionSnapshot(BaseModel):
    """
    Representasi 8 field publik dari satu sesi absen les.
    Data privat (materi belajar, catatan, dll.) sudah dibuang oleh Backend
    melalui `toPublicSnapshot()` sebelum dikirim ke sini.
    """

    id: str = Field(description="UUID unik sesi absen.")
    tutor_id: str = Field(description="UUID tutor pengajar.")
    student_id: str = Field(description="UUID murid.")
    subject_ids: list[str] = Field(
        min_length=1,
        max_length=5,
        description="Daftar UUID mata pelajaran yang diajarkan (1 sampai 5 mapel).",
    )
    lesson_date: str = Field(description="Tanggal sesi les dalam format YYYY-MM-DD.")
    start_time: Optional[str] = Field(
        default=None,
        description="Jam mulai sesi dalam format HH:MM (WIB), atau None untuk data lama.",
    )
    duration_minutes: int = Field(
        ge=1,
        description="Durasi mengajar dalam satuan menit (minimal 1 menit).",
    )
    submitted_at: str = Field(
        description="Waktu submit absen dalam format ISO-8601 UTC."
    )


class AnomalyConfig(BaseModel):
    """
    4 parameter ambang batas aturan bisnis yang dikirim dinamis dari `backend/.env`.
    Memungkinkan Admin mengubah batas tanpa perlu melatih ulang model ML.
    """

    durationOutlierMinutes: int = Field(
        default=180,
        ge=1,
        description="Batas maksimal durasi normal (menit). Default: 180 menit.",
    )
    durationMinMinutes: int = Field(
        default=30,
        ge=1,
        description="Batas minimal durasi normal (menit). Default: 30 menit.",
    )
    lateStartAfter: str = Field(
        default="21:00",
        description="Batas jam mulai paling malam (HH:MM). Default: 21:00.",
    )
    earlyStartBefore: str = Field(
        default="07:00",
        description="Batas jam mulai paling pagi (HH:MM). Default: 07:00.",
    )


class AnalyzeRequest(BaseModel):
    """Payload utama yang dikirim oleh Backend ke endpoint POST /v1/anomaly/analyze."""

    target: SessionSnapshot = Field(
        description="Sesi absen terbaru yang sedang diperiksa."
    )
    comparisons: list[SessionSnapshot] = Field(
        default_factory=list,
        max_length=500,
        description="Maksimal 500 sesi riwayat (+-30 hari) yang di-submit lebih dulu dari target.",
    )
    config: AnomalyConfig = Field(
        default_factory=AnomalyConfig,
        description="Konfigurasi ambang batas aturan bisnis dari Backend.",
    )


# ==============================================================================
# Skema Output (Dari FastAPI -> Backend)
# ==============================================================================


class FindingCandidate(BaseModel):
    """Detail 1 item temuan anomali yang akan disimpan Backend ke tabel `anomaly_flags`."""

    lesson_session_id: str
    related_lesson_session_id: Optional[str] = None
    is_anomaly: bool = True
    finding_type: FindingType
    severity: FindingSeverity
    reason: str = Field(min_length=1, max_length=600)
    evidence_summary: Optional[str] = Field(default=None, max_length=600)
    suggested_action: SuggestedAction = "review"


class AnalyzeResponse(BaseModel):
    """Payload balasan HTTP 200 dari FastAPI ke Backend."""

    validity: SessionValidity
    validity_reason: str = Field(min_length=1, max_length=600)
    findings: list[FindingCandidate]


class HealthResponse(BaseModel):
    """Payload respons untuk pengecekan kesehatan layanan (GET /health)."""

    status: Literal["ok", "degraded"]
    model_loaded: bool
    model_name: str
    feature_count: int
