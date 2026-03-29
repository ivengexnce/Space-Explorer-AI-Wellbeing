"""
alert_system.py — MAITRI AI Alert Engine v2
UPGRADES:
  - Returns structured dict {severity, code, message, speak} instead of bare string
  - speak field is TTS-friendly (no ALL-CAPS, no jargon) — spoken aloud by Maitri
  - 4 severity tiers: INFO / CAUTION / WARNING / CRITICAL
  - Detects rapid mood oscillation and positive streaks
  - alert_speak() helper extracts TTS text
"""
from collections import Counter
import logging

logger = logging.getLogger(__name__)

_SEVERITY_RANK = {"CRITICAL": 4, "WARNING": 3, "CAUTION": 2, "INFO": 1}


def _alert(severity: str, code: str, message: str, speak: str) -> dict:
    return {"severity": severity, "code": code, "message": message, "speak": speak}


def check_alert(log: list) -> dict | None:
    """
    Analyse the recent emotion window.
    Returns highest-priority alert as a dict, or None.
    """
    if len(log) < 5:
        return None

    c  = Counter(log)
    n  = len(log)
    candidates = []

    # ── CRITICAL ──────────────────────────────────────────────────────────────
    if c["sad"] >= 4:
        candidates.append(_alert(
            "CRITICAL", "STRESS_OVERLOAD",
            "Stress overload detected",
            "I notice you've been feeling really sad for a while, sweetheart. I'm right here — let's breathe together slowly."
        ))
    if c["angry"] >= 4:
        candidates.append(_alert(
            "CRITICAL", "AGGRESSION_SPIKE",
            "Aggression spike detected",
            "I can sense so much tension in you right now. Let's slow everything down — take one deep breath with me."
        ))

    # ── WARNING ───────────────────────────────────────────────────────────────
    negative_total = c["sad"] + c["angry"] + c["fear"] + c["disgust"]
    if negative_total >= 6:
        candidates.append(_alert(
            "WARNING", "SUSTAINED_NEGATIVE",
            "Sustained negative emotional pattern",
            "You've been carrying a heavy feeling for a while now, my dear. I'm right here with you — you are not alone."
        ))
    if n >= 5 and len(set(log[-5:])) >= 4:
        candidates.append(_alert(
            "WARNING", "MOOD_OSCILLATION",
            "Rapid mood fluctuation detected",
            "Your mood seems to be shifting quite quickly. Let's pause together and take one gentle breath."
        ))

    # ── CAUTION ───────────────────────────────────────────────────────────────
    if c["fear"] >= 3:
        candidates.append(_alert(
            "CAUTION", "ANXIETY_RISING",
            "Anxiety level rising",
            "I can see some anxiety building, and I want you to know you are completely safe. I'm right here."
        ))
    if c["disgust"] >= 3:
        candidates.append(_alert(
            "CAUTION", "NEGATIVE_STATE",
            "Persistent negative state",
            "Something seems to be bothering you. Even a small change of scenery can help so much."
        ))

    # ── INFO ──────────────────────────────────────────────────────────────────
    if n >= 20 and c["happy"] == 0 and c["neutral"] <= 2:
        candidates.append(_alert(
            "INFO", "LOW_POSITIVE_SESSION",
            "Extended low-positive session",
            "You've been going for a while without much joy. How are you really doing? I'm here to listen."
        ))
    if n >= 8 and c["happy"] >= 6:
        candidates.append(_alert(
            "INFO", "POSITIVE_STREAK",
            "Sustained positive mood",
            "You've been smiling so beautifully! I love seeing you this happy — keep shining!"
        ))

    if not candidates:
        return None

    return max(candidates, key=lambda a: _SEVERITY_RANK.get(a["severity"], 0))


def alert_message(alert: dict | None) -> str | None:
    return alert["message"] if alert else None


def alert_speak(alert: dict | None) -> str | None:
    return alert["speak"] if alert else None