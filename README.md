# Mumtaz Bimbel — AI Service (FastAPI)

Layanan **AI REST API** berbasis **FastAPI** untuk aplikasi **Mumtaz Bimbel Dashboard**. Service ini menjalankan **2 modul AI yang sepenuhnya terisolasi** dalam satu container/port (`8000`):

1. **Deteksi Anomali Absensi Tutor (`POST /v1/anomaly/analyze`)** — Model **Machine Learning lokal (LightGBM + Guardrail Deterministik)** untuk menjaga akurasi _payroll_ tutor dan _billing_ orang tua.
2. **Ringkasan Belajar Orang Tua (`POST /v1/learning-summary/summarize`)** — **Generative AI (Google Gemini Structured Output + Post-Processor Deterministik)** untuk merangkum perkembangan belajar anak per sesi maupun bulanan dalam Bahasa Indonesia.

> **Isolasi Kegagalan:** Modul Anomaly berjalan 100% lokal tanpa API key eksternal. Jika `GEMINI_API_KEY` belum dikonfigurasi, server dan `/v1/anomaly/analyze` tetap berjalan normal sementara `/v1/learning-summary/summarize` mengembalikan `HTTP 503`.

---

## 1. Daftar Endpoint

| Method & Path                         | Fungsi                                         | Engine / Model            | Catatan                                                                                |
| ------------------------------------- | ---------------------------------------------- | ------------------------- | -------------------------------------------------------------------------------------- |
| `GET /`                               | Info dasar service & daftar endpoint           | FastAPI                   | Non-autentikasi, metadata layanan                                                      |
| `GET /health`                         | Health check kesiapan ML & konfigurasi GenAI   | Lokal (tanpa call LLM)    | Mengembalikan `status`, `model_loaded`, `feature_count`, `learning_summary_configured` |
| `GET /docs`                           | Dokumentasi interaktif Swagger UI              | FastAPI OpenAPI           | Untuk pengujian manual payload                                                         |
| `POST /v1/anomaly/analyze`            | Validasi anomali sesi absensi tutor            | LightGBM + Guardrail      | Hanya menerima 8 field publik (tanpa materi/catatan)                                   |
| `POST /v1/learning-summary/summarize` | Ringkasan belajar anak (`session` / `monthly`) | Google Gemini + Guardrail | Stateless, zero-PII (`extra="forbid"`), strict JSON contract                           |

---

## 2. Modul 1 — Deteksi Anomali Absensi (`POST /v1/anomaly/analyze`)

### Model & Performa (`artifacts/anomaly_model.pkl`)

- **Algoritma:** `LightGBM` (`~1,1 MB`, inferensi milidetik, dimuat sekali saat _lifespan startup_).
- **Dataset Latih:** `7.557` baris (`5.289` train / `1.134` val / `1.134` test) dengan distribusi `60% valid`, `20% needs_revision`, `20% rejected` (referensi di `dataset/`).
- **Evaluasi:** `Val Accuracy 99,91%`, `Val Macro F1 99,90%`, `Test Accuracy 100%`, `Test Macro F1 100%`.
- **Pipeline 5 Tahap:**
  1. `app/schemas.py` — Validasi `target` (8 field publik), `comparisons` (maks. 500 sesi riwayat `±30` hari), dan `config` ambang batas dinamis dari backend.
  2. `app/feature_extractor.py` — Ekstraksi **19 fitur numerik** (durasi, jam mulai, duplikat persis/samar, overlap tutor/murid/diri sendiri, statistik 30 hari).
  3. `artifacts/anomaly_model.pkl` — Prediksi kelas awal LightGBM.
  4. `app/guardrail.py` — Guardrail deterministik untuk akurasi 100% di titik batas (menutup celah diskretisasi seperti durasi `181` menit) & mematuhi threshold dinamis tanpa perlu _retrain_.
  5. `app/response_builder.py` — Menyusun `validity`, `validity_reason`, dan `findings` berbahasa Indonesia.

### Klasifikasi Status (`rejected` > `needs_revision` > `valid`)

| Status               | Dampak di Aplikasi                          | Kriteria Default                                                                                                                    |
| -------------------- | ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| **`valid`**          | Langsung disetujui (masuk gaji & tagihan)   | Durasi `30–180` menit, mulai `07:00–21:00` WIB, tidak duplikat, tidak bentrok jadwal                                                |
| **`needs_revision`** | Ditahan dari rekap; tutor dapat merevisi    | Durasi `< 30` / `> 180` mnt, mulai `< 07:00` / `> 21:00`, duplikat samar (beda jam), atau bentrok jadwal (tutor/murid/diri sendiri) |
| **`rejected`**       | Ditahan dari rekap; tidak bisa diedit tutor | Duplikat 100% persis (6 atribut identik: `tutor_id`, `student_id`, `subject_ids`, `lesson_date`, `start_time`, `duration_minutes`)  |

Kategori `finding_type`: `suspected_duplicate`, `duration_outlier`, `late_start`, `unusual_pattern`.

<details>
<summary><strong>Contoh Request & Response <code>POST /v1/anomaly/analyze</code></strong></summary>

**Request:**

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

**Response (`HTTP 200`):**

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

## 3. Modul 2 — Ringkasan Belajar Orang Tua (`POST /v1/learning-summary/summarize`)

### Model & Mekanisme Eksekusi (`app/learning_summary/`)

- **Provider & SDK:** Google Gemini API via `google-genai` (async `client.aio`) dengan **Structured Output** (`response_mime_type="application/json"`, `response_schema=LLMOutputSchema`).
- **Model Utama:** `gemini-3.5-flash-lite` dengan `thinking_level=MINIMAL` (latensi target ~1,5–5 detik) dan `temperature=0.25`.
- **Resiliensi & Fallback Otomatis:** Retry terbatas untuk error `5xx` transien (`503 UNAVAILABLE` high demand), lalu otomatis berpindah ke `LEARNING_SUMMARY_FALLBACK_MODELS` (`gemini-3.6-flash` → `gemini-3.5-flash`) dalam satu total budget timeout `24 detik` (lebih kecil dari timeout `30 detik` Backend Dashboard).
- **Stateless:** Tidak menyimpan cache atau koneksi database; caching persisten + SHA-256 `source_fingerprint` dikelola di PostgreSQL Backend Dashboard.

### Aturan Kontrak & Guardrail (100% Cocok dengan `@mumtaz/contracts`)

- **Zero-PII & Strict Input (`extra="forbid"`):** Menolak field PII (`student_name`, `tutor_name`, `school_name`, UUID, `admin_note`) dengan `HTTP 422`.
- **2 Cakupan (`scope`):**
  - `session`: wajib tepat **1 sesi**.
  - `monthly`: **1–100 sesi** `approved` dalam satu bulan (`YYYY-MM`).
- **Multi-subject & Data Legacy:** Mendukung `1–5` mapel per sesi dan `learning_notes: null` (string kosong dinormalisasi jadi `null`).
- **Prompt Safety (`prompt_builder.py`):** Bahasa Indonesia ramah orang tua (sebutan `"Ananda"`), membungkus data sesi dalam `<sessions_data>` untuk mencegah _prompt injection_.
- **Post-Processor Deterministik (`postprocessor.py`):**
  - Whitelist tepat 6 field output (`overall_status`, `summary`, `strengths`, `areas_to_improve`, `subjects_covered`, `model`) — key liar seperti `parent_tips` dibuang otomatis.
  - Truncate aman (`summary <= 1000`, bullet `<= 240`, `subject_name <= 80`), batas item (`strengths/areas_to_improve <= 5`, `subjects_covered <= 15`), dedup case-insensitive.
  - Kanonisasi ejaan `subject_name` sesuai input & membuang mata pelajaran halusinasi.
- **Mapping HTTP Error:** `422` (payload tidak valid), `502` (error upstream/output rusak), `503` (API key belum diset), `504` (timeout LLM). Tidak pernah membocorkan API key atau stack trace.

<details>
<summary><strong>Contoh Request & Response <code>POST /v1/learning-summary/summarize</code></strong></summary>

**Request (`scope: "session"`):**

```json
{
  "scope": "session",
  "period": "2026-10",
  "student_grade": "2 SD",
  "sessions": [
    {
      "lesson_date": "2026-10-01",
      "subjects": ["Matematika"],
      "duration_minutes": 90,
      "learning_material": "Penjumlahan dan pengurangan bilangan dua digit",
      "learning_notes": "Siswa lancar mengerjakan soal penjumlahan bersusun dua digit tanpa bantuan. Pada pengurangan dengan teknik meminjam masih perlu didampingi perlahan."
    }
  ]
}
```

**Response (`HTTP 200`):**

```json
{
  "overall_status": "good",
  "summary": "Pada pertemuan awal Oktober 2026, Ananda sudah lancar mengerjakan penjumlahan bilangan dua digit secara mandiri. Pengurangan dengan teknik meminjam masih perlu latihan perlahan agar lebih teliti.",
  "strengths": [
    "Lancar mengerjakan penjumlahan bersusun dua digit tanpa bantuan"
  ],
  "areas_to_improve": ["Ketelitian pada pengurangan dengan teknik meminjam"],
  "subjects_covered": [
    {
      "subject_name": "Matematika",
      "highlight": "Penjumlahan dua digit lancar; pengurangan teknik meminjam masih perlu pendampingan."
    }
  ],
  "model": "gemini-3.5-flash-lite"
}
```

</details>

---

## 4. Tech Stack & Struktur Repository

- **Runtime & Web:** Python 3.12, FastAPI, Uvicorn, Pydantic v2
- **Machine Learning:** LightGBM, Scikit-learn (`1.6.1`), Pandas, NumPy, Joblib
- **Generative AI:** `google-genai`, `python-dotenv`
- **Testing & Deploy:** Pytest, HTTPX, Docker & Docker Compose

```text
AI-MODEL-MUMTAZ/
├── app/
│   ├── main.py                      # Entrypoint FastAPI (/, /health, /v1/anomaly/analyze + router)
│   ├── schemas.py                   # Skema Pydantic Anomaly & HealthResponse
│   ├── feature_extractor.py         # Transformasi JSON sesi -> 19 fitur numerik
│   ├── guardrail.py                 # Guardrail deterministik batas aturan bisnis anomaly
│   ├── response_builder.py          # Generator validity_reason & findings Bahasa Indonesia
│   └── learning_summary/
│       ├── config.py                # Loader .env (model, fallback, timeout, thinking_level)
│       ├── schemas.py               # Kontrak strict Pydantic Request/Response + LLMOutputSchema
│       ├── prompt_builder.py        # System & user prompt Bahasa Indonesia (session/monthly)
│       ├── postprocessor.py         # Guardrail sanitasi output LLM & validasi mapel
│       ├── llm_client.py            # Client async Gemini + retry 5xx + fallback model otomatis
│       └── router.py                # APIRouter: POST /v1/learning-summary/summarize
├── artifacts/
│   ├── anomaly_model.pkl            # Model LightGBM terlatih
│   └── feature_metadata.json        # Daftar 19 fitur, distribusi dataset, & metrik evaluasi
├── dataset/
│   ├── feature_extraction.ipynb     # Notebook ekstraksi fitur & pelatihan model
│   └── sessions_with_synthetic.csv  # Dataset latih sintetis (7.557 baris)
├── tests/
│   ├── test_api.py                  # 8 test: /health, batas 30/180/181 mnt, duplikat, overlap, config
│   └── test_learning_summary.py     # 8 test offline (mock LLM): kontrak, zero-PII, guardrail, fallback, error
├── .env.example                     # Template environment variable GenAI
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── pytest.ini
```

---

## 5. Konfigurasi Environment (`.env`)

Salin `.env.example` menjadi `.env` (file `.env` diabaikan oleh `.gitignore`):

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_api_key_here
LEARNING_SUMMARY_MODEL=gemini-3.5-flash-lite
LEARNING_SUMMARY_FALLBACK_MODELS=gemini-3.6-flash,gemini-3.5-flash
LEARNING_SUMMARY_THINKING_LEVEL=MINIMAL
LEARNING_SUMMARY_LLM_TIMEOUT_SECONDS=24
LEARNING_SUMMARY_TEMPERATURE=0.25
LEARNING_SUMMARY_MAX_OUTPUT_TOKENS=1536
```

---

## 6. Cara Menjalankan & Testing

### Opsi A — Docker Compose

```powershell
# Build image & jalankan di background (port 8000; otomatis memuat .env jika ada)
docker compose up --build -d

# Cek log container
docker compose logs -f ai-anomaly

# Jalankan seluruh 16 unit test di dalam container
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

# Jalankan seluruh 16 unit test (100% offline, tidak memakai kuota Gemini)
pytest -v
```

---

## 7. Integrasi dengan `mumtaz-bimbel-dashboard`

Tambahkan konfigurasi berikut di `backend/.env` pada repositori Fullstack (ganti `localhost` ke `host.docker.internal` jika Backend berjalan di dalam Docker):

```env
# 1. Anomaly Detection (LightGBM)
ANOMALY_SERVICE_URL=http://localhost:8000
ANOMALY_MODEL_NAME=anomaly-lgbm-v1
ANOMALY_DURATION_OUTLIER_MINUTES=180
ANOMALY_DURATION_MIN_MINUTES=30
ANOMALY_LATE_START_AFTER=21:00
ANOMALY_EARLY_START_BEFORE=07:00
ANOMALY_PROVIDER_TIMEOUT_MS=20000

# 2. Generative AI Learning Summary (Google Gemini)
LEARNING_SUMMARY_SERVICE_URL=http://localhost:8000
LEARNING_SUMMARY_MODEL_NAME=
LEARNING_SUMMARY_TIMEOUT_MS=30000
```

Pastikan saat Backend Dashboard dijalankan (`npm run dev -w backend`), log startup `api_listening` menampilkan `"anomaly_provider": "ml_fastapi"` dan `"learning_summary_provider": "genai_fastapi"`.
