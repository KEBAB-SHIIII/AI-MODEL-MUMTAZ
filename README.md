# Mumtaz Bimbel — AI Anomaly Detection Service

Layanan **Machine Learning REST API** berbasis **FastAPI** dan **LightGBM** untuk mendeteksi anomali absensi tutor secara otomatis pada aplikasi **Mumtaz Bimbel Dashboard** (menggantikan prototipe Gemini API dengan model ML buatan sendiri).

Service ini mengevaluasi setiap absen yang di-_submit_ atau direvisi oleh tutor secara _real-time_, mengklasifikasikan status validitasnya untuk menjaga akurasi **payroll (gaji tutor)** dan **billing (tagihan orang tua)**, serta mengembalikan penjelasan dalam Bahasa Indonesia ke Backend Node.js (`HttpAnomalyDetector`).

---

## 1. Tujuan & Klasifikasi Status (`validity`)

Setiap sesi les yang masuk diklasifikasikan ke dalam **3 status validitas** dengan urutan prioritas mutlak **`rejected` > `needs_revision` > `valid`**:

| Status               | Dampak di Aplikasi                                    | Kapan Diberikan?                                                                                                                                                                                      |
| -------------------- | ----------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`valid`**          | Langsung disetujui dan **masuk rekap gaji & tagihan** | Sesi normal: durasi `30–180` menit, jam mulai `07:00–21:00` WIB, tidak duplikat, dan tidak bentrok jadwal                                                                                             |
| **`needs_revision`** | **Ditahan dari rekap**; tutor dapat merevisi data     | Melanggar salah satu dari **8 kondisi**: durasi `< 30` atau `> 180` menit, mulai `< 07:00` atau `> 21:00` WIB, duplikat samar (beda jam mulai), atau bentrok jadwal (tutor, murid, atau sesi sendiri) |
| **`rejected`**       | **Ditahan dari rekap**; tidak bisa diedit tutor       | **Duplikat 100% persis** (6 atribut identik: `tutor_id`, `student_id`, `subject_ids`, `lesson_date`, `start_time`, dan `duration_minutes`) dengan sesi yang sudah di-_submit_ lebih awal              |

Seluruh temuan juga dipetakan ke 4 kategori enum database PostgreSQL (`finding_type`): `suspected_duplicate`, `duration_outlier`, `late_start`, dan `unusual_pattern`.

---

## 2. Arsitektur & Alur Kerja (`POST /v1/anomaly/analyze`)

Layanan menggunakan pendekatan **Hybrid (Machine Learning + Deterministic Guardrail)** melalui **5 tahap eksekusi** pada setiap request:

```text
Backend Node.js (JSON: target + comparisons +-30 hari + config)
   │
   ▼  Tahap 1 — Validasi Kontrak (app/schemas.py)
   │  Validasi 8 field publik (tanpa materi/catatan privat) via Pydantic
   ▼  Tahap 2 — Ekstraksi 19 Fitur Numerik (app/feature_extractor.py)
   │  Bandingkan target vs maks. 500 sesi riwayat (+-30 hari lebih awal) -> 19 fitur angka
   ▼  Tahap 3 — Inferensi Model ML (artifacts/anomaly_model.pkl)
   │  Prediksi kelas awal menggunakan model LightGBM
   ▼  Tahap 4 — Guardrail Deterministik (app/guardrail.py)
   │  Tutup celah batas (mis. kasus 181 menit) & patuhi threshold dinamis dari .env Backend
   ▼  Tahap 5 — Penyusunan Respons (app/response_builder.py)
      Kembalikan JSON { validity, validity_reason, findings } dalam Bahasa Indonesia
```

### Mengapa Menggunakan LightGBM + Guardrail?

- **Ringan & Cepat:** File model `anomaly_model.pkl` berukuran ~1,1 MB dan memproses inferensi dalam hitungan milidetik.
- **Akurasi Tinggi:** Dilatih pada **7.557 baris** data (60% `valid`, 20% `needs_revision`, 20% `rejected`) dan mengungguli Random Forest serta XGBoost dengan **Test Accuracy `100%` (`1.0`)**, **Test Macro F1 `100%` (`1.0`)**, dan **Validation Accuracy `99,91%`**.
- **Guardrail 100% Presisi di Garis Batas:** Menutup _Boundary Discretization Gap_ (seperti durasi `181` menit karena celah sampel antara `180` dan `183` menit di data latih) sekaligus mendukung perubahan ambang batas dinamis dari `backend/.env` tanpa perlu _retrain_ model.

---

## 3. Tech Stack & Struktur Proyek

- **Framework & Server:** Python 3.12, FastAPI, Uvicorn, Pydantic v2
- **Machine Learning:** LightGBM, Scikit-learn (`1.6.1`), Pandas, NumPy, Joblib
- **Testing & Container:** Pytest, HTTPX, Docker & Docker Compose

```text
C:\AI-MODEL-MUMTAZ\
├── app/
│   ├── main.py               # Entrypoint FastAPI (GET /, GET /health, POST /v1/anomaly/analyze)
│   ├── schemas.py            # Tahap 1: Skema Pydantic request & response
│   ├── feature_extractor.py  # Tahap 2: Transformasi JSON -> 19 fitur numerik + helper_meta
│   ├── guardrail.py          # Tahap 4: Guardrail deterministik batas aturan bisnis
│   └── response_builder.py   # Tahap 5: Generator validity_reason & findings Bahasa Indonesia
├── artifacts/
│   ├── anomaly_model.pkl     # Model LightGBM terlatih
│   └── feature_metadata.json # Urutan baku 19 fitur & metadata evaluasi model
├── tests/
│   └── test_api.py           # Pengujian otomatis (health, batas 30/180/181 mnt, duplikat, overlap, config)
├── dataset/                  # Dataset latih sintetis & notebook Google Colab (referensi)
├── docs/                     # Dokumentasi teknis, analisis kasus 181 mnt, & panduan integrasi
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── pytest.ini
```

---

## 4. Cara Menjalankan Service

### Opsi A — Docker Compose (Direkomendasikan untuk Tim Fullstack)

Pastikan Docker Desktop sudah aktif, lalu jalankan dari root folder proyek:

```powershell
# Build image & jalankan service di background (port 8000)
docker compose up --build -d

# Cek log container
docker compose logs -f ai-anomaly

# Jalankan seluruh unit test di dalam container
docker compose run --rm ai-anomaly pytest -v

# Hentikan container
docker compose down
```

### Opsi B — Lokal Menggunakan Python `venv`

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Jalankan server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Jalankan seluruh unit test
pytest -v
```

---

## 5. Referensi Endpoint & Kontrak API

- **Health Check:** `GET http://localhost:8000/health`
- **Swagger UI (Interaktif):** `http://localhost:8000/docs`
- **Analisis Anomali:** `POST http://localhost:8000/v1/anomaly/analyze`

<details>
<summary><strong>Contoh Request & Response <code>POST /v1/anomaly/analyze</code></strong></summary>

**Request Body (dari Backend `HttpAnomalyDetector`):**

```json
{
  "target": {
    "id": "99999999-9999-4999-8999-999999999900",
    "tutor_id": "6daa16aa-6e13-430f-8fab-fd153fa48628",
    "student_id": "862cdfac-370d-493e-a3d7-0104f4c56ebf",
    "subject_ids": ["8cee3629-d670-4cc6-91ca-b0949f8a93d7"],
    "lesson_date": "2026-10-10",
    "start_time": "08:15",
    "duration_minutes": 181,
    "submitted_at": "2026-10-10T10:30:00.000Z"
  },
  "comparisons": [],
  "config": {
    "durationOutlierMinutes": 180,
    "durationMinMinutes": 30,
    "lateStartAfter": "21:00",
    "earlyStartBefore": "07:00"
  }
}
```

**Response Body (`HTTP 200`):**

```json
{
  "validity": "needs_revision",
  "validity_reason": "Perlu konfirmasi/revisi: Durasi sesi tercatat 181 menit, melebihi batas maksimal 180 menit (+1 menit).",
  "findings": [
    {
      "lesson_session_id": "99999999-9999-4999-8999-999999999900",
      "related_lesson_session_id": null,
      "is_anomaly": true,
      "finding_type": "duration_outlier",
      "severity": "low",
      "reason": "Durasi sesi tercatat 181 menit, melebihi batas maksimal 180 menit (+1 menit).",
      "evidence_summary": "Rentang les pukul 08:15–11:16 WIB (181 menit) melampaui ambang wajar 180 menit.",
      "suggested_action": "review"
    }
  ]
}
```

</details>

---

## 6. Integrasi dengan Backend Dashboard (`mumtaz-bimbel-dashboard`)

Tambahkan/aktifkan konfigurasi berikut di `backend/.env` pada repositori Fullstack:

```env
# Gunakan localhost jika Backend jalan di host, atau host.docker.internal / ai-anomaly jika Backend juga di Docker
ANOMALY_SERVICE_URL=http://localhost:8000
ANOMALY_MODEL_NAME=anomaly-lgbm-v1
ANOMALY_DURATION_OUTLIER_MINUTES=180
ANOMALY_DURATION_MIN_MINUTES=30
ANOMALY_LATE_START_AFTER=21:00
ANOMALY_EARLY_START_BEFORE=07:00
ANOMALY_PROVIDER_TIMEOUT_MS=20000
```

Saat Backend dijalankan (`npm run dev -w backend`), pastikan log startup menampilkan `"anomaly_provider": "ml_fastapi"`.

---

## 7. Dokumentasi Terkait

- [Panduan Integrasi Tim Fullstack](docs/PANDUAN%20INTEGRASI%20FULLSTACK.md)
- [Konteks Bisnis Project AI Anomaly](docs/KONTEKS%20PROJECT%20AI%20ANOMALY.md)
- [Spesifikasi 19 Fitur & Aturan Comparison](docs/IMPLEMENTASI%20AI%20MODEL%20+%20COMPARISON.md)
- [Analisis Kasus Batas 181 Menit & Guardrail](docs/analisis_kasus_181_menit_dan_solusi_guardrail_fastapi.md)
- [Laporan Progress Migrasi Backend AI](docs/LAPORAN%20PROGRESS%20MIGRASI%20BACKEND%20AI.md)
