"""
voice_output.py — Maitri TTS Engine v2
FIXES the 'run loop already started' crash from pyttsx3.
The engine lives permanently in ONE dedicated daemon thread.
All other threads just put text in the queue — they never touch the engine.
"""
import pyttsx3
import threading
import queue
import logging
import time

logger = logging.getLogger(__name__)

_q      = queue.Queue(maxsize=2)   # max 2 items — drops stale speech
_lock   = threading.Lock()
_thread = None
_speaking_flag  = threading.Event()   # set while TTS is producing audio
_speaking_until = [0.0]               # timestamp when it's safe to open mic


# ── Voice worker — created ONCE, lives forever ────────────────────────────────
def _worker():
    """
    This is the ONLY thread that ever calls pyttsx3.
    It owns the engine for its entire lifetime.
    """
    try:
        engine = pyttsx3.init()
    except Exception as e:
        logger.error("pyttsx3 init failed: %s", e)
        return

    _select_female_voice(engine)
    engine.setProperty("rate",   145)   # slow, warm, caring
    engine.setProperty("volume", 0.92)
    logger.info("Maitri TTS worker ready")

    while True:
        try:
            text = _q.get(timeout=1.0)   # blocks until speech arrives
        except queue.Empty:
            continue

        if text is None:
            logger.info("TTS worker shutting down")
            break

        try:
            _speaking_flag.set()
            # Estimate how long this will take at 145 WPM
            # 145 WPM = ~2.4 chars/sec after accounting for pauses
            word_count = len(text.split())
            estimated_secs = max(2.0, (word_count / 145.0) * 60.0)
            _speaking_until[0] = time.time() + estimated_secs + 1.5  # +1.5s hardware buffer

            logger.info("Maitri speaks (~%.1fs): %s", estimated_secs, text[:80])
            engine.say(text)
            engine.runAndWait()          # blocks until audio is done

            # Extra hardware buffer — speaker output lags runAndWait by up to 1s
            # Keep the flag set so mic stays closed during this window
            tail = max(0.0, _speaking_until[0] - time.time())
            if tail > 0:
                time.sleep(min(tail, 2.0))

        except RuntimeError as e:
            if "run loop already started" in str(e):
                logger.warning("TTS run-loop conflict, re-initialising engine")
                try:
                    engine.stop()
                except Exception:
                    pass
                try:
                    engine = pyttsx3.init()
                    _select_female_voice(engine)
                    engine.setProperty("rate", 145)
                    engine.setProperty("volume", 0.92)
                except Exception as e2:
                    logger.error("TTS re-init failed: %s", e2)
            else:
                logger.error("TTS RuntimeError: %s", e)
        except Exception as e:
            logger.error("TTS error: %s", e)
        finally:
            _speaking_until[0] = 0.0
            _speaking_flag.clear()
            try:
                _q.task_done()
            except Exception:
                pass


def _select_female_voice(engine) -> None:
    voices = engine.getProperty("voices") or []
    preferred = ["zira", "hazel", "female", "woman", "samantha",
                 "karen", "moira", "tessa", "fiona", "victoria", "eva"]
    for kw in preferred:
        for v in voices:
            if kw in (v.id or "").lower() or kw in (v.name or "").lower():
                engine.setProperty("voice", v.id)
                logger.info("Maitri voice: %s", v.name)
                return
    if len(voices) > 1:
        engine.setProperty("voice", voices[1].id)
        logger.info("Maitri voice fallback: %s", voices[1].name)


def _ensure_worker():
    """Start the TTS worker thread if it isn't alive."""
    global _thread
    with _lock:
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(
                target=_worker, daemon=True, name="maitri-tts"
            )
            _thread.start()
            time.sleep(0.1)   # tiny wait for engine to initialise


# ── Public API ────────────────────────────────────────────────────────────────
def speak(text: str) -> None:
    """
    Queue text for Maitri to speak.
    Non-blocking — returns immediately.
    Softens robotic phrases before speaking.
    Drops the oldest queued item if the queue is full (keeps speech current).
    """
    if not text or not text.strip():
        return

    _ensure_worker()

    # Soften robotic language
    text = (text
            .replace("detected", "noticed")
            .replace("I detect", "I can sense")
            .replace("CRITICAL", "something important")
            .replace("Error", "a small issue"))

    text = text.strip()

    # Clear stale queued speech so Maitri always says the LATEST message
    while not _q.empty():
        try:
            _q.get_nowait()
            _q.task_done()
        except Exception:
            break

    try:
        _q.put_nowait(text)
    except queue.Full:
        pass   # still speaking — skip


def is_speaking() -> bool:
    """
    Returns True while TTS audio is actively playing OR hardware buffer not drained.
    Uses both the event flag AND a time-based estimate to prevent early mic opening.
    """
    if _speaking_flag.is_set():
        return True
    # Also block if we're within the hardware-drain window
    if _speaking_until[0] > 0 and time.time() < _speaking_until[0]:
        return True
    return False


def get_speaking_end_time() -> float:
    """Returns the estimated timestamp when it is safe to open the microphone."""
    return max(_speaking_until[0], time.time() if _speaking_flag.is_set() else 0.0)


def shutdown():
    """Gracefully stop the TTS worker."""
    try:
        _q.put_nowait(None)
    except Exception:
        pass