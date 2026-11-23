"""
Pengujian Otomatis Endpoint Generative AI Ringkasan Belajar Orang Tua
(`POST /v1/learning-summary/summarize`).

Seluruh unit/API test ini berjalan 100% offline menggunakan mock LLM sehingga cepat,
deterministik, dan tidak menghabiskan kuota token Gemini.

Menjalankan seluruh test:
    .\\venv\\Scripts\\pytest.exe -v
"""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.learning_summary import router as learning_summary_router_module
from app.learning_summary.llm_client import (
    LLMNotConfiguredError,
    LLMProviderError,
    LLMTimeoutError,
)
from app.learning_summary.prompt_builder import build_user_prompt
from app.learning_summary.schemas import LearningSummaryRequest, LearningSummaryResponse
from app.main import app

SESSION_PAYLOAD = {
    "scope": "session",
    "period": "2026-10",
    "student_grade": "2 SD",
    "sessions": [
        {
            "lesson_date": "2026-10-01",
            "subjects": ["Matematika"],
            "duration_minutes": 90,
            "learning_material": "Penjumlahan dan pengurangan bilangan dua digit",
            "learning_notes": (
                "Siswa lancar mengerjakan soal penjumlahan bersusun dua digit tanpa bantuan. "
                "Pada pengurangan dengan teknik meminjam masih perlu didampingi perlahan."
            ),
        }
    ],
}

MONTHLY_PAYLOAD = {
    "scope": "monthly",
    "period": "2026-10",
    "student_grade": "5 SD",
    "sessions": [
        {
            "lesson_date": "2026-10-05",
            "subjects": ["IPA", "Matematika"],
            "duration_minutes": 90,
            "learning_material": "Pecahan campuran dan gaya gesek",
            "learning_notes": (
                "Siswa antusias berdiskusi tentang contoh gaya gesek sehari-hari dan cepat "
                "memahami penjumlahan pecahan campuran."
            ),
        },
        {
            "lesson_date": "2026-10-12",
            "subjects": ["Bahasa Inggris"],
            "duration_minutes": 60,
            "learning_material": "Simple past tense dan kosakata kegiatan sehari-hari",
            "learning_notes": None,
        },
        {
            "lesson_date": "2026-10-20",
            "subjects": ["Matematika", "Bahasa Indonesia"],
            "duration_minutes": 90,
            "learning_material": "Soal cerita pecahan dan ide pokok paragraf",
            "learning_notes": (
                "Kemampuan soal cerita meningkat dan Ananda sudah bisa menentukan ide pokok "
                "paragraf dengan baik."
            ),
        },
    ],
}


def test_session_summary_happy_path(monkeypatch):
    mock_llm = AsyncMock(
        return_value=(
            {
                "overall_status": "good",
                "summary": (
                    "Pada pertemuan awal Oktober, Ananda sudah lancar mengerjakan penjumlahan "
                    "bilangan dua digit. Pengurangan dengan teknik meminjam masih perlu latihan rutin."
                ),
                "strengths": [
                    "Lancar mengerjakan penjumlahan bersusun dua digit secara mandiri"
                ],
                "areas_to_improve": [
                    "Ketelitian pada pengurangan dengan teknik meminjam"
                ],
                "subjects_covered": [
                    {
                        "subject_name": "Matematika",
                        "highlight": "Penjumlahan dua digit lancar; pengurangan meminjam perlu latihan lanjutan.",
                    }
                ],
            },
            "gemini-3.5-flash-lite",
        )
    )
    monkeypatch.setattr(learning_summary_router_module, "summarize_with_llm", mock_llm)

    with TestClient(app) as client:
        res = client.post("/v1/learning-summary/summarize", json=SESSION_PAYLOAD)
        assert res.status_code == 200
        body = res.json()

        validated = LearningSummaryResponse.model_validate(body)
        assert validated.overall_status == "good"
        assert validated.model == "gemini-3.5-flash-lite"
        assert "parent_tips" not in body
        assert set(body.keys()) == {
            "overall_status",
            "summary",
            "strengths",
            "areas_to_improve",
            "subjects_covered",
            "model",
        }
        assert len(body["subjects_covered"]) == 1
        assert body["subjects_covered"][0]["subject_name"] == "Matematika"


def test_monthly_summary_multi_subject_dedup_and_canonical_casing(monkeypatch):
    mock_llm = AsyncMock(
        return_value=(
            {
                "overall_status": "very_good",
                "summary": "Sepanjang Oktober 2026, Ananda menunjukkan perkembangan yang sangat baik di empat mata pelajaran.",
                "strengths": [
                    "Antusias berdiskusi pada materi IPA",
                    "Mandiri menyelesaikan soal cerita pecahan",
                ],
                "areas_to_improve": [],
                "subjects_covered": [
                    {
                        "subject_name": "ipa",
                        "highlight": "Aktif berdiskusi tentang gaya gesek.",
                    },
                    {
                        "subject_name": "Matematika",
                        "highlight": "Pecahan campuran dan soal cerita meningkat.",
                    },
                    {
                        "subject_name": "matematika",
                        "highlight": "Duplikat yang harus dibuang.",
                    },
                    {
                        "subject_name": "Bahasa Inggris",
                        "highlight": "Mempelajari simple past tense.",
                    },
                    {
                        "subject_name": "Bahasa Indonesia",
                        "highlight": "Mampu menentukan ide pokok paragraf.",
                    },
                ],
            },
            "gemini-3.5-flash-lite",
        )
    )
    monkeypatch.setattr(learning_summary_router_module, "summarize_with_llm", mock_llm)

    with TestClient(app) as client:
        res = client.post("/v1/learning-summary/summarize", json=MONTHLY_PAYLOAD)
        assert res.status_code == 200
        body = res.json()
        subject_names = [item["subject_name"] for item in body["subjects_covered"]]
        assert subject_names == [
            "IPA",
            "Matematika",
            "Bahasa Inggris",
            "Bahasa Indonesia",
        ]


def test_legacy_null_and_blank_learning_notes_accepted(monkeypatch):
    legacy_payload = {
        "scope": "session",
        "period": "2026-10",
        "student_grade": "3 SD",
        "sessions": [
            {
                "lesson_date": "2026-10-12",
                "subjects": ["Bahasa Inggris"],
                "duration_minutes": 60,
                "learning_material": "Simple past tense dan kosakata kegiatan sehari-hari",
                "learning_notes": None,
            }
        ],
    }

    # Pastikan prompt builder tidak crash ketika learning_notes = None atau whitespace
    parsed_req = LearningSummaryRequest.model_validate(legacy_payload)
    prompt = build_user_prompt(parsed_req)
    assert "Oktober 2026" in prompt
    assert '"learning_notes": null' in prompt

    blank_notes_payload = {
        **legacy_payload,
        "sessions": [{**legacy_payload["sessions"][0], "learning_notes": "   "}],
    }
    parsed_blank = LearningSummaryRequest.model_validate(blank_notes_payload)
    assert parsed_blank.sessions[0].learning_notes is None

    mock_llm = AsyncMock(
        return_value=(
            {
                "overall_status": "good",
                "summary": "Ananda mengikuti pembelajaran Bahasa Inggris mengenai simple past tense dan kosakata sehari-hari.",
                "strengths": [],
                "areas_to_improve": [],
                "subjects_covered": [
                    {
                        "subject_name": "Bahasa Inggris",
                        "highlight": "Mempelajari simple past tense dan kosakata kegiatan sehari-hari.",
                    }
                ],
            },
            "gemini-3.5-flash-lite",
        )
    )
    monkeypatch.setattr(learning_summary_router_module, "summarize_with_llm", mock_llm)

    with TestClient(app) as client:
        res = client.post("/v1/learning-summary/summarize", json=legacy_payload)
        assert res.status_code == 200
        assert res.json()["areas_to_improve"] == []


def test_session_scope_rejects_multiple_sessions():
    invalid_payload = {
        **MONTHLY_PAYLOAD,
        "scope": "session",
    }
    with TestClient(app) as client:
        res = client.post("/v1/learning-summary/summarize", json=invalid_payload)
        assert res.status_code == 422


def test_zero_pii_extra_fields_and_blank_material_rejected():
    with TestClient(app) as client:
        # PII di root
        res_root_pii = client.post(
            "/v1/learning-summary/summarize",
            json={**SESSION_PAYLOAD, "student_name": "Budi Santoso"},
        )
        assert res_root_pii.status_code == 422

        # PII di dalam sessions[]
        res_session_pii = client.post(
            "/v1/learning-summary/summarize",
            json={
                **SESSION_PAYLOAD,
                "sessions": [
                    {**SESSION_PAYLOAD["sessions"][0], "tutor_name": "Pak Andi"}
                ],
            },
        )
        assert res_session_pii.status_code == 422

        # learning_material whitespace-only
        res_blank_material = client.post(
            "/v1/learning-summary/summarize",
            json={
                **SESSION_PAYLOAD,
                "sessions": [
                    {**SESSION_PAYLOAD["sessions"][0], "learning_material": "   "}
                ],
            },
        )
        assert res_blank_material.status_code == 422


def test_postprocessor_guardrail_sanitizes_messy_llm_output(monkeypatch):
    long_summary = "Perkembangan Ananda sangat baik. " * 60  # > 1500 karakter
    long_bullet = "Poin kelebihan yang sangat panjang " * 12  # > 240 karakter
    mock_llm = AsyncMock(
        return_value=(
            {
                "overall_status": "good",
                "summary": long_summary,
                "strengths": [
                    "",
                    "   ",
                    "Fokus belajar baik",
                    "fokus belajar baik",  # duplikat case-insensitive
                    long_bullet,
                    "Poin 3",
                    "Poin 4",
                    "Poin 5",
                    "Poin 6 yang harus dipotong",
                    "Poin 7 yang harus dipotong",
                ],
                "areas_to_improve": ["", "Latihan soal cerita", "latihan soal cerita"],
                "subjects_covered": [
                    {
                        "subject_name": "matematika",
                        "highlight": "Highlight sangat panjang " * 15,
                    },
                    {
                        "subject_name": "Kimia Kuantum",  # halusinasi tidak ada di input
                        "highlight": "Tidak boleh lolos",
                    },
                    {
                        "subject_name": "Matematika",
                        "highlight": "   ",  # kosong, harus dibuang
                    },
                ],
                "parent_tips": ["Key liar ini wajib dibuang"],
                "tokens_used": 999,
            },
            "gemini-3.5-flash-lite",
        )
    )
    monkeypatch.setattr(learning_summary_router_module, "summarize_with_llm", mock_llm)

    with TestClient(app) as client:
        res = client.post("/v1/learning-summary/summarize", json=SESSION_PAYLOAD)
        assert res.status_code == 200
        body = res.json()

        assert "parent_tips" not in body
        assert "tokens_used" not in body
        assert len(body["summary"]) <= 1000
        assert body["summary"].endswith("…")
        assert len(body["strengths"]) == 5
        assert all(1 <= len(item) <= 240 for item in body["strengths"])
        assert body["areas_to_improve"] == ["Latihan soal cerita"]
        assert len(body["subjects_covered"]) == 1
        assert body["subjects_covered"][0]["subject_name"] == "Matematika"
        assert len(body["subjects_covered"][0]["highlight"]) <= 240


def test_error_timeout_and_not_configured_handling(monkeypatch):
    with TestClient(app) as client:
        # 1. Timeout -> 504
        monkeypatch.setattr(
            learning_summary_router_module,
            "summarize_with_llm",
            AsyncMock(side_effect=LLMTimeoutError("timeout")),
        )
        res_timeout = client.post(
            "/v1/learning-summary/summarize", json=SESSION_PAYLOAD
        )
        assert res_timeout.status_code == 504

        # 2. Provider error -> 502 tanpa membocorkan secret/detail internal
        secret_marker = "AQ.SUPER_SECRET_KEY_DO_NOT_LEAK"
        monkeypatch.setattr(
            learning_summary_router_module,
            "summarize_with_llm",
            AsyncMock(
                side_effect=LLMProviderError(f"upstream failed with {secret_marker}")
            ),
        )
        res_provider = client.post(
            "/v1/learning-summary/summarize", json=SESSION_PAYLOAD
        )
        assert res_provider.status_code == 502
        assert secret_marker not in res_provider.text

        # 3. Output invalid dari LLM (overall_status rusak) -> 502
        monkeypatch.setattr(
            learning_summary_router_module,
            "summarize_with_llm",
            AsyncMock(
                return_value=(
                    {"overall_status": "excellent", "summary": "Bagus"},
                    "gemini-3.5-flash-lite",
                )
            ),
        )
        res_bad_output = client.post(
            "/v1/learning-summary/summarize", json=SESSION_PAYLOAD
        )
        assert res_bad_output.status_code == 502

        # 4. Belum dikonfigurasi -> 503, sementara /health tetap 200
        monkeypatch.setattr(
            learning_summary_router_module,
            "summarize_with_llm",
            AsyncMock(side_effect=LLMNotConfiguredError("API key kosong")),
        )
        res_unconfigured = client.post(
            "/v1/learning-summary/summarize", json=SESSION_PAYLOAD
        )
        assert res_unconfigured.status_code == 503

        monkeypatch.setenv("GEMINI_API_KEY", "")
        res_health = client.get("/health")
        assert res_health.status_code == 200
        assert res_health.json()["status"] == "ok"
        assert res_health.json()["learning_summary_configured"] is False
