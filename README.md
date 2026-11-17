# Mumtaz Bimbel — AI Anomaly Detection Service (FastAPI + LightGBM)

Layanan Machine Learning berbasis **FastAPI** untuk mendeteksi anomali absensi tutor (`valid`, `needs_revision`, `rejected`) menggunakan model **LightGBM** (`artifacts/anomaly_model.pkl`) dan **Guardrail Deterministik**.

## Struktur Folder

- `artifacts/` — File runtime model (`anomaly_model.pkl` & `feature_metadata.json`).
- `app/schemas.py` — Tahap 1: Skema Pydantic request & response (sinkron dengan Backend `HttpAnomalyDetector`).
- `app/feature_extractor.py` — Tahap 2: Transformasi JSON menjadi 19 fitur angka (`FEATURE_NAMES`).
- `app/guardrail.py` — Tahap 4: Guardrail deterministik untuk kasus batas (mis. durasi 181 menit).
- `app/response_builder.py` — Tahap 5: Penyusunan `validity_reason` & `findings` Bahasa Indonesia.
- `app/main.py` — Entrypoint FastAPI (`GET /health` & `POST /v1/anomaly/analyze`).
- `tests/test_api.py` — Pengujian otomatis endpoint & aturan bisnis.
- `Dockerfile`, `.dockerignore`, `docker-compose.yml` — Konfigurasi container untuk dijalankan langsung oleh tim Fullstack.

## Opsi 1: Menjalankan via Docker Compose (Direkomendasikan untuk Tim Fullstack)

Pastikan Docker Desktop sudah aktif, lalu jalankan dari root folder proyek ini:

```powershell
docker compose up --build -d
```

Untuk mengecek log atau menjalankan unit test di dalam container:

```powershell
docker compose logs -f ai-anomaly
docker compose run --rm ai-anomaly pytest -v
```

Untuk menghentikan container:

```powershell
docker compose down
```

## Opsi 2: Menjalankan Lokal Tanpa Docker (Python `venv`)

```powershell
.\venv\Scripts\Activate.ps1
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Jalankan unit test lokal:

```powershell
.\venv\Scripts\pytest.exe -v
```

## Endpoint & Integrasi dengan Backend Dashboard

- **Health Check:** `GET http://localhost:8000/health`
- **Swagger UI:** `http://localhost:8000/docs`
- **Endpoint Analisis (Backend):** `POST http://localhost:8000/v1/anomaly/analyze`

Pada file `backend/.env` di proyek `mumtaz-bimbel-dashboard`:

- Jika Backend dijalankan lokal (`npm run dev -w backend`):
  ```env
  ANOMALY_SERVICE_URL=http://localhost:8000
  ANOMALY_MODEL_NAME=anomaly-lgbm-v1
  ```
- Jika Backend juga dijalankan di dalam Docker container: gunakan `http://host.docker.internal:8000` (atau nama service `http://ai-anomaly:8000` jika berada di network compose yang sama).
