"""
Tahap 2: Transformasi Data Mentah (JSON) Menjadi 19 Fitur Angka (`FEATURE_NAMES`).

File ini bertugas sebagai "penerjemah" dari JSON (`target`, `comparisons`, `config`)
menjadi 19 angka yang siap dibaca oleh model LightGBM (`anomaly_model.pkl`).

PENTING UNTUK MAINTENANCE:
- Urutan `FEATURE_NAMES` dan rumus setiap fitur di bawah ini WAJIB 100% identik dengan
  `dataset/feature_extraction.ipynb` & `artifacts/feature_metadata.json` yang dipakai saat
  pelatihan model di Google Colab.
- Selain 19 fitur angka, fungsi `extract_features_and_meta()` juga mengembalikan `helper_meta`
  berisi referensi objek sesi pembanding yang memicu duplikat/bentrok untuk kebutuhan Tahap 5.
"""

from typing import Any, Optional

from .schemas import AnomalyConfig, SessionSnapshot

# Urutan baku 19 fitur (#1 sampai #19) sesuai feature_metadata.json
FEATURE_NAMES: list[str] = [
    "duration_minutes",  # 1.  Durasi sesi target (menit)
    "duration_over_limit",  # 2.  Selisih durasi di atas batas maksimal (> 0 = melanggar)
    "start_minute",  # 3.  Jam mulai target dalam menit sejak 00:00
    "start_over_limit",  # 4.  Selisih jam mulai di atas batas malam (> 0 = melanggar)
    "subject_count",  # 5.  Jumlah mata pelajaran pada sesi target (1-5)
    "comparisons_count",  # 6.  Total sesi pembanding yang diterima (+-30 hari)
    "exact_dup_count",  # 7.  Jumlah duplikat 100% persis (6 atribut sama)
    "same_tutor_student_date_count",  # 8.  Jumlah sesi tutor+murid sama di tanggal yang sama
    "same_student_date_diff_tutor_count",  # 9.  Jumlah sesi murid sama, mapel beririsan, tutor beda di tgl sama
    "time_overlap_count",  # 10. Total sesi yang jam mengajarnya beririsan waktu
    "tutor_sessions_30d",  # 11. Total sesi tutor ini dalam 30 hari terakhir
    "student_sessions_30d",  # 12. Total sesi murid ini dalam 30 hari terakhir
    "duration_diff_from_tutor_mean_30d",  # 13. Selisih durasi target dgn rata-rata durasi tutor 30h
    "duration_under_limit",  # 14. Selisih durasi di bawah batas minimal (> 0 = melanggar)
    "start_under_limit",  # 15. Selisih jam mulai di bawah batas pagi (> 0 = melanggar)
    "fuzzy_dup_count",  # 16. Jumlah duplikat samar (5 atribut sama, beda jam mulai)
    "tutor_overlap_diff_student_count",  # 17. Jumlah jadwal bentrok tutor dgn murid berbeda
    "student_overlap_diff_tutor_count",  # 18. Jumlah jadwal bentrok murid dgn tutor berbeda
    "self_overlap_count",  # 19. Jumlah jadwal bentrok tutor+murid yang sama
]


def hhmm_to_minutes(hhmm: Optional[str], default: int = 960) -> int:
    """
    Mengubah string jam 'HH:MM' (atau 'HH:MM:SS') menjadi total menit sejak pukul 00:00.
    Contoh: '07:00' -> 420, '21:00' -> 1260. Jika None/kosong, default ke 16:00 (960).
    """
    if not hhmm or ":" not in hhmm:
        return default
    parts = hhmm.strip().split(":")
    return int(parts[0]) * 60 + int(parts[1])


def minutes_to_hhmm(total_minutes: int) -> str:
    """
    Mengubah total menit sejak 00:00 kembali ke format string 'HH:MM' untuk teks laporan.
    Contoh: 495 -> '08:15'.
    """
    hours = (total_minutes // 60) % 24
    minutes = total_minutes % 60
    return f"{hours:02d}:{minutes:02d}"


def is_time_overlapping(start_a: int, dur_a: int, start_b: int, dur_b: int) -> bool:
    """
    Mengecek apakah dua rentang waktu [start, start + duration) saling beririsan.
    Catatan: Sesi yang langsung menyambung persis (misal 08:00-09:00 dan 09:00-10:00)
    TIDAK dianggap bentrok karena memakai perbandingan `<` (bukan `<=`).
    """
    end_a = start_a + dur_a
    end_b = start_b + dur_b
    return start_a < end_b and start_b < end_a


def extract_features_and_meta(
    target: SessionSnapshot,
    comparisons: list[SessionSnapshot],
    config: AnomalyConfig,
) -> tuple[dict[str, float | int], dict[str, Any]]:
    """
    Menghitung ke-19 fitur numerik dan metadata sesi pembanding pemicu anomali.

    Returns:
        features: Dictionary {nama_fitur: nilai_angka} untuk input model ML & Guardrail.
        helper_meta: Dictionary berisi sesi pembanding pertama yang memicu masing-masing
                     jenis duplikat/bentrok agar Tahap 5 bisa mengisi `related_lesson_session_id`.
    """
    dur = int(target.duration_minutes)
    start_min = hhmm_to_minutes(target.start_time, default=960)
    target_subjects = sorted(target.subject_ids)
    target_subject_set = set(target_subjects)

    late_limit_min = hhmm_to_minutes(
        config.lateStartAfter, default=1260
    )  # Default 21:00 (1260)
    early_limit_min = hhmm_to_minutes(
        config.earlyStartBefore, default=420
    )  # Default 07:00 (420)

    # --------------------------------------------------------------------------
    # A. Hitung Fitur Tunggal (Target vs Config)
    # Kaidah tanda: <= 0 berarti AMAN (di dalam batas), > 0 berarti MELANGGAR batas.
    # --------------------------------------------------------------------------
    duration_over_limit = dur - int(config.durationOutlierMinutes)
    duration_under_limit = int(config.durationMinMinutes) - dur
    start_over_limit = start_min - late_limit_min
    start_under_limit = early_limit_min - start_min
    subject_count = len(target_subjects)
    comparisons_count = len(comparisons)

    # --------------------------------------------------------------------------
    # B. Inisialisasi Counter Fitur Perbandingan & Riwayat 30 Hari
    # --------------------------------------------------------------------------
    exact_dup_count = 0
    fuzzy_dup_count = 0
    same_tutor_student_date_count = 0
    same_student_date_diff_tutor_count = 0
    time_overlap_count = 0
    tutor_overlap_diff_student_count = 0
    student_overlap_diff_tutor_count = 0
    self_overlap_count = 0

    tutor_sessions_30d = 0
    student_sessions_30d = 0
    tutor_durations_30d: list[int] = []

    # Menyimpan sesi pembanding pertama yang memicu tiap aturan untuk bukti (findings)
    exact_dup_session: Optional[SessionSnapshot] = None
    fuzzy_dup_session: Optional[SessionSnapshot] = None
    tutor_overlap_session: Optional[SessionSnapshot] = None
    student_overlap_session: Optional[SessionSnapshot] = None
    self_overlap_session: Optional[SessionSnapshot] = None

    # --------------------------------------------------------------------------
    # C. Iterasi Seluruh Sesi Pembanding (+-30 hari yang di-submit lebih awal)
    # --------------------------------------------------------------------------
    for comp in comparisons:
        if comp.id == target.id:
            continue

        comp_dur = int(comp.duration_minutes)
        comp_start = hhmm_to_minutes(comp.start_time, default=960)
        comp_subjects = sorted(comp.subject_ids)
        subj_intersect = len(set(comp_subjects) & target_subject_set) > 0

        same_tutor = comp.tutor_id == target.tutor_id
        same_student = comp.student_id == target.student_id
        same_date = comp.lesson_date == target.lesson_date
        same_subj = comp_subjects == target_subjects
        same_dur = comp_dur == dur
        same_start = (
            target.start_time is not None
            and comp.start_time is not None
            and comp_start == start_min
        )

        # Fitur 11 & persiapan Fitur 13: Statistik riwayat tutor 30 hari
        if same_tutor:
            tutor_sessions_30d += 1
            tutor_durations_30d.append(comp_dur)

        # Fitur 12: Statistik riwayat murid 30 hari
        if same_student:
            student_sessions_30d += 1

        # Pengecekan duplikat & bentrok jadwal hanya berlaku pada tanggal les yang sama
        if not same_date:
            continue

        # Fitur 8: Tutor, murid, dan tanggal les sama
        if same_tutor and same_student:
            same_tutor_student_date_count += 1

        # Fitur 9: Murid dan tanggal sama, mata pelajaran beririsan, tetapi tutor berbeda
        if same_student and (not same_tutor) and subj_intersect:
            same_student_date_diff_tutor_count += 1

        # Fitur 7: Duplikat 100% Persis (6 atribut identik -> berujung REJECTED)
        is_exact_dup = (
            same_tutor
            and same_student
            and same_subj
            and same_date
            and same_dur
            and same_start
        )
        if is_exact_dup:
            exact_dup_count += 1
            if exact_dup_session is None:
                exact_dup_session = comp

        # Fitur 16: Duplikat Samar (5 atribut sama, namun jam mulai berbeda -> NEEDS_REVISION)
        if (
            same_tutor
            and same_student
            and same_subj
            and same_date
            and same_dur
            and not same_start
        ):
            fuzzy_dup_count += 1
            if fuzzy_dup_session is None:
                fuzzy_dup_session = comp

        # Pengecekan Bentrok / Irisan Waktu (Overlap) jika kedua sesi punya jam mulai
        if target.start_time is not None and comp.start_time is not None:
            if is_time_overlapping(start_min, dur, comp_start, comp_dur):
                if same_tutor or same_student:
                    # Fitur 10: Total jadwal bertabrakan (termasuk exact duplicate, persis notebook)
                    time_overlap_count += 1

                # Fitur 17: Tutor sama mengajar 2 murid berbeda di jam yang beririsan
                if same_tutor and not same_student:
                    tutor_overlap_diff_student_count += 1
                    if tutor_overlap_session is None:
                        tutor_overlap_session = comp

                # Fitur 18: Murid sama diajar 2 tutor berbeda di jam yang beririsan
                elif same_student and not same_tutor:
                    student_overlap_diff_tutor_count += 1
                    if student_overlap_session is None:
                        student_overlap_session = comp

                # Fitur 19: Tutor & murid sama di jam yang beririsan (tetapi bukan duplikat persis)
                elif same_tutor and same_student and not is_exact_dup:
                    self_overlap_count += 1
                    if self_overlap_session is None:
                        self_overlap_session = comp

    # Fitur 13: Selisih durasi sesi target terhadap rata-rata durasi tutor 30 hari terakhir
    if tutor_durations_30d:
        tutor_mean_30d = sum(tutor_durations_30d) / len(tutor_durations_30d)
        duration_diff_from_tutor_mean_30d = round(dur - tutor_mean_30d, 4)
    else:
        duration_diff_from_tutor_mean_30d = 0.0

    features: dict[str, float | int] = {
        "duration_minutes": dur,
        "duration_over_limit": duration_over_limit,
        "start_minute": start_min,
        "start_over_limit": start_over_limit,
        "subject_count": subject_count,
        "comparisons_count": comparisons_count,
        "exact_dup_count": exact_dup_count,
        "same_tutor_student_date_count": same_tutor_student_date_count,
        "same_student_date_diff_tutor_count": same_student_date_diff_tutor_count,
        "time_overlap_count": time_overlap_count,
        "tutor_sessions_30d": tutor_sessions_30d,
        "student_sessions_30d": student_sessions_30d,
        "duration_diff_from_tutor_mean_30d": duration_diff_from_tutor_mean_30d,
        "duration_under_limit": duration_under_limit,
        "start_under_limit": start_under_limit,
        "fuzzy_dup_count": fuzzy_dup_count,
        "tutor_overlap_diff_student_count": tutor_overlap_diff_student_count,
        "student_overlap_diff_tutor_count": student_overlap_diff_tutor_count,
        "self_overlap_count": self_overlap_count,
    }

    helper_meta: dict[str, Any] = {
        "target_end_hhmm": minutes_to_hhmm(start_min + dur),
        "exact_dup_session": exact_dup_session,
        "fuzzy_dup_session": fuzzy_dup_session,
        "tutor_overlap_session": tutor_overlap_session,
        "student_overlap_session": student_overlap_session,
        "self_overlap_session": self_overlap_session,
    }

    return features, helper_meta
