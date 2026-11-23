# Panduan Implementasi Service FastAPI: Endpoint Generative AI Ringkasan Belajar Orang Tua (`POST /v1/learning-summary/summarize`)

Dokumen ini adalah acuan teknis **end-to-end** untuk membangun endpoint Generative AI di repositori service FastAPI (`AI-MODEL-MUMTAZ`). Seluruh kontrak JSON, batas validasi, timeout, dan perilaku fallback di bawah ini sudah **100% diselaraskan** dengan baseline fullstack yang sudah selesai dan teruji di repo `mumtaz-bimbel-dashboard` (branch `feat/backend-aii`, commit `da7a9ad` → `2b09c05`).

---

## 1. Konteks Masalah Awal, Keputusan Arsitektur, & Solusi Final

### 1.1 Masalah Awal
1. **Kebutuhan fitur Orang Tua**: Orang tua murid ingin memantau apakah anak mereka belajar dengan baik atau perlu pendampingan berdasarkan **materi pembelajaran (`learning_material`)** dan **catatan tutor (`learning_notes`)** di setiap sesi maupun akumulasi satu bulan — tanpa harus membaca dan menyimpulkan seluruh catatan satu per satu secara manual.
2. **Pemisahan peran AI vs Database**: Sempat dipertimbangkan apakah data Dashboard Admin juga harus dipasok oleh service AI. Setelah ditinjau, metrik Dashboard Admin (omzet kotor, jumlah sesi, jumlah murid, honor tutor, grafik pendapatan) murni berupa agregasi deterministik dari PostgreSQL sehingga **tidak cocok dan tidak perlu** melewati service AI.
3. **Kualitas data input untuk Generative AI**: Catatan tutor sebelumnya boleh kosong/singkat sehingga kurang kaya untuk dirangkum AI. Oleh karena itu, di baseline fullstack sebelumnya sudah diterapkan aturan wajib **minimal 100 karakter** untuk `learning_notes` pada sesi baru (sementara sesi lama/legacy di database masih mungkin memiliki `learning_notes: null`).

### 1.2 Keputusan Arsitektur Final
1. **Service AI FastAPI (`AI-MODEL-MUMTAZ`) memiliki tepat 2 endpoint AI**:
   - `POST /v1/anomaly/analyze` *(sudah ada)* — Model ML LightGBM + guardrail deterministik untuk validasi absensi tutor. **Tetap terisolasi penuh dan TIDAK BOLEH menerima `learning_material` maupun `learning_notes`.**
   - `POST /v1/learning-summary/summarize` *(yang akan dibangun berdasarkan panduan ini)* — Endpoint Generative AI untuk merangkum perkembangan belajar anak bagi Orang Tua.
2. **Satu endpoint untuk 2 cakupan (`scope`)**:
   - `scope: "session"` → merangkum tepat **1 sesi** belajar.
   - `scope: "monthly"` → merangkum **seluruh sesi `approved` dalam 1 bulan** (`1..100` sesi).
3. **Hanya sesi `approved` yang diringkas**:
   - Backend dashboard hanya mengirim sesi yang sudah `approved` (lolos validasi `valid` dari Model Anomaly AI atau disetujui manual Admin).
4. **Caching & Invalidasi dikelola di Backend Dashboard (Pendekatan A)**:
   - Service FastAPI **stateless** (tidak perlu mengakses PostgreSQL dan tidak perlu menyimpan cache sendiri).
   - Backend dashboard sudah menyimpan hasil ringkasan di tabel PostgreSQL `learning_summaries` dengan validasi **SHA-256 `source_fingerprint`**. FastAPI hanya dipanggil saat cache belum ada atau berubah (`is_stale: true`), dan endpoint generate di backend sudah dibatasi rate limit **20 req / 15 menit** per akun Orang Tua.
5. **Kontrak output final (tanpa `parent_tips`, dukung multi-subject)**:
   - Field `parent_tips` **dihapus** dari seluruh sistem. Backend memakai `z.strictObject(...)`, sehingga jika FastAPI mengirim key tambahan seperti `parent_tips`, backend akan **menolak** respons sebagai `invalid_output` (`HTTP 503` ke user).
   - Satu sesi dapat mencakup lebih dari 1 mata pelajaran, sehingga request mengirim `subjects: string[]` dan response mengembalikan daftar ringkasan per mata pelajaran di `subjects_covered: { subject_name, highlight }[]`.

---

## 2. Spesifikasi Komunikasi dengan Backend Dashboard

Backend (`backend/src/integrations/learning-summary/http-provider.ts`) sudah memiliki adapter `HttpLearningSummaryProvider` yang siap memanggil FastAPI dengan spesifikasi berikut:

| Komponen | Spesifikasi Eksak di Backend Dashboard |
| --- | --- |
| **Base URL** | `LEARNING_SUMMARY_SERVICE_URL` di `backend/.env` (boleh sama dengan `ANOMALY_SERVICE_URL`, mis. `http://localhost:8000`) |
| **Endpoint** | `POST /v1/learning-summary/summarize` |
| **Content-Type** | Request & Response `application/json` |
| **Timeout Frontend → Backend** | `35.000 ms` (`frontend/src/features/parent/api.ts`) |
| **Timeout Backend → FastAPI** | `30.000 ms` default (`LEARNING_SUMMARY_TIMEOUT_MS=30000`) |
| **Rekomendasi Timeout LLM di FastAPI** | **`22–25 detik`** (harus lebih kecil dari 30 detik agar FastAPI sempat mengembalikan error bersih sebelum backend melakukan `AbortController.abort()`) |
| **Status Sukses** | `HTTP 200` dengan JSON yang 100% lolos schema strict |
| **Status Gagal** | `422` (payload tidak valid), `502`/`503`/`504` (LLM gagal/timeout/output rusak). Backend otomatis memetakan semua kegagalan provider ke pesan aman `503 INTEGRATION_UNAVAILABLE` untuk Orang Tua. |

---

## 3. Kontrak JSON Eksak (Wajib 100% Cocok dengan `@mumtaz/contracts`)

Sumber kebenaran kontrak ada di `packages/contracts/src/learning-summary.ts`.

### 3.1 Request Payload (`Backend → FastAPI`)

| Field | Tipe | Aturan Validasi | Keterangan |
| --- | --- | --- | --- |
| `scope` | `string` (enum) | `"session"` \| `"monthly"` | Menentukan gaya ringkasan (1 sesi vs tren bulanan) |
| `period` | `string` | Regex `^\d{4}-(0[1-9]\|1[0-2])$` | Contoh: `"2026-10"` |
| `student_grade` | `string` | Trimmed, `1..60` karakter | Contoh: `"2 SD"`, `"5 SD"`, `"2 SMP"` (untuk konteks level materi) |
| `sessions` | `array` | Minimal `1`, maksimal `100` item. **Jika `scope === "session"`, wajib tepat `1` item.** | Diurutkan kronologis `lesson_date ASC` oleh backend |
| `sessions[].lesson_date` | `string` | Tanggal kalender valid `YYYY-MM-DD` | Contoh: `"2026-10-01"` |
| `sessions[].subjects` | `string[]` | Minimal `1`, maksimal `5` mapel; tiap string `1..80` karakter | Diurutkan alfabetis oleh backend, mis. `["IPA", "Matematika"]` |
| `sessions[].duration_minutes` | `int` | Integer positif (`> 0`) | Contoh: `90` |
| `sessions[].learning_material` | `string` | Minimal `1` karakter | Materi yang dipelajari |
| `sessions[].learning_notes` | `string \| null` | String atau `null` | **Bisa `null`** pada sesi legacy! |

> **Aturan Privasi (Zero-PII):** Request tidak pernah memuat `student_name`, `school_name`, `tutor_name`, UUID internal, maupun `admin_note`. Pydantic schema sebaiknya memakai `extra="forbid"` agar jika suatu saat ada kebocoran field ekstra, langsung terdeteksi.

#### Contoh Request 1 — `scope: "session"` (dengan `learning_notes` terisi)
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
      "learning_notes": "Siswa lancar mengerjakan soal penjumlahan bersusun dua digit tanpa bantuan. Pada pengurangan dengan teknik meminjam masih perlu didampingi langkah demi langkah agar lebih teliti."
    }
  ]
}
```

#### Contoh Request 2 — `scope: "monthly"` (multi-sesi, multi-subject, + sesi legacy `learning_notes: null`)
```json
{
  "scope": "monthly",
  "period": "2026-10",
  "student_grade": "5 SD",
  "sessions": [
    {
      "lesson_date": "2026-10-05",
      "subjects": ["IPA", "Matematika"],
      "duration_minutes": 90,
      "learning_material": "Pecahan campuran dan gaya gesek",
      "learning_notes": "Siswa antusias berdiskusi tentang contoh gaya gesek sehari-hari dan cepat memahami konsep penjumlahan pecahan campuran. Masih perlu latihan mengubah soal cerita menjadi operasi matematika."
    },
    {
      "lesson_date": "2026-10-12",
      "subjects": ["Bahasa Inggris"],
      "duration_minutes": 60,
      "learning_material": "Simple past tense dan kosakata kegiatan sehari-hari",
      "learning_notes": null
    },
    {
      "lesson_date": "2026-10-20",
      "subjects": ["Matematika"],
      "duration_minutes": 90,
      "learning_material": "Soal cerita pecahan campuran dan desimal",
      "learning_notes": "Kemampuan memahami soal cerita pecahan meningkat dibanding pertemuan sebelumnya. Siswa mulai mandiri membuat langkah penyelesaian, hanya perlu teliti saat menyederhanakan hasil akhir."
    }
  ]
}
```

---

### 3.2 Response Payload (`FastAPI → Backend`, HTTP 200)

Backend memvalidasi response menggunakan `learningSummaryAiResponseSchema = z.strictObject(...)`. **Semua batas dan nama key di bawah ini bersifat WAJIB (exact match):**

| Field | Tipe | Aturan Validasi Ketat (Zod Backend) | Tampilan di UI Orang Tua |
| --- | --- | --- | --- |
| `overall_status` | `string` (enum) | **Hanya** `"very_good"` \| `"good"` \| `"needs_attention"` | Chip status: `"Sangat baik"` (hijau) / `"Berkembang baik"` (biru) / `"Perlu pendampingan"` (oranye) |
| `summary` | `string` | Trimmed, **`1..1000` karakter** (tidak boleh kosong) | Paragraf utama ringkasan belajar |
| `strengths` | `string[]` | Maksimal **`5` item**; tiap item trimmed **`1..240` karakter** (boleh `[]`) | Seksi **Kelebihan** (bullet list) |
| `areas_to_improve` | `string[]` | Maksimal **`5` item**; tiap item trimmed **`1..240` karakter** (boleh `[]`) | Seksi **Perlu latihan** (bullet list) |
| `subjects_covered` | `object[]` | Maksimal **`15` item** (boleh `[]`) | Seksi **Ringkasan per mata pelajaran** (terlipat otomatis jika `> 3` item) |
| `subjects_covered[].subject_name` | `string` | Trimmed, **`1..80` karakter** | Nama mata pelajaran (harus sesuai input `sessions[].subjects`) |
| `subjects_covered[].highlight` | `string` | Trimmed, **`1..240` karakter** | Ringkasan singkat 1 kalimat capaian pada mapel tersebut |
| `model` | `string \| null` *(opsional)* | Jika ada dan bukan `null`: trimmed, **`1..80` karakter** | Tidak ditampilkan ke Orang Tua; disimpan ke kolom audit DB `learning_summaries.model` |

> **Peringatan Strict Object:**
> - **JANGAN** menambahkan key ekstra apa pun di root response maupun di dalam item `subjects_covered` (misalnya `parent_tips`, `scope`, `period`, `tokens_used`, `provider`, `latency_ms`). Key ekstra langsung ditolak oleh `z.strictObject` di backend!
> - **JANGAN** mengembalikan string kosong `""` di dalam `strengths`, `areas_to_improve`, `subject_name`, atau `highlight` (semua item wajib `min(1)` setelah `.strip()`).

#### Contoh Response Valid (`HTTP 200`)
```json
{
  "overall_status": "good",
  "summary": "Selama Oktober 2026, Ananda menunjukkan perkembangan belajar yang baik lintas Matematika, IPA, dan Bahasa Inggris. Pemahaman soal cerita pecahan campuran meningkat dibanding awal bulan, dan Ananda aktif saat berdiskusi materi IPA.",
  "strengths": [
    "Cepat memahami konsep penjumlahan pecahan campuran",
    "Antusias dan aktif berdiskusi pada materi gaya gesek",
    "Mulai mandiri menyusun langkah penyelesaian soal cerita"
  ],
  "areas_to_improve": [
    "Ketelitian saat menyederhanakan hasil akhir pecahan"
  ],
  "subjects_covered": [
    {
      "subject_name": "Matematika",
      "highlight": "Pemahaman pecahan campuran dan soal cerita meningkat; perlu lebih teliti saat menyederhanakan jawaban akhir."
    },
    {
      "subject_name": "IPA",
      "highlight": "Memahami konsep gaya gesek dan aktif memberikan contoh dalam kehidupan sehari-hari."
    },
    {
      "subject_name": "Bahasa Inggris",
      "highlight": "Mengikuti pembelajaran simple past tense dan kosakata kegiatan sehari-hari (catatan detail tutor belum tersedia)."
    }
  ],
  "model": "gemini-2.5-flash"
}
```

---

## 4. Struktur Folder yang Direkomendasikan di Repo FastAPI (`AI-MODEL-MUMTAZ`)

Tambahkan paket terpisah `app/learning_summary/` di samping modul anomaly yang sudah ada, sehingga kode ML Anomaly tetap bersih dan tidak tersentuh:

```text
AI-MODEL-MUMTAZ/
├── app/
│   ├── main.py                        # Daftarkan router learning_summary (di samping /v1/anomaly/analyze & /health)
│   ├── ...                            # Modul anomaly existing (JANGAN diubah kontraknya)
│   └── learning_summary/
│       ├── __init__.py
│       ├── config.py                  # Env var LLM (provider/API key, model, timeout, temperature)
│       ├── schemas.py                 # Pydantic v2 Request & Response (mirror Zod @mumtaz/contracts)
│       ├── prompt_builder.py          # System prompt + user prompt builder (session vs monthly, legacy null)
│       ├── llm_client.py              # Adapter pemanggilan LLM (Gemini / OpenAI-compatible) + JSON schema
│       ├── postprocessor.py           # Sanitizer & guardrail deterministik agar tidak pernah melanggar batas Zod
│       └── router.py                  # APIRouter: POST /v1/learning-summary/summarize
├── tests/
│   ├── test_api.py                    # Test anomaly existing
│   └── test_learning_summary.py       # Unit & API tests endpoint learning summary (offline mock LLM)
├── .env.example
└── requirements.txt
```

---

## 5. Panduan Implementasi Detail per Modul

### 5.1 Konfigurasi Environment (`app/learning_summary/config.py`)

Tambahkan variabel berikut di `.env` service FastAPI (sesuaikan dengan provider LLM pilihan, misalnya **Google Gemini API** via `google-genai` atau **OpenAI / Groq / OpenRouter** via `openai` SDK):

```env
# Contoh jika memakai Gemini (google-genai)
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_api_key_here
LEARNING_SUMMARY_MODEL=gemini-2.5-flash
LEARNING_SUMMARY_LLM_TIMEOUT_SECONDS=24
LEARNING_SUMMARY_TEMPERATURE=0.25
```

> **Catatan pemilihan model & parameter**:
> - Gunakan model cepat yang mendukung **Structured Output (JSON Schema)** (mis. `gemini-2.5-flash` atau `gpt-4o-mini`) agar latensi stabil di kisaran **1.5–5 detik** (jauh di bawah batas timeout 30 detik backend).
> - Set `temperature` rendah (`0.2` – `0.3`) agar ringkasan tetap faktual sesuai catatan tutor dan tidak berhalusinasi.
> - Set `timeout` klien LLM di `22–25` detik agar masih ada ruang 5+ detik sebelum backend memutus koneksi di detik ke-30.

---

### 5.2 Pydantic v2 Schemas (`app/learning_summary/schemas.py`)

Schema ini dibuat **identik** dengan `packages/contracts/src/learning-summary.ts` termasuk `extra="forbid"`:

```python
from datetime import date
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SummaryScope = Literal["session", "monthly"]
OverallStatus = Literal["very_good", "good", "needs_attention"]


class LearningSummarySessionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lesson_date: date  # Otomatis validasi format & tanggal kalender valid YYYY-MM-DD
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


class LearningSummaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: SummaryScope
    period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    student_grade: str = Field(min_length=1, max_length=60)
    sessions: list[LearningSummarySessionInput] = Field(min_length=1, max_length=100)

    @field_validator("student_grade")
    @classmethod
    def strip_grade(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("student_grade tidak boleh kosong")
        return trimmed

    @model_validator(mode="after")
    def validate_scope_session_count(self) -> "LearningSummaryRequest":
        if self.scope == "session" and len(self.sessions) != 1:
            raise ValueError("Scope 'session' wajib mengirim tepat 1 sesi")
        return self


class SubjectHighlight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_name: str = Field(min_length=1, max_length=80)
    highlight: str = Field(min_length=1, max_length=240)


class LearningSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall_status: OverallStatus
    summary: str = Field(min_length=1, max_length=1000)
    strengths: list[str] = Field(default_factory=list, max_length=5)
    areas_to_improve: list[str] = Field(default_factory=list, max_length=5)
    subjects_covered: list[SubjectHighlight] = Field(default_factory=list, max_length=15)
    model: Optional[str] = Field(default=None, min_length=1, max_length=80)
```

---

### 5.3 Prompt Engineering (`app/learning_summary/prompt_builder.py`)

Aturan penting saat menyusun prompt agar hasil LLM selalu berkualitas, aman, dan ramah untuk orang tua Indonesia:

1. **Bahasa & Nada Bicara**:
   - Bahasa Indonesia yang hangat, suportif, sopan, jelas, dan mudah dipahami orang tua non-teknis.
   - Gunakan sebutan **"Ananda"** (jangan pernah mengarang nama murid, nama tutor, atau nama sekolah karena payload memang zero-PII).
   - Jangan gunakan format tanggal mentah `YYYY-MM-DD` di kalimat ringkasan; gunakan gaya natural Indonesia (mis. "awal Oktober", "pertemuan pertama", "sepanjang Oktober 2026").
2. **Anti-Halusinasi (Grounded pada Input)**:
   - Hanya simpulkan fakta yang benar-benar tertulis di `learning_material`, `learning_notes`, `subjects`, `duration_minutes`, dan `student_grade`.
   - Jika `learning_notes` bernilai `null` atau kosong pada suatu sesi (sesi legacy), rangkum secara jujur dari materi & mapel yang dipelajari tanpa mengarang kelebihan/kekurangan yang tidak ada buktinya. Jika tidak ada poin kelemahan yang tertulis, kembalikan `areas_to_improve: []`.
3. **Panduan Klasifikasi `overall_status`**:
   - `"very_good"`: Catatan tutor dominan sangat positif — Ananda menguasai materi dengan cepat/mandiri, antusias, dan hampir tidak ada hambatan berarti.
   - `"good"`: Perkembangan positif dan wajar — Ananda memahami materi inti meski ada 1–2 bagian yang masih perlu latihan/ketelitian. *(Gunakan `"good"` juga sebagai default aman bila catatan singkat/netral atau `learning_notes: null`.)*
   - `"needs_attention"`: Catatan tutor secara jelas menunjukkan kesulitan berulang, kurang fokus signifikan, atau tertinggal dalam memahami konsep dasar sehingga perlu pendampingan lebih.
4. **Panduan `scope: "session"` vs `scope: "monthly"`**:
   - **`session`**: Ringkas 2–3 kalimat fokus pada materi yang dibahas di sesi tersebut, hal yang sudah dikuasai Ananda, dan hal yang masih perlu dilatih. `strengths` 1–3 poin, `areas_to_improve` 0–3 poin, `subjects_covered` 1 item per mata pelajaran di sesi itu.
   - **`monthly`**: Sintesis keseluruhan perkembangan selama bulan `period` (`2–4` kalimat): gambarkan konsistensi belajar, progres antar sesi (jika ada perkembangan dari awal ke akhir bulan), dan fokus umum. `strengths` 1–5 poin terpenting, `areas_to_improve` 0–5 poin terpenting, `subjects_covered` gabungkan per mata pelajaran unik (1 item per mapel unik, maksimal 15).
5. **Larangan Mutlak**:
   - **JANGAN** sertakan saran untuk orang tua (`parent_tips`) sebagai field JSON.
   - **JANGAN** sebut kata "AI", "berdasarkan JSON", atau metadata teknis sistem.

#### Contoh System Prompt yang Direkomendasikan
```python
SYSTEM_PROMPT = """
Kamu adalah asisten pendidikan untuk bimbingan belajar Mumtaz Bimbel yang bertugas merangkum perkembangan belajar anak bagi orang tua dalam Bahasa Indonesia yang hangat, jelas, objektif, dan mudah dipahami.

ATURAN WAJIB:
1. Gunakan sebutan "Ananda" untuk merujuk ke murid. JANGAN mengarang nama murid, nama tutor, atau nama sekolah.
2. Seluruh isi ringkasan WAJIB 100% berdasar pada data sesi yang diberikan (materi, catatan tutor, mata pelajaran, durasi, jenjang kelas). Jangan mengarang fakta yang tidak ada di catatan.
3. Jika sebuah sesi memiliki `learning_notes: null` (catatan tutor belum tersedia), rangkum hanya dari materi dan mata pelajaran yang dipelajari secara jujur tanpa mengada-ada kekurangan.
4. Keluarkan HANYA objek JSON valid sesuai schema:
   - overall_status: "very_good" | "good" | "needs_attention"
   - summary: string Bahasa Indonesia (maks 900 karakter)
   - strengths: list string poin kelebihan (0..5 poin, maks 220 karakter/poin)
   - areas_to_improve: list string poin yang perlu dilatih (0..5 poin, maks 220 karakter/poin; boleh [] jika tidak ada hambatan di catatan)
   - subjects_covered: list objek {"subject_name": string, "highlight": string (maks 220 karakter)} — tepat 1 entri per mata pelajaran unik yang ada di input (maks 15).
5. JANGAN sertakan field tambahan seperti `parent_tips` atau metadata lainnya.
6. Kriteria `overall_status`:
   - "very_good": pemahaman sangat baik/mandiri dan hampir tanpa hambatan.
   - "good": perkembangan baik/stabil meski ada beberapa hal yang masih perlu latihan, atau catatan bersifat netral/singkat.
   - "needs_attention": catatan jelas menunjukkan kesulitan berulang, hambatan konsep dasar, atau fokus yang perlu perhatian khusus.
""".strip()
```

---

### 5.4 Post-Processor & Guardrail Deterministik (`app/learning_summary/postprocessor.py`)

Sama seperti prinsip **Tahap 4 Guardrail** pada endpoint anomaly, **jangan pernah mempercayai output mentah LLM langsung** tanpa sanitasi deterministik sebelum dikembalikan ke backend!

Buat fungsi `sanitize_llm_output(raw: dict, allowed_subjects: list[str], model_name: str | None) -> LearningSummaryResponse` yang melakukan:

1. **Whitelisting field**: hanya ambil 5 field inti (`overall_status`, `summary`, `strengths`, `areas_to_improve`, `subjects_covered`) + `model`. Key liar seperti `parent_tips` otomatis dibuang.
2. **Validasi `overall_status`**: pastikan masuk `{"very_good", "good", "needs_attention"}`; jika tidak valid, lempar error `InvalidLLMOutputError`.
3. **Trim & Truncate aman** (dengan `...` jika melebihi batas karakter Zod):
   - `summary`: `.strip()`, maks `1000` karakter (jika kosong → lempar error).
   - `strengths`: buang item kosong, dedup case-insensitive, truncate tiap item maks `240` karakter, potong maks `5` item.
   - `areas_to_improve`: buang item kosong, dedup case-insensitive, truncate tiap item maks `240` karakter, potong maks `5` item.
   - `subjects_covered`: buang item tanpa `subject_name` atau `highlight`, dedup berdasarkan `subject_name.lower()`, truncate `subject_name` maks `80` karakter dan `highlight` maks `240` karakter, potong maks `15` item.
   - `model`: `.strip()`, truncate maks `80` karakter, atau `None` jika kosong.
4. **Final Pydantic Validation**: kembalikan `LearningSummaryResponse(...)` agar dipastikan 100% lolos kontrak sebelum dikirim sebagai HTTP 200.

```python
from .schemas import LearningSummaryResponse, SubjectHighlight


def _truncate(text: str, max_len: int) -> str:
    cleaned = " ".join(text.strip().split())
    if len(cleaned) <= max_len:
        return cleaned
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


def sanitize_llm_output(raw: dict, model_name: str | None) -> LearningSummaryResponse:
    overall_status = raw.get("overall_status")
    if overall_status not in ("very_good", "good", "needs_attention"):
        raise ValueError(f"overall_status tidak valid: {overall_status!r}")

    raw_summary = raw.get("summary")
    if not isinstance(raw_summary, str) or not raw_summary.strip():
        raise ValueError("summary kosong dari LLM")
    summary = _truncate(raw_summary, 1000)

    strengths = _clean_string_list(raw.get("strengths"), max_items=5, max_len=240)
    areas_to_improve = _clean_string_list(raw.get("areas_to_improve"), max_items=5, max_len=240)

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
            if key in seen_subjects:
                continue
            seen_subjects.add(key)
            subjects_covered.append(
                SubjectHighlight(subject_name=clean_name, highlight=clean_highlight)
            )
            if len(subjects_covered) >= 15:
                break

    clean_model = _truncate(model_name, 80) if model_name and model_name.strip() else None

    return LearningSummaryResponse(
        overall_status=overall_status,
        summary=summary,
        strengths=strengths,
        areas_to_improve=areas_to_improve,
        subjects_covered=subjects_covered,
        model=clean_model,
    )
```

---

### 5.5 Pemanggilan LLM (`app/learning_summary/llm_client.py`)

Gunakan **Structured Outputs** bawaan SDK LLM sehingga output selalu berbentuk JSON murni tanpa markdown code fence (` ```json `):

- **Jika memakai Google Gemini (`google-genai`)**:
  - Pass `response_mime_type="application/json"` dan `response_schema=LLMOutputSchema` (Pydantic model dengan 5 field: `overall_status`, `summary`, `strengths`, `areas_to_improve`, `subjects_covered` — tanpa `model` karena `model` diisi deterministik dari config server).
  - Gunakan `asyncio.wait_for(..., timeout=settings.llm_timeout_seconds)` (atau client async `client.aio.models.generate_content`) agar request yang lambat tidak memblokir worker FastAPI.
- **Jika memakai OpenAI / OpenAI-compatible SDK (`openai`)**:
  - Gunakan `AsyncOpenAI(api_key=..., timeout=settings.llm_timeout_seconds)` dan `client.beta.chat.completions.parse(..., response_format=LLMOutputSchema)` atau `response_format={"type": "json_object"}`.
- **Jangan pernah membocorkan API key atau stack trace** pada respons HTTP error. Tangkap timeout (`TimeoutError`) → kembalikan HTTP `504`; tangkap error upstream LLM / JSON rusak → kembalikan HTTP `502` / `503` dengan pesan generik.

---

### 5.6 Router & Registrasi di `app/main.py`

```python
# app/learning_summary/router.py
from fastapi import APIRouter, HTTPException
from .schemas import LearningSummaryRequest, LearningSummaryResponse
from .llm_client import summarize_with_llm, LLMTimeoutError, LLMProviderError
from .postprocessor import sanitize_llm_output

router = APIRouter(prefix="/v1/learning-summary", tags=["learning-summary"])


@router.post("/summarize", response_model=LearningSummaryResponse)
async def summarize_learning(payload: LearningSummaryRequest) -> LearningSummaryResponse:
    try:
        raw_output, model_used = await summarize_with_llm(payload)
        return sanitize_llm_output(raw_output, model_used)
    except LLMTimeoutError:
        raise HTTPException(status_code=504, detail="Layanan LLM melebihi batas waktu")
    except (LLMProviderError, ValueError):
        raise HTTPException(status_code=502, detail="Gagal menghasilkan ringkasan belajar")
```

Lalu di `app/main.py` (service FastAPI yang sudah ada):
```python
from app.learning_summary.router import router as learning_summary_router

app.include_router(learning_summary_router)
```

> **Cek `/health`**: Pastikan `GET /health` tetap `200 OK` (mis. menambahkan info non-sensitif `"learning_summary_configured": bool(settings.api_key)` jika diinginkan) tanpa memanggil API LLM saat health check.

---

## 6. Checklist Pengujian Wajib di Repo FastAPI (`tests/test_learning_summary.py`)

Buat minimal 7 test `pytest` menggunakan `httpx.AsyncClient` / `TestClient` dengan **mock LLM** (agar test cepat, deterministik, dan tidak menghabiskan kuota token):

1. **Happy path `scope: "session"`**: 1 sesi → `200`, respons lolos `LearningSummaryResponse`, tidak ada key `parent_tips`.
2. **Happy path `scope: "monthly"` multi-subject**: 3 sesi dengan 4 mapel berbeda → `200`, `subjects_covered` memuat seluruh mapel tanpa duplikat.
3. **Legacy `learning_notes: null`**: request dengan `learning_notes: null` diterima (`200`) dan prompt tidak crash saat formatting.
4. **Validasi `scope: "session"` dengan > 1 sesi**: ditolak `422`.
5. **Validasi zero-PII (`extra="forbid"`)**: request berisi `student_name` atau `tutor_name` ditolak `422`.
6. **Guardrail post-processor**: mock LLM mengembalikan `summary` 1.500 karakter, 7 `strengths`, string kosong, dan key liar `parent_tips` → endpoint tetap menghasilkan `200` yang bersih (`len(summary) <= 1000`, `len(strengths) <= 5`, tanpa `parent_tips`).
7. **Error & timeout handling**: mock LLM raise `LLMTimeoutError` → `504`; mock LLM raise `LLMProviderError` → `502`, tanpa membocorkan API key.

---

## 7. Checklist Uji Integrasi End-to-End dengan `mumtaz-bimbel-dashboard`

Setelah endpoint FastAPI selesai dan berjalan di lokal (mis. `http://localhost:8000`):

1. **Jalankan migration DB di dashboard** (membuat tabel `learning_summaries`):
   ```powershell
   npm run db:migrate -w backend
   ```
2. **Aktifkan env di `C:\mumtaz-bimbel-dashboard\backend\.env`**:
   ```env
   LEARNING_SUMMARY_SERVICE_URL=http://localhost:8000
   LEARNING_SUMMARY_MODEL_NAME=
   LEARNING_SUMMARY_TIMEOUT_MS=30000
   ```
3. **Verifikasi startup log backend**: pastikan log `api_listening` menampilkan:
   ```json
   "learning_summary_provider": "genai_fastapi"
   ```
4. **Smoke test langsung ke FastAPI** (PowerShell):
   ```powershell
   $body = @{
     scope = "session"
     period = "2026-10"
     student_grade = "2 SD"
     sessions = @(
       @{
         lesson_date = "2026-10-01"
         subjects = @("Matematika")
         duration_minutes = 90
         learning_material = "Penjumlahan dan pengurangan bilangan dua digit"
         learning_notes = "Siswa lancar penjumlahan dua digit, pengurangan dengan teknik meminjam masih perlu latihan perlahan."
       }
     )
   } | ConvertTo-Json -Depth 5

   Invoke-RestMethod -Method Post -Uri "http://localhost:8000/v1/learning-summary/summarize" -ContentType "application/json" -Body $body
   ```
5. **Uji dari UI Orang Tua di Dashboard**:
   - Login sebagai Orang Tua → buka **Progress Anak** → pilih periode yang memiliki sesi `approved`.
   - Klik **Buat ringkasan bulanan** → pastikan kartu menampilkan badge status, paragraf ringkasan, Kelebihan, Perlu latihan, dan Ringkasan per mata pelajaran.
   - Refresh halaman / pindah ke **Riwayat Pembelajaran** lalu kembali → pastikan ringkasan langsung muncul dari cache PostgreSQL (cek log FastAPI: tidak ada request baru).
   - Klik **Ringkas sesi ini** pada salah satu sesi di timeline → pastikan blok ringkasan muncul di bawah materi & catatan tutor tanpa menyembunyikan catatan asli.
   - Login sebagai Admin, ubah sedikit catatan pada sesi `approved` tersebut, lalu kembali ke akun Orang Tua → pastikan badge **`Ada sesi/catatan baru`** dan tombol **`Perbarui ringkasan`** muncul, lalu klik untuk menimpa cache dengan ringkasan terbaru.
