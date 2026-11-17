# Panduan Integrasi Layanan AI Anomaly Detection untuk Tim Fullstack

Dokumen ini berisi panduan singkat bagi **Fullstack Developer** untuk menjalankan layanan FastAPI ML (`C:\AI-MODEL-MUMTAZ`) di lokal menggunakan **Docker Compose** dan menyambungkannya ke Backend (`mumtaz-bimbel-dashboard`).

---

## 1. Menjalankan Service AI dengan Docker (Direkomendasikan)

Pastikan **Docker Desktop** sudah berjalan, lalu jalankan perintah berikut di folder repositori AI ini:

```powershell
# 1. Clone atau pull update terbaru
git pull origin main

# 2. Build & jalankan container FastAPI di background (port 8000)
docker compose up --build -d
```

### Cek Status & Log Service AI
- **Health Check:** Buka `http://localhost:8000/health` di browser atau terminal.
  Respons normal:
  ```json
  {
    "status": "ok",
    "model_loaded": true,
    "model_name": "LightGBM",
    "feature_count": 19
  }
  ```
- **Swagger UI (Dokumentasi & Uji Coba Interaktif):** `http://localhost:8000/docs`
- **Lihat Log Container:**
  ```powershell
  docker compose logs -f ai-anomaly
  ```
- **Jalankan Unit Test di Dalam Container (Opsional):**
  ```powershell
  docker compose run --rm ai-anomaly pytest -v
  ```
- **Menghentikan Container:**
  ```powershell
  docker compose down
  ```

> **Alternatif Tanpa Docker (Python Lokal):**
> ```powershell
> python -m venv venv
> .\venv\Scripts\Activate.ps1
> pip install -r requirements.txt
> uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
> ```

---

## 2. Menyambungkan ke Backend (`mumtaz-bimbel-dashboard`)

Buka file `backend/.env` pada repositori dashboard fullstack, lalu pastikan konfigurasi berikut aktif (tidak dikomentari `#`):

```env
# Pilih salah satu URL sesuai cara Backend dijalankan:
# 1. Jika Backend jalan di lokal (npm run dev -w backend):
ANOMALY_SERVICE_URL=http://localhost:8000

# 2. Jika Backend JUGA jalan di dalam Docker container:
# ANOMALY_SERVICE_URL=http://host.docker.internal:8000
# (atau http://ai-anomaly:8000 jika berada dalam satu docker-compose network)

ANOMALY_MODEL_NAME=anomaly-lgbm-v1
ANOMALY_DURATION_OUTLIER_MINUTES=180
ANOMALY_DURATION_MIN_MINUTES=30
ANOMALY_LATE_START_AFTER=21:00
ANOMALY_EARLY_START_BEFORE=07:00
ANOMALY_PROVIDER_TIMEOUT_MS=20000
```

Setelah menyimpan `.env`, jalankan ulang Backend:

```powershell
npm run dev -w backend
```

Pastikan pada log startup Backend muncul:

```json
"anomaly_provider": "ml_fastapi"
```

---

## 3. Ringkasan Endpoint & Kontrak API

### A. `GET /health`
Digunakan untuk memastikan container hidup dan file model `anomaly_model.pkl` (19 fitur) sudah termuat di memori.

### B. `POST /v1/anomaly/analyze`
Dipanggil otomatis oleh `HttpAnomalyDetector` di Backend setiap kali Tutor melakukan *submit* atau *revisi* absen.

- **Input dari Backend (`AnalyzeRequest`):**
  ```json
  {
    "target": {
      "id": "uuid-sesi-baru",
      "tutor_id": "uuid-tutor",
      "student_id": "uuid-murid",
      "subject_ids": ["uuid-mapel-1"],
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
- **Output ke Backend (`AnalyzeResponse`):**
  ```json
  {
    "validity": "needs_revision",
    "validity_reason": "Perlu konfirmasi/revisi: Durasi sesi tercatat 181 menit, melebihi batas maksimal 180 menit (+1 menit).",
    "findings": [
      {
        "lesson_session_id": "uuid-sesi-baru",
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

---

## 4. Skenario Uji Cepat End-to-End di Aplikasi

Untuk memastikan integrasi **Frontend $\rightarrow$ Backend $\rightarrow$ FastAPI ML** berjalan normal setelah terhubung, coba 3 input berikut lewat form absen Tutor:

| Skenario Uji di UI Tutor | Input yang Dicoba | Hasil yang Harus Tampil di Dashboard |
|---|---|---|
| **1. Sesi Normal** | Jam mulai `08:00`, durasi `60` menit | Status **`valid`** (Hijau), `findings` kosong, masuk rekap |
| **2. Perlu Revisi** | Jam mulai `08:00`, durasi `181` menit (atau `< 30` mnt / mulai `< 07:00` atau `> 21:00` / bentrok jadwal) | Status **`needs_revision`** (Biru), muncul alasan Bahasa Indonesia & detail finding |
| **3. Ditolak (Duplikat Persis)** | Submit ulang sesi dengan tutor, murid, mapel, tanggal, jam mulai, dan durasi yang **100% sama** | Status **`rejected`** (Merah), `finding_type: suspected_duplicate`, `related_lesson_session_id` terisi |

---

## 5. Troubleshooting Singkat

- **Port `8000` sudah dipakai aplikasi lain:**
  Ubah mapping port di `docker-compose.yml` menjadi `"8001:8000"`, lalu sesuaikan `ANOMALY_SERVICE_URL=http://localhost:8001` di `backend/.env`.
- **Backend memunculkan error koneksi (`ECONNREFUSED` / `failed`):**
  1. Pastikan container menyala lewat `docker ps` atau cek `http://localhost:8000/health`.
  2. Jika Backend berjalan di dalam Docker, jangan gunakan `localhost:8000`, melainkan `http://host.docker.internal:8000` (atau nama service `http://ai-anomaly:8000`).
- **Ingin menonaktifkan sementara FastAPI di Backend:**
  Beri tanda `#` di depan `ANOMALY_SERVICE_URL` pada `backend/.env` lalu restart Backend (otomatis *fallback* ke provider sebelumnya).
