# Overview Modifikasi — Fitur Ringkasan Belajar AI Orang Tua (Parent Learning Summary)

Dokumen ini merangkum secara detail **apa saja yang baru dibuat dan dimodifikasi** pada repo `mumtaz-bimbel-dashboard` (branch `feat/backend-aii`, commit `da7a9ad` → `2b09c05`) serta **tujuan masing-masing perubahan**, sebagai baseline fullstack sebelum implementasi endpoint Generative AI di service FastAPI (`AI-MODEL-MUMTAZ`).

---

## 1. Ringkasan Arsitektur & Keputusan Final

1. **Service AI FastAPI hanya memiliki 2 endpoint**:
   - `POST /v1/anomaly/analyze` *(existing)* — validasi anomali sesi absensi (Model ML). **Tidak pernah menerima** `learning_material` maupun `learning_notes`.
   - `POST /v1/learning-summary/summarize` *(baru)* — ringkasan perkembangan belajar anak untuk Orang Tua berbasis Generative AI. Satu endpoint menangani dua cakupan: `scope: "session"` (per sesi) dan `scope: "monthly"` (ringkasan bulanan).
2. **Dashboard Admin tetap query langsung ke PostgreSQL** — tidak dipindah ke endpoint AI karena seluruh metrik dashboard adalah agregasi deterministik (omzet, jumlah sesi, jumlah murid, honor).
3. **Hanya sesi `approved` yang dapat diringkas**:
   - Sesi `approved` adalah sesi yang sudah lolos validasi (`valid` dari Model Anomaly AI atau disetujui manual oleh Admin).
   - Sesi `pending`, `revision_requested`, dan `rejected` tidak pernah dikirim ke Generative AI maupun diekspos ke Orang Tua.
4. **Pendekatan A — Cache Persisten di PostgreSQL (`learning_summaries`)**:
   - Hasil ringkasan disimpan ke PostgreSQL agar Orang Tua tidak menunggu ulang LLM dan biaya token hemat.
   - Invalidasi cache menggunakan **SHA-256 `source_fingerprint`** dari materi, catatan tutor, daftar mata pelajaran, durasi, dan jenjang kelas. Jika ada sesi baru disetujui atau Admin mengubah materi/catatan, cache otomatis ditandai `is_stale: true` sehingga Orang Tua mendapat tombol **Perbarui ringkasan**.
5. **Multi-subject & Tanpa `parent_tips`**:
   - Satu sesi bisa mencakup beberapa mata pelajaran, sehingga payload keluar mengirim `subjects: string[]` dan response AI mengembalikan `subjects_covered: { subject_name, highlight }[]`.
   - Field `parent_tips` **dihapus** di semua layer (kontrak, DB, backend, UI) sesuai keputusan produk.
   - Jika ringkasan bulanan mencakup `> 3` mata pelajaran, daftar di UI otomatis dilipat (*collapsible*) dengan tombol `Lihat semua (N mapel)`.

---

## 2. Kontrak Final Endpoint AI (`POST /v1/learning-summary/summarize`)

Backend dashboard sudah siap mengirim request dan memvalidasi response sesuai kontrak Zod ketat di `packages/contracts/src/learning-summary.ts`.

### A. Request JSON (Backend Dashboard → FastAPI)

**Contoh `scope: "monthly"`** (1–100 sesi `approved` dalam satu bulan):
```json
{
  "scope": "monthly",
  "period": "2026-10",
  "student_grade": "2 SD",
  "sessions": [
    {
      "lesson_date": "2026-10-01",
      "subjects": ["Matematika"],
      "duration_minutes": 90,
      "learning_material": "Penjumlahan dan pengurangan bilangan dua digit",
      "learning_notes": "Siswa lancar penjumlahan, pengurangan dengan meminjam masih perlu latihan."
    },
    {
      "lesson_date": "2026-10-31",
      "subjects": ["IPA", "Matematika"],
      "duration_minutes": 90,
      "learning_material": "Perkalian dasar 1–5 dan sifat benda",
      "learning_notes": null
    }
  ]
}
```

**Contoh `scope: "session"`** (wajib tepat 1 sesi):
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
      "learning_notes": "Siswa lancar penjumlahan, pengurangan dengan meminjam masih perlu latihan."
    }
  ]
}
```

> **Catatan Zero-PII & Legacy Data**:
> - Request **tidak pernah** menyertakan `student_name`, `school_name`, `tutor_name`, UUID internal, maupun `admin_note`.
> - `learning_notes` dapat bernilai `null` (untuk sesi lama sebelum aturan minimal 100 karakter berlaku). FastAPI harus tetap bisa merangkum berdasarkan `learning_material` dan `subjects` saat `learning_notes` kosong/null.

### B. Response JSON (FastAPI → Backend Dashboard)

```json
{
  "overall_status": "good",
  "summary": "Ananda menunjukkan perkembangan yang baik sepanjang Oktober 2026. Pemahaman penjumlahan dan perkalian dasar sudah lancar, sementara pengurangan dengan teknik meminjam masih perlu latihan rutin.",
  "strengths": [
    "Cepat memahami penjumlahan bilangan dua digit",
    "Antusias saat latihan perkalian dasar"
  ],
  "areas_to_improve": [
    "Ketelitian pada soal pengurangan dengan teknik meminjam"
  ],
  "subjects_covered": [
    {
      "subject_name": "Matematika",
      "highlight": "Penjumlahan dan perkalian dasar 1–5 lancar; pengurangan meminjam perlu latihan lanjutan."
    },
    {
      "subject_name": "IPA",
      "highlight": "Mulai memahami klasifikasi sifat benda padat dan cair."
    }
  ],
  "model": "gemini-2.5-flash"
}
```

**Aturan Validasi Response (strictObject — field ekstra seperti `parent_tips` akan ditolak!):**
- `overall_status`: `"very_good"` | `"good"` | `"needs_attention"`
- `summary`: string trimmed, `1..1000` karakter
- `strengths`: array string (`1..240` karakter per item), maksimal `5` item (boleh `[]`)
- `areas_to_improve`: array string (`1..240` karakter per item), maksimal `5` item (boleh `[]`)
- `subjects_covered`: array `{ subject_name (1..80), highlight (1..240) }`, maksimal `15` item (boleh `[]`)
- `model`: opsional / nullable string (`1..80` karakter), hanya disimpan untuk audit DB internal (tidak pernah dikirim ke Orang Tua)

---

## 3. Daftar Detail File yang Dibuat & Dimodifikasi

### A. Layer Kontrak (`packages/contracts`) — Commit `da7a9ad`

| File | Status | Apa yang Diubah & Untuk Apa |
| --- | --- | --- |
| `packages/contracts/src/learning-summary.ts` | **Baru** | Mendefinisikan semua Zod schema & TypeScript type bersama: `learningSummaryAiRequestSchema`, `learningSummaryAiResponseSchema`, `learningSummaryViewSchema`, `parentLearningSummariesResponseSchema`, `generateMonthlySummaryRequestSchema`, `generateMonthlySummaryResponseSchema`, dan `generateSessionSummaryResponseSchema`. Menjadi sumber kebenaran tunggal antara backend, frontend, dan kontrak FastAPI. |
| `packages/contracts/src/index.ts` | **Dimodifikasi** | Mengekspor seluruh schema & type dari `./learning-summary.js` agar dapat diimpor dari `@mumtaz/contracts`. |
| `packages/contracts/tests/learning-summary.test.ts` | **Baru** | 9 unit test untuk memverifikasi dukungan multi-subject, `learning_notes: null`, penolakan `scope: 'session'` dengan >1 sesi, penolakan field PII tambahan, penolakan `parent_tips`, batas panjang teks/array, dan penolakan kebocoran field audit (`provider`, `model`, `admin_note`). |

---

### B. Layer Database, Migration, & Backend (`backend`) — Commit `3b67cc1`

| File | Status | Apa yang Diubah & Untuk Apa |
| --- | --- | --- |
| `backend/src/db/schema.ts` | **Dimodifikasi** | Menambahkan definisi tabel Drizzle `learningSummaries` (`learning_summaries`) lengkap dengan kolom `scope`, `student_id` (FK `cascade`), `period`, `lesson_session_id` (nullable FK `cascade`), `source_fingerprint`, `overall_status`, `summary`, `strengths` (`jsonb`), `areas_to_improve` (`jsonb`), `subjects_covered` (`jsonb`), `provider`, `model`, `generated_at`, `updated_at`; 4 `CHECK` constraints; 2 partial unique index (`learning_summaries_session_key` & `learning_summaries_monthly_key`); serta index `learning_summaries_student_period_idx`. |
| `backend/drizzle/0010_learning_summaries.sql` | **Baru** | Migration SQL PostgreSQL untuk membuat tabel `learning_summaries`, foreign key, constraint, dan partial unique index di Neon / PostgreSQL / PGlite. |
| `backend/drizzle/meta/_journal.json` | **Dimodifikasi** | Mendaftarkan entri `idx: 10` (`0010_learning_summaries`) agar Drizzle migrator menjalankan migration baru secara otomatis. |
| `backend/src/config/env.ts` | **Dimodifikasi** | Menambahkan 3 env var opsional: `LEARNING_SUMMARY_SERVICE_URL` (`optionalUrl`), `LEARNING_SUMMARY_MODEL_NAME` (`optionalString`), `LEARNING_SUMMARY_TIMEOUT_MS` (default `30000` ms), dan status `learningSummaryProvider` (`'genai_fastapi' \| 'not_configured'`) pada `integrationStatus(env)`. |
| `backend/.env.example` | **Dimodifikasi** | Mendokumentasikan bagian `# 5. Generative AI Learning Summary` agar developer tahu variabel env yang perlu diisi saat mengaktifkan endpoint FastAPI. |
| `backend/src/integrations/learning-summary/types.ts` | **Baru** | Mendefinisikan interface `LearningSummaryProvider` dan class `LearningSummaryProviderError` (`timeout`, `request_failed`, `invalid_output`) agar layanan tidak terikat langsung pada implementasi HTTP dan mudah di-mock saat testing. |
| `backend/src/integrations/learning-summary/http-provider.ts` | **Baru** | Implementasi `HttpLearningSummaryProvider` yang memanggil `POST ${baseUrl}/v1/learning-summary/summarize` dengan `AbortSignal`, validasi Zod payload keluar & response masuk, serta pembungkusan error generik tanpa membocorkan URL internal service AI. |
| `backend/src/integrations/learning-summary/create-provider.ts` | **Baru** | Factory `createLearningSummaryProvider(env)` yang mengembalikan `HttpLearningSummaryProvider` bila `LEARNING_SUMMARY_SERVICE_URL` diset, atau `null` bila belum dikonfigurasi (tidak ada fake success di production). |
| `backend/src/services/learning-summary/learning-summary-service.ts` | **Baru** | Logika bisnis inti:<br>• `computeSummaryFingerprint`: hash SHA-256 deterministik dari data sumber.<br>• `getParentLearningSummaries`: membaca cache bulanan & per sesi untuk `GET /summaries`, menandai `is_stale`, dan memastikan bila `approved_session_count === 0` (mis. semua sesi dihapus/ditolak) selalu mengembalikan `monthly: null` & `sessions: {}` tanpa membocorkan cache lama.<br>• `generateMonthlyLearningSummary`: validasi minimal 1 sesi `approved` (jika 0 → `422`), cek cache segar (`cached: true`), panggil provider dengan timeout, simpan/timpa via `ON CONFLICT DO UPDATE`, gunakan `grade` dari sesi `approved` terakhir pada bulan tersebut agar promosi kelas di masa depan tidak memicu false stale.<br>• `generateSessionLearningSummary`: validasi sesi milik anak & berstatus `approved` (jika tidak → `404`), cek cache segar, panggil provider, upsert sambil memperbarui `student_id` & `period` bila sesi pernah dipindahkan Admin. |
| `backend/src/auth/rate-limit.ts` | **Dimodifikasi** | Menambahkan `createLearningSummaryRateLimiter` (batas 20 request / 15 menit per akun Orang Tua/IP, `skipSuccessfulRequests: false`) untuk melindungi kuota token LLM dari spam klik. |
| `backend/src/routes/parent.ts` | **Dimodifikasi** | Mendaftarkan 3 endpoint Orang Tua (semua dilindungi `requireRole('parent')`, `assertParentLinked`, dan CSRF pada `POST`):<br>• `GET /parent/students/:student_id/summaries?period=YYYY-MM`<br>• `POST /parent/students/:student_id/summaries/monthly` (rate-limited)<br>• `POST /parent/students/:student_id/sessions/:session_id/summary` (rate-limited) |
| `backend/src/app.ts` | **Dimodifikasi** | Menambahkan `learningSummaryProvider?: LearningSummaryProvider \| null` pada `AppDependencies` dan meneruskannya ke `parentRouter`. |
| `backend/src/server.ts` | **Dimodifikasi** | Menginisialisasi `createLearningSummaryProvider(env)`, menyuntikkannya ke `createApp`, dan mencatat `learning_summary_provider` di log startup server. |
| `backend/tests/helpers/test-app.ts` | **Dimodifikasi** | Menambahkan opsi `learningSummaryProvider` pada `createTestApp` agar test integrasi bisa menyuntikkan spy/failing provider atau `null`. |
| `backend/tests/learning-summary.test.ts` | **Baru** | 7 suite test (unit `HttpLearningSummaryProvider` + integrasi PGlite): RBAC `403`, cache hit/miss, zero-PII check, legacy `learning_notes: null`, stale detection & overwrite setelah edit catatan, proteksi kebocoran cache saat 0 sesi approved, `404` sesi non-approved, `422` bulan kosong, serta `503` bila provider belum diset / gagal sementara `GET` tetap `200`. |

---

### C. Layer Frontend & Fake Backend (`frontend`) — Commit `2b09c05`

| File | Status | Apa yang Diubah & Untuk Apa |
| --- | --- | --- |
| `frontend/src/lib/query-keys.ts` | **Dimodifikasi** | Menambahkan `queryKeys.parent.summaries(studentId, period)` agar cache TanStack Query terisolasi per anak dan per periode. |
| `frontend/src/features/parent/api.ts` | **Dimodifikasi** | Menambahkan `fetchParentSummaries`, `generateMonthlySummary`, dan `generateSessionSummary`. Kedua `POST` generate memakai override `{ timeout: 35_000 }` (> batas 30 detik backend) agar tidak premature timeout saat LLM memproses respons. |
| `frontend/src/features/parent/learning-summary-card.tsx` | **Baru** | Komponen UI untuk Orang Tua:<br>• `MonthlyLearningSummaryCard`: kartu ringkasan bulanan di halaman Progress Anak (empty state 0 sesi, tombol `Buat ringkasan bulanan`, hasil lengkap dengan status chip `Sangat baik` / `Berkembang baik` / `Perlu pendampingan`, seksi `Kelebihan` & `Perlu latihan`, daftar `Ringkasan per mata pelajaran` yang otomatis terlipat jika `> 3` mapel, penanda `Ada sesi/catatan baru` + `Perbarui ringkasan`, timestamp + disclaimer, dan inline alert + `Coba lagi`).<br>• `SessionLearningSummaryBlock`: tombol `Ringkas sesi ini` dan blok ringkasan ringkas per sesi di dalam timeline tanpa pernah menyembunyikan materi & catatan asli tutor. |
| `frontend/src/features/parent/parent-pages.tsx` | **Dimodifikasi** | Menambahkan hook `useParentSummaries` yang menyinkronkan hasil `POST` langsung ke cache TanStack Query (`setQueryData`) dan melacak state loading/error per `sessionId`. Memasang `MonthlyLearningSummaryCard` di `ParentDashboardPage` serta `SessionLearningSummaryBlock` di `Timeline` (`ParentDashboardPage` & `ParentHistoryPage`). |
| `frontend/src/test/fake-api/learning-summary-fake.ts` | **Baru** | Store in-memory untuk mensimulasikan caching, deteksi stale, generate bulanan & per sesi, dan kegagalan `503` pada test UI offline. |
| `frontend/src/test/fake-api/fake-backend.ts` | **Dimodifikasi** | Menambahkan handler untuk 3 endpoint `/parent/.../summaries...` + helper test `failNextLearningSummary()` dan `seedApprovedSession(...)` (untuk skenario multi-subject >3 mapel). |
| `frontend/src/app/parent-summary.test.tsx` | **Baru** | 5 test UI end-to-end dengan Testing Library: generate bulanan + persistensi saat pindah halaman, generate per sesi di timeline, collapse/expand `> 3` mapel, state 0 sesi tanpa tombol generate, serta error inline + `Coba lagi` tanpa menyembunyikan catatan tutor. |

---

## 4. Ringkasan Alur Data End-to-End

1. Orang Tua membuka **Progress Anak** atau **Riwayat Pembelajaran** untuk periode `YYYY-MM`.
2. Frontend memanggil `GET /api/v1/parent/students/:student_id/summaries?period=YYYY-MM` (tidak memanggil AI service; hanya baca cache DB).
3. Jika ringkasan belum ada, tombol **Buat ringkasan bulanan** / **Ringkas sesi ini** muncul.
4. Saat diklik, frontend memanggil `POST .../summaries/monthly` atau `POST .../sessions/:session_id/summary` (timeout 35 detik).
5. Backend:
   - Memverifikasi role `parent`, relasi anak (`assertParentLinked`), CSRF, dan rate limit.
   - Mengambil sesi `approved`, menghitung SHA-256 `source_fingerprint`.
   - Jika cache segar cocok → langsung kembalikan `{ summary, cached: true }` tanpa memanggil FastAPI.
   - Jika belum ada / `is_stale` → kirim payload zero-PII ke `POST ${LEARNING_SUMMARY_SERVICE_URL}/v1/learning-summary/summarize`, validasi output dengan Zod, simpan via `ON CONFLICT DO UPDATE`, dan kembalikan `{ summary, cached: false }`.
6. Frontend memperbarui cache TanStack Query sehingga ringkasan langsung tampil dan tetap bertahan saat Orang Tua berpindah tab/halaman.

---

## 5. Langkah Selanjutnya (Saat Menyiapkan Service FastAPI)

1. Jalankan migration di database lokal/Neon (jika belum):
   ```powershell
   npm run db:migrate -w backend
   ```
2. Set variabel berikut di `backend/.env`:
   ```env
   LEARNING_SUMMARY_SERVICE_URL=http://localhost:8000
   LEARNING_SUMMARY_MODEL_NAME=
   LEARNING_SUMMARY_TIMEOUT_MS=30000
   ```
3. Implementasikan endpoint `POST /v1/learning-summary/summarize` di repo FastAPI (`AI-MODEL-MUMTAZ`) mengikuti kontrak Request & Response pada **Bagian 2** dokumen ini.
4. Uji end-to-end dari akun Orang Tua di dashboard untuk memastikan tombol **Buat ringkasan bulanan** dan **Ringkas sesi ini** menerima hasil Generative AI dan menyimpannya ke tabel `learning_summaries`.
