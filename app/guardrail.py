"""
Tahap 4: Guardrail Deterministik (Pengaman Batas Aturan Bisnis).

Mengapa file ini dibutuhkan padahal sudah ada model ML (`anomaly_model.pkl`)?
1. Menutup celah perbatasan (Boundary Discretization Gap): Pada data latih LightGBM,
   tidak ada sampel durasi 181 atau 182 menit sehingga pohon keputusan membelah di ~181.5 menit.
   Guardrail menjamin durasi 181 menit (+1 di atas batas) pasti terdeteksi `needs_revision`.
2. Mendukung perubahan `.env` Backend secara dinamis: Jika Admin mengubah ambang batas di
   `backend/.env` (misal batas maksimal diubah ke 150 menit), Guardrail langsung mengikuti
   `duration_over_limit > 0` tanpa perlu melatih ulang model `.pkl`.
3. Mencegah false positive di garis batas valid (misal tepat 30 menit, 180 menit, 07:00, 21:00).
"""

from .schemas import SessionValidity


def apply_business_guardrail(
    raw_model_prediction: str,
    features: dict[str, float | int],
) -> SessionValidity:
    """
    Memvalidasi prediksi mentah model ML terhadap 9 kondisi aturan bisnis secara eksak.
    Urutan prioritas mutlak: rejected > needs_revision > valid.
    """
    # Pintu 1 (Prioritas Tertinggi): Duplikat 100% persis wajib REJECTED
    if features["exact_dup_count"] >= 1:
        return "rejected"

    # Pintu 2 (8 Kondisi Wajib Revisi):
    # - 4 kondisi pelanggaran batas angka (durasi / jam mulai)
    # - 1 kondisi duplikat samar (beda jam mulai)
    # - 3 kondisi jadwal bentrok (tutor, murid, atau tutor+murid sendiri)
    if (
        features["duration_over_limit"] > 0
        or features["duration_under_limit"] > 0
        or features["start_over_limit"] > 0
        or features["start_under_limit"] > 0
        or features["fuzzy_dup_count"] >= 1
        or features["tutor_overlap_diff_student_count"] >= 1
        or features["student_overlap_diff_tutor_count"] >= 1
        or features["self_overlap_count"] >= 1
    ):
        return "needs_revision"

    # Pintu 3: Jika seluruh kondisi di atas bersih (= 0), pastikan status akhir adalah valid
    # sehingga sesi tepat di garis batas (30 mnt, 180 mnt, 07:00, 21:00) tetap aman.
    if raw_model_prediction in ("valid", "needs_revision", "rejected"):
        return "valid"

    return "valid"
