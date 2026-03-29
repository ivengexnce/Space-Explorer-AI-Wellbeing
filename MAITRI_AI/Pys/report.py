"""
report.py — MAITRI AI Session Report Generator v3
Saves to: reports/report_YYYYMMDD_HHMMSS_<sid8>.json  (machine-readable, for frontend)
          reports/report_YYYYMMDD_HHMMSS_<sid8>.txt   (human-readable)
          reports/report_YYYYMMDD_HHMMSS_<sid8>.csv   (raw frame log for spreadsheet)

JSON schema is consumed by the /session/<id>/report-full endpoint
and rendered as a rich visual report in the MAITRI frontend.
"""
import datetime
import json
import logging
import csv
from collections import Counter
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

REPORT_DIR = Path("reports")

# Emotion → wellbeing weight (-1.0 … +1.0)
_WEIGHTS = {
    "happy":    1.0,
    "neutral":  0.4,
    "surprise": 0.5,
    "disgust": -0.5,
    "fear":    -0.7,
    "sad":     -0.8,
    "angry":   -0.9,
}

_EMOTION_COLORS = {
    "happy":    "#00ff87",
    "neutral":  "#00e5ff",
    "surprise": "#ffc107",
    "disgust":  "#ff8c42",
    "fear":     "#c084fc",
    "sad":      "#5b8dd9",
    "angry":    "#ff3355",
}

_MENTAL_LABELS = {
    "happy":    "Flourishing & Joyful",
    "neutral":  "Calm & Balanced",
    "surprise": "Alert & Stimulated",
    "disgust":  "Discomfort — Needs Reset",
    "fear":     "Anxious — Needs Safety",
    "sad":      "Needs Gentle Support",
    "angry":    "High Tension — Needs Calm",
}

_WELLBEING_GRADE = [
    (90, "Excellent",  "💚"),
    (75, "Good",       "💙"),
    (60, "Moderate",   "💛"),
    (45, "Low",        "🧡"),
    (0,  "Needs Care", "❤️"),
]


def _wellbeing_score(log: list) -> float:
    """0–100 score from emotion-weighted log."""
    if not log:
        return 50.0
    raw    = sum(_WEIGHTS.get(e.lower(), 0.0) for e in log) / len(log)
    normed = (raw + 1.0) / 2.0          # → 0.0 – 1.0
    return round(normed * 100, 1)


def _grade(score: float) -> tuple[str, str]:
    for threshold, label, icon in _WELLBEING_GRADE:
        if score >= threshold:
            return label, icon
    return "Needs Care", "❤️"


def _streaks(log: list) -> dict:
    """Find longest positive and negative streaks."""
    positive = {"happy", "neutral", "surprise"}
    best_pos = best_neg = cur_pos = cur_neg = 0
    for e in log:
        if e.lower() in positive:
            cur_pos += 1
            cur_neg  = 0
        else:
            cur_neg += 1
            cur_pos  = 0
        best_pos = max(best_pos, cur_pos)
        best_neg = max(best_neg, cur_neg)
    return {"longest_positive_streak": best_pos, "longest_negative_streak": best_neg}


def _mood_transitions(log: list) -> list[dict]:
    """Return list of mood change events {from, to, at_frame}."""
    transitions = []
    for i in range(1, len(log)):
        if log[i] != log[i - 1]:
            transitions.append({"from": log[i - 1], "to": log[i], "at_frame": i + 1})
    return transitions


def _segment_analysis(log: list, segments: int = 4) -> list[dict]:
    """Split session into N segments and return dominant emotion per segment."""
    if not log:
        return []
    seg_size = max(1, len(log) // segments)
    result   = []
    for i in range(segments):
        chunk = log[i * seg_size: (i + 1) * seg_size]
        if not chunk:
            continue
        c = Counter(chunk)
        dominant = c.most_common(1)[0][0]
        score    = _wellbeing_score(chunk)
        result.append({
            "segment":    i + 1,
            "label":      f"Phase {i+1}",
            "frames":     len(chunk),
            "dominant":   dominant,
            "score":      score,
            "color":      _EMOTION_COLORS.get(dominant, "#4a7a90"),
            "distribution": {k: round(v / len(chunk) * 100, 1) for k, v in c.most_common()},
        })
    return result


def build_report_data(
    log: list,
    session_id: str = "",
    conversation: list = None,
    alerts: list = None,
    session_meta: dict = None,
) -> dict:
    """
    Build the complete rich report dict.
    Called by both save_log() and the /report-full Flask endpoint.
    """
    ts = datetime.datetime.now()
    c  = Counter(log)

    dominant     = c.most_common(1)[0][0] if log else "neutral"
    score        = _wellbeing_score(log)
    grade, icon  = _grade(score)
    streaks      = _streaks(log)
    transitions  = _mood_transitions(log)
    segments     = _segment_analysis(log)

    # Per-emotion stats
    emotion_stats = []
    for emo, count in c.most_common():
        pct = round(count / max(len(log), 1) * 100, 1)
        emotion_stats.append({
            "emotion":    emo,
            "count":      count,
            "percent":    pct,
            "color":      _EMOTION_COLORS.get(emo, "#4a7a90"),
            "label":      _MENTAL_LABELS.get(emo, ""),
            "weight":     _WEIGHTS.get(emo, 0.0),
        })

    # Frame-by-frame for sparkline (downsample to max 500 points)
    full_log     = log
    sample_rate  = max(1, len(log) // 500)
    sampled_log  = [log[i] for i in range(0, len(log), sample_rate)]
    emotion_order = ["angry", "sad", "fear", "disgust", "surprise", "neutral", "happy"]
    sampled_y    = [emotion_order.index(e) if e in emotion_order else 3 for e in sampled_log]

    # Positive / negative / neutral frame counts
    pos_count     = sum(1 for e in log if e.lower() in {"happy", "surprise"})
    neg_count     = sum(1 for e in log if e.lower() in {"sad", "angry", "fear", "disgust"})
    neu_count     = sum(1 for e in log if e.lower() == "neutral")

    # Conversation summary
    conv_turns    = len(conversation or [])
    user_msgs     = [t for t in (conversation or []) if t.get("role") == "user"]
    maitri_msgs   = [t for t in (conversation or []) if t.get("role") == "maitri"]

    return {
        # ── Meta ───────────────────────────────────────────────────────────
        "generated_at":    ts.isoformat(),
        "session_id":      session_id,
        "report_version":  "3.0",

        # ── Core summary ───────────────────────────────────────────────────
        "total_frames":         len(log),
        "dominant_emotion":     dominant,
        "dominant_color":       _EMOTION_COLORS.get(dominant, "#00e5ff"),
        "dominant_label":       _MENTAL_LABELS.get(dominant, ""),
        "wellbeing_score":      score,
        "wellbeing_grade":      grade,
        "wellbeing_icon":       icon,

        # ── Frame counts ───────────────────────────────────────────────────
        "positive_frames":  pos_count,
        "negative_frames":  neg_count,
        "neutral_frames":   neu_count,
        "mood_changes":     len(transitions),

        # ── Detailed emotion breakdown ─────────────────────────────────────
        "emotion_stats":   emotion_stats,
        "emotion_colors":  _EMOTION_COLORS,

        # ── Trends & patterns ──────────────────────────────────────────────
        "streaks":         streaks,
        "transitions":     transitions[:50],   # cap at 50 for payload size
        "segments":        segments,

        # ── Timeline (sampled) ─────────────────────────────────────────────
        "timeline_labels": list(range(1, len(sampled_log) + 1)),
        "timeline_values": sampled_y,
        "timeline_emotions": sampled_log,
        "emotion_order":   emotion_order,

        # ── Distribution (pie) ─────────────────────────────────────────────
        "pie_labels":      [s["emotion"] for s in emotion_stats],
        "pie_values":      [s["count"]   for s in emotion_stats],
        "pie_colors":      [s["color"]   for s in emotion_stats],

        # ── Conversation ───────────────────────────────────────────────────
        "conversation_turns":  conv_turns,
        "user_messages":       len(user_msgs),
        "maitri_messages":     len(maitri_msgs),
        "conversation_sample": (conversation or [])[-20:],  # last 20 turns

        # ── Alerts ─────────────────────────────────────────────────────────
        "alerts":          alerts or [],
        "alert_count":     len(alerts or []),

        # ── Session meta ───────────────────────────────────────────────────
        "session_meta":    session_meta or {},

        # ── Full log (for CSV) ─────────────────────────────────────────────
        "_full_log":       full_log,
    }


def save_log(
    log:          list,
    session_id:   str  = "",
    conversation: list = None,
    alerts:       list = None,
    session_meta: dict = None,
) -> dict:
    """
    Save session report to reports/ folder (JSON + TXT + CSV).
    Returns the report data dict (same shape as build_report_data).
    """
    REPORT_DIR.mkdir(exist_ok=True)

    ts      = datetime.datetime.now()
    ts_str  = ts.strftime("%Y%m%d_%H%M%S")
    sfx     = f"_{session_id[:8]}" if session_id else ""
    base    = f"report_{ts_str}{sfx}"

    json_path = REPORT_DIR / f"{base}.json"
    txt_path  = REPORT_DIR / f"{base}.txt"
    csv_path  = REPORT_DIR / f"{base}.csv"

    data = build_report_data(log, session_id, conversation, alerts, session_meta)

    # ── JSON ──────────────────────────────────────────────────────────────
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # ── TXT ───────────────────────────────────────────────────────────────
    sep = "=" * 56
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"{sep}\n  MAITRI AI — SESSION WELLBEING REPORT v3\n{sep}\n")
        f.write(f"Generated    : {ts.isoformat()}\n")
        f.write(f"Session ID   : {session_id or 'N/A'}\n")
        f.write(f"Total Frames : {len(log)}\n")
        f.write(f"Wellbeing    : {data['wellbeing_score']}/100  [{data['wellbeing_grade']}] {data['wellbeing_icon']}\n")
        f.write(f"Dominant Emo : {data['dominant_emotion'].title()}\n")
        f.write(f"Mood Changes : {data['mood_changes']}\n")
        f.write(f"Conversation : {data['conversation_turns']} turns\n")
        f.write(f"Alerts       : {data['alert_count']}\n")
        f.write(f"\n{'─'*56}\nEmotion Distribution:\n")
        for s in data["emotion_stats"]:
            bar = "█" * int(s["percent"] / 4)
            f.write(f"  {s['emotion']:<12} {s['count']:>4}x  {s['percent']:5.1f}%  {bar}\n")
        f.write(f"\n{'─'*56}\nSession Phases:\n")
        for seg in data["segments"]:
            f.write(f"  Phase {seg['segment']} ({seg['frames']} frames): "
                    f"{seg['dominant'].title()} — score {seg['score']}/100\n")
        f.write(f"\n{'─'*56}\nStreaks:\n")
        f.write(f"  Longest positive streak : {data['streaks']['longest_positive_streak']} frames\n")
        f.write(f"  Longest negative streak : {data['streaks']['longest_negative_streak']} frames\n")
        f.write(f"\n{'─'*56}\nFull Frame Log:\n")
        for i, e in enumerate(log):
            f.write(f"  [{i+1:05d}] {e}\n")

    # ── CSV ───────────────────────────────────────────────────────────────
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["frame_index", "emotion", "wellbeing_weight"])
        for i, e in enumerate(log):
            writer.writerow([i + 1, e, _WEIGHTS.get(e.lower(), 0.0)])

    data["_saved_paths"] = {
        "json": str(json_path),
        "txt":  str(txt_path),
        "csv":  str(csv_path),
    }

    logger.info("Report saved: %s (score=%.1f, grade=%s)",
                json_path, data["wellbeing_score"], data["wellbeing_grade"])
    print(f"✅ Report saved:\n  JSON: {json_path}\n  TXT : {txt_path}\n  CSV : {csv_path}")
    return data
