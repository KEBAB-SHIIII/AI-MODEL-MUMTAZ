"""
Tahap 5: Penyusunan Respons Akhir (`AnalyzeResponse`) dalam Bahasa Indonesia.

File ini mengubah angka-angka fitur dan keputusan `final_validity` menjadi:
1. `validity_reason`: Ringkasan alasan yang ramah dibaca Tutor & Admin di UI.
2. `findings`: Daftar temuan terstruktur yang dipetakan ke 4 `finding_type` PostgreSQL
   (`suspected_duplicate`, `duration_outlier`, `late_start`, `unusual_pattern`).
"""

from typing import Any, Optional

from .feature_extractor import hhmm_to_minutes, minutes_to_hhmm
from .schemas import (
    AnalyzeResponse,
    AnomalyConfig,
    FindingCandidate,
    FindingSeverity,
    FindingType,
    SessionSnapshot,
    SessionValidity,
)


def _clip(text: str, max_len: int = 600) -> str:
    """Memastikan teks tidak melebihi batas 600 karakter sesuai kontrak Zod Backend."""
    return text[:max_len]


def _format_range(session: SessionSnapshot) -> str:
    """Memformat rentang jam sesi menjadi teks mudah dibaca, misal 'pukul 08:15–09:45 WIB (90 menit)'."""
    if not session.start_time:
        return f"{session.duration_minutes} menit"
    start_m = hhmm_to_minutes(session.start_time)
    end_hhmm = minutes_to_hhmm(start_m + session.duration_minutes)
    return (
        f"pukul {session.start_time}–{end_hhmm} WIB ({session.duration_minutes} menit)"
    )


def _make_finding(
    target_id: str,
    finding_type: FindingType,
    severity: FindingSeverity,
    reason: str,
    evidence: str,
    related_session: Optional[SessionSnapshot] = None,
) -> FindingCandidate:
    """Helper untuk membuat objek FindingCandidate dengan panjang teks yang aman."""
    return FindingCandidate(
        lesson_session_id=target_id,
        related_lesson_session_id=related_session.id if related_session else None,
        is_anomaly=True,
        finding_type=finding_type,
        severity=severity,
        reason=_clip(reason),
        evidence_summary=_clip(evidence),
        suggested_action="review",
    )


def build_analyze_response(
    target: SessionSnapshot,
    config: AnomalyConfig,
    features: dict[str, float | int],
    helper_meta: dict[str, Any],
    final_validity: SessionValidity,
) -> AnalyzeResponse:
    """
    Menyusun payload respons HTTP 200 `{ validity, validity_reason, findings }`
    yang siap diterima dan disimpan oleh Backend Node.js.
    """
    findings: list[FindingCandidate] = []
    reasons_summary: list[str] = []

    # 1. Duplikat 100% Persis (REJECTED -> suspected_duplicate)
    if features["exact_dup_count"] >= 1:
        comp: Optional[SessionSnapshot] = helper_meta.get("exact_dup_session")
        reason = (
            f"Terdeteksi duplikat identik (100% sama) dengan sesi yang sudah di-submit sebelumnya "
            f"pada tanggal {target.lesson_date} ({_format_range(target)})."
        )
        evidence = (
            f"Tutor, murid, mata pelajaran ({int(features['subject_count'])} mapel), tanggal "
            f"{target.lesson_date}, jam mulai {target.start_time}, dan durasi {target.duration_minutes} menit "
            f"sama persis dengan sesi sebelumnya."
        )
        findings.append(
            _make_finding(
                target.id, "suspected_duplicate", "high", reason, evidence, comp
            )
        )
        reasons_summary.append(reason)

    # 2. Durasi Melebihi Batas Maksimal (> 180 menit -> duration_outlier)
    if features["duration_over_limit"] > 0:
        over = int(features["duration_over_limit"])
        reason = (
            f"Durasi sesi tercatat {target.duration_minutes} menit, melebihi batas maksimal "
            f"{config.durationOutlierMinutes} menit (+{over} menit)."
        )
        evidence = (
            f"Rentang les {_format_range(target)} melampaui ambang wajar "
            f"{config.durationOutlierMinutes} menit."
        )
        severity: FindingSeverity = (
            "medium" if target.duration_minutes >= 240 else "low"
        )
        findings.append(
            _make_finding(target.id, "duration_outlier", severity, reason, evidence)
        )
        reasons_summary.append(reason)

    # 3. Durasi Kurang dari Batas Minimal (< 30 menit -> duration_outlier)
    if features["duration_under_limit"] > 0:
        under = int(features["duration_under_limit"])
        reason = (
            f"Durasi sesi tercatat {target.duration_minutes} menit, kurang dari batas minimal "
            f"{config.durationMinMinutes} menit (-{under} menit)."
        )
        evidence = (
            f"Rentang les {_format_range(target)} di bawah durasi minimum "
            f"{config.durationMinMinutes} menit."
        )
        findings.append(
            _make_finding(target.id, "duration_outlier", "low", reason, evidence)
        )
        reasons_summary.append(reason)

    # 4. Jam Mulai Melewati Batas Malam (> 21:00 -> late_start)
    if features["start_over_limit"] > 0:
        reason = (
            f"Sesi dimulai pukul {target.start_time} WIB, melewati batas jam operasional malam "
            f"({config.lateStartAfter} WIB)."
        )
        evidence = f"Jam mulai tercatat {target.start_time} WIB (batas akhir {config.lateStartAfter} WIB)."
        findings.append(_make_finding(target.id, "late_start", "low", reason, evidence))
        reasons_summary.append(reason)

    # 5. Jam Mulai Lebih Awal dari Batas Pagi (< 07:00 -> late_start)
    if features["start_under_limit"] > 0:
        reason = (
            f"Sesi dimulai pukul {target.start_time} WIB, lebih awal dari batas jam operasional pagi "
            f"({config.earlyStartBefore} WIB)."
        )
        evidence = f"Jam mulai tercatat {target.start_time} WIB (batas awal {config.earlyStartBefore} WIB)."
        findings.append(_make_finding(target.id, "late_start", "low", reason, evidence))
        reasons_summary.append(reason)

    # 6. Duplikat Samar Beda Jam Mulai (fuzzy_dup_count >= 1 -> suspected_duplicate)
    if features["fuzzy_dup_count"] >= 1:
        comp = helper_meta.get("fuzzy_dup_session")
        comp_time = _format_range(comp) if comp else "jam berbeda"
        reason = (
            f"Terdeteksi sesi serupa (tutor, murid, mata pelajaran, tanggal, dan durasi sama) "
            f"pada tanggal {target.lesson_date} namun dengan jam mulai berbeda ({comp_time})."
        )
        evidence = f"Sesi ini tercatat {_format_range(target)}, sedangkan sesi sebelumnya tercatat {comp_time}."
        findings.append(
            _make_finding(
                target.id, "suspected_duplicate", "medium", reason, evidence, comp
            )
        )
        reasons_summary.append(reason)

    # 7. Jadwal Tutor Bentrok dengan Murid Lain (-> unusual_pattern)
    if features["tutor_overlap_diff_student_count"] >= 1:
        comp = helper_meta.get("tutor_overlap_session")
        comp_time = _format_range(comp) if comp else "jam yang beririsan"
        reason = (
            f"Jadwal mengajar tutor bentrok (irisan waktu) dengan sesi murid lain pada tanggal "
            f"{target.lesson_date} ({comp_time})."
        )
        evidence = f"Tutor tercatat mengajar pada {_format_range(target)} yang beririsan dengan sesi lain pada {comp_time}."
        findings.append(
            _make_finding(
                target.id, "unusual_pattern", "medium", reason, evidence, comp
            )
        )
        reasons_summary.append(reason)

    # 8. Jadwal Murid Bentrok dengan Tutor Lain (-> unusual_pattern)
    if features["student_overlap_diff_tutor_count"] >= 1:
        comp = helper_meta.get("student_overlap_session")
        comp_time = _format_range(comp) if comp else "jam yang beririsan"
        reason = (
            f"Jadwal belajar murid bentrok (irisan waktu) dengan sesi bersama tutor lain pada tanggal "
            f"{target.lesson_date} ({comp_time})."
        )
        evidence = f"Murid tercatat mengikuti sesi {_format_range(target)} yang beririsan dengan sesi tutor lain ({comp_time})."
        findings.append(
            _make_finding(
                target.id, "unusual_pattern", "medium", reason, evidence, comp
            )
        )
        reasons_summary.append(reason)

    # 9. Jadwal Tutor & Murid Sama Bentrok Sendiri (-> unusual_pattern)
    if features["self_overlap_count"] >= 1:
        comp = helper_meta.get("self_overlap_session")
        comp_time = _format_range(comp) if comp else "jam yang beririsan"
        reason = (
            f"Jadwal sesi ini beririsan waktu dengan sesi lain untuk tutor dan murid yang sama "
            f"pada tanggal {target.lesson_date} ({comp_time})."
        )
        evidence = f"Rentang waktu {_format_range(target)} bertumpukan dengan sesi sebelumnya ({comp_time})."
        findings.append(
            _make_finding(
                target.id, "unusual_pattern", "medium", reason, evidence, comp
            )
        )
        reasons_summary.append(reason)

    # Susun kalimat ringkasan `validity_reason` sesuai status akhir
    if final_validity == "valid":
        validity_reason = "Tidak ditemukan anomali pada sesi ini; durasi, jam mulai, dan jadwal sesuai aturan."
        findings = []
    elif final_validity == "rejected":
        validity_reason = _clip(" ".join(reasons_summary))
    else:
        if reasons_summary:
            validity_reason = _clip(
                "Perlu konfirmasi/revisi: " + " ".join(reasons_summary)
            )
        else:
            validity_reason = "Pola sesi memerlukan peninjauan ulang oleh Admin atau konfirmasi dari Tutor."

    return AnalyzeResponse(
        validity=final_validity,
        validity_reason=validity_reason,
        findings=findings,
    )
