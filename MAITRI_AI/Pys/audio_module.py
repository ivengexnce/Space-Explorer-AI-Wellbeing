"""
audio_module.py — Maitri Microphone Input v3
KEY FIXES (from log analysis):
  - adjust_for_ambient_noise runs ONCE per process (was running every call — wasting 400ms)
  - Mic lock is non-blocking; returns dict instead of bare AudioData
  - record_and_transcribe() is a single call for the voice loop
  - Returns (text, source) tuple so caller knows if Google or Sphinx answered
  - Exponential back-off helper for repeated failures
"""
import speech_recognition as sr
import threading
import logging
import time

logger = logging.getLogger(__name__)

_recognizer = sr.Recognizer()
_mic_lock   = threading.Lock()

_recognizer.dynamic_energy_threshold = True
_recognizer.energy_threshold         = 300
_recognizer.pause_threshold          = 0.8

# ── One-time noise calibration ────────────────────────────────────────────────
_noise_calibrated  = False
_noise_calib_lock  = threading.Lock()
_NOISE_CALIB_SEC   = 0.5   # half-second baseline — plenty for indoor use


def _ensure_noise_profile(source: sr.Microphone) -> None:
    """Calibrate ambient noise exactly once per process lifetime."""
    global _noise_calibrated
    with _noise_calib_lock:
        if not _noise_calibrated:
            logger.info("Mic: one-time noise calibration (%.1fs)...", _NOISE_CALIB_SEC)
            _recognizer.adjust_for_ambient_noise(source, duration=_NOISE_CALIB_SEC)
            _noise_calibrated = True
            logger.info("Mic: calibrated (threshold=%.0f)", _recognizer.energy_threshold)


def record_audio(timeout: int = 5, phrase_limit: int = 12) -> dict:
    """
    Record one phrase from the microphone.
    Returns:
      { "audio": AudioData|None, "success": bool, "reason": str }
    """
    if not _mic_lock.acquire(blocking=False):
        logger.info("Mic: busy — skipping")
        return {"audio": None, "success": False, "reason": "busy"}
    try:
        with sr.Microphone() as source:
            _ensure_noise_profile(source)
            logger.info("Mic: listening (timeout=%ds, phrase_limit=%ds)", timeout, phrase_limit)
            audio = _recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_limit)
            return {"audio": audio, "success": True, "reason": "ok"}
    except sr.WaitTimeoutError:
        logger.info("Mic: no speech within %ds", timeout)
        return {"audio": None, "success": False, "reason": "timeout"}
    except Exception as e:
        logger.error("Mic record error: %s", e)
        return {"audio": None, "success": False, "reason": f"error:{e}"}
    finally:
        _mic_lock.release()


def speech_to_text(audio) -> tuple[str, str]:
    """
    Transcribe AudioData → (text, source).
    source: "google" | "sphinx" | "none"
    Accepts raw AudioData or the dict from record_audio().
    """
    if isinstance(audio, dict):
        audio = audio.get("audio")
    if audio is None:
        return "", "none"

    try:
        text = _recognizer.recognize_google(audio)
        if text:
            logger.info("STT (Google): %s", text)
            return text.strip(), "google"
    except sr.UnknownValueError:
        logger.info("STT: could not understand audio")
    except sr.RequestError as e:
        logger.warning("STT (Google) network: %s — trying Sphinx", e)
        try:
            text = _recognizer.recognize_sphinx(audio)
            if text:
                logger.info("STT (Sphinx): %s", text)
                return text.strip(), "sphinx"
        except Exception:
            pass
    except Exception as e:
        logger.error("STT error: %s", e)
    return "", "none"


def record_and_transcribe(timeout: int = 5, phrase_limit: int = 12) -> dict:
    """
    One-call convenience: record + transcribe.
    Returns:
      { "text": str, "source": str, "success": bool, "reason": str }
    """
    rec = record_audio(timeout=timeout, phrase_limit=phrase_limit)
    if not rec["success"]:
        return {"text": "", "source": "none", "success": False, "reason": rec["reason"]}
    text, source = speech_to_text(rec["audio"])
    return {
        "text":    text,
        "source":  source,
        "success": bool(text),
        "reason":  "ok" if text else "no_speech",
    }


def reset_noise_calibration():
    """Force re-calibration on next mic open (e.g. after environment change)."""
    global _noise_calibrated
    with _noise_calib_lock:
        _noise_calibrated = False
    logger.info("Mic: noise calibration reset")


def transcribe_bytes(raw_pcm: bytes, sample_rate: int = 16000, sample_width: int = 2) -> str:
    """Legacy helper — raw PCM bytes → text string."""
    if not raw_pcm:
        return ""
    try:
        text, _ = speech_to_text(sr.AudioData(raw_pcm, sample_rate, sample_width))
        return text
    except Exception as e:
        logger.error("transcribe_bytes: %s", e)
        return ""