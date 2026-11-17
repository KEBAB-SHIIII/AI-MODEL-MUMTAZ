"""
Pengujian Otomatis Layanan FastAPI Deteksi Anomali Absen Tutor.

Menjalankan test dengan perintah:
    .\\venv\\Scripts\\pytest.exe -v
"""

from fastapi.testclient import TestClient

from app.main import app

BASE_SESSION = {
    "id": "00000000-0000-4000-8000-000000000009",
    "tutor_id": "00000000-0000-4000-8002-000000000001",
    "student_id": "00000000-0000-4000-8003-000000000002",
    "subject_ids": ["00000000-0000-4000-8004-000000000001"],
    "lesson_date": "2026-10-10",
    "start_time": "08:15",
    "duration_minutes": 90,
    "submitted_at": "2026-10-10T10:05:00.000Z",
}


def test_health_endpoint():
    with TestClient(app) as client:
        res = client.get("/health")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ok"
        assert body["model_loaded"] is True
        assert body["model_name"] == "LightGBM"
        assert body["feature_count"] == 19


def test_duration_boundaries():
    with TestClient(app) as client:
        # Batas bawah valid (tepat 30 menit)
        res_30 = client.post(
            "/v1/anomaly/analyze",
            json={
                "target": {**BASE_SESSION, "duration_minutes": 30},
                "comparisons": [],
            },
        )
        assert res_30.status_code == 200
        assert res_30.json()["validity"] == "valid"
        assert res_30.json()["findings"] == []

        # 29 menit -> wajib needs_revision
        res_29 = client.post(
            "/v1/anomaly/analyze",
            json={
                "target": {**BASE_SESSION, "duration_minutes": 29},
                "comparisons": [],
            },
        )
        assert res_29.status_code == 200
        body_29 = res_29.json()
        assert body_29["validity"] == "needs_revision"
        assert body_29["findings"][0]["finding_type"] == "duration_outlier"

        # Batas atas valid (tepat 180 menit)
        res_180 = client.post(
            "/v1/anomaly/analyze",
            json={
                "target": {**BASE_SESSION, "duration_minutes": 180},
                "comparisons": [],
            },
        )
        assert res_180.status_code == 200
        assert res_180.json()["validity"] == "valid"
        assert res_180.json()["findings"] == []

        # Kasus 181 menit (Boundary Discretization Gap) -> wajib ditangkap Guardrail jadi needs_revision
        res_181 = client.post(
            "/v1/anomaly/analyze",
            json={
                "target": {**BASE_SESSION, "duration_minutes": 181},
                "comparisons": [],
            },
        )
        assert res_181.status_code == 200
        body_181 = res_181.json()
        assert body_181["validity"] == "needs_revision"
        assert body_181["findings"][0]["finding_type"] == "duration_outlier"
        assert "181 menit" in body_181["validity_reason"]


def test_start_time_boundaries():
    with TestClient(app) as client:
        # Tepat 07:00 dan tepat 21:00 -> valid
        for valid_time in ("07:00", "21:00"):
            res = client.post(
                "/v1/anomaly/analyze",
                json={
                    "target": {**BASE_SESSION, "start_time": valid_time},
                    "comparisons": [],
                },
            )
            assert res.status_code == 200
            assert res.json()["validity"] == "valid"

        # 06:59 dan 21:01 -> needs_revision (late_start)
        for bad_time in ("06:59", "21:01"):
            res = client.post(
                "/v1/anomaly/analyze",
                json={
                    "target": {**BASE_SESSION, "start_time": bad_time},
                    "comparisons": [],
                },
            )
            assert res.status_code == 200
            body = res.json()
            assert body["validity"] == "needs_revision"
            assert body["findings"][0]["finding_type"] == "late_start"


def test_exact_duplicate_is_rejected():
    earlier = {
        **BASE_SESSION,
        "id": "00000000-0000-4000-8000-000000000008",
        "submitted_at": "2026-10-10T09:00:00.000Z",
    }
    with TestClient(app) as client:
        res = client.post(
            "/v1/anomaly/analyze",
            json={"target": BASE_SESSION, "comparisons": [earlier]},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["validity"] == "rejected"
        assert body["findings"][0]["finding_type"] == "suspected_duplicate"
        assert body["findings"][0]["related_lesson_session_id"] == earlier["id"]


def test_fuzzy_duplicate_is_needs_revision():
    earlier = {
        **BASE_SESSION,
        "id": "00000000-0000-4000-8000-000000000007",
        "start_time": "14:00",
        "submitted_at": "2026-10-10T09:00:00.000Z",
    }
    with TestClient(app) as client:
        res = client.post(
            "/v1/anomaly/analyze",
            json={"target": BASE_SESSION, "comparisons": [earlier]},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["validity"] == "needs_revision"
        assert body["findings"][0]["finding_type"] == "suspected_duplicate"
        assert body["findings"][0]["related_lesson_session_id"] == earlier["id"]


def test_overlaps_and_adjacent_sessions():
    # Sesi 08:15-09:45 (90 menit)
    with TestClient(app) as client:
        # 1. Tutor overlap dengan murid berbeda (09:00-10:00)
        tutor_conflict = {
            **BASE_SESSION,
            "id": "00000000-0000-4000-8000-000000000011",
            "student_id": "00000000-0000-4000-8003-000000000099",
            "start_time": "09:00",
            "duration_minutes": 60,
            "submitted_at": "2026-10-10T09:00:00.000Z",
        }
        res_t = client.post(
            "/v1/anomaly/analyze",
            json={"target": BASE_SESSION, "comparisons": [tutor_conflict]},
        )
        assert res_t.json()["validity"] == "needs_revision"
        assert res_t.json()["findings"][0]["finding_type"] == "unusual_pattern"

        # 2. Murid overlap dengan tutor berbeda (08:00-09:00)
        student_conflict = {
            **BASE_SESSION,
            "id": "00000000-0000-4000-8000-000000000012",
            "tutor_id": "00000000-0000-4000-8002-000000000099",
            "start_time": "08:00",
            "duration_minutes": 60,
            "submitted_at": "2026-10-10T09:00:00.000Z",
        }
        res_s = client.post(
            "/v1/anomaly/analyze",
            json={"target": BASE_SESSION, "comparisons": [student_conflict]},
        )
        assert res_s.json()["validity"] == "needs_revision"
        assert res_s.json()["findings"][0]["finding_type"] == "unusual_pattern"

        # 3. Menyambung persis (09:45-10:45) -> BUKAN overlap (valid)
        adjacent = {
            **BASE_SESSION,
            "id": "00000000-0000-4000-8000-000000000013",
            "student_id": "00000000-0000-4000-8003-000000000099",
            "start_time": "09:45",
            "duration_minutes": 60,
            "submitted_at": "2026-10-10T09:00:00.000Z",
        }
        res_adj = client.post(
            "/v1/anomaly/analyze",
            json={"target": BASE_SESSION, "comparisons": [adjacent]},
        )
        assert res_adj.json()["validity"] == "valid"
        assert res_adj.json()["findings"] == []


def test_priority_rejected_overrides_needs_revision():
    target_long_dup = {**BASE_SESSION, "duration_minutes": 210}
    earlier_long = {
        **target_long_dup,
        "id": "00000000-0000-4000-8000-000000000014",
        "submitted_at": "2026-10-10T09:00:00.000Z",
    }
    with TestClient(app) as client:
        res = client.post(
            "/v1/anomaly/analyze",
            json={"target": target_long_dup, "comparisons": [earlier_long]},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["validity"] == "rejected"
        types = {f["finding_type"] for f in body["findings"]}
        assert types == {"suspected_duplicate", "duration_outlier"}


def test_dynamic_config_from_backend_env():
    with TestClient(app) as client:
        res = client.post(
            "/v1/anomaly/analyze",
            json={
                "target": {**BASE_SESSION, "duration_minutes": 130},
                "comparisons": [],
                "config": {
                    "durationOutlierMinutes": 120,
                    "durationMinMinutes": 30,
                    "lateStartAfter": "21:00",
                    "earlyStartBefore": "07:00",
                },
            },
        )
        assert res.status_code == 200
        body = res.json()
        assert body["validity"] == "needs_revision"
        assert body["findings"][0]["finding_type"] == "duration_outlier"
