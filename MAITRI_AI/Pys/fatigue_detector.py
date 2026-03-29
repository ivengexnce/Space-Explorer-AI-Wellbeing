import cv2
import time
import logging

logger = logging.getLogger(__name__)

_eye_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_eye.xml"
)

# Per-call state (module-level, intentionally simple)
_last_eye_time: float = time.time()
_blink_count:   int   = 0
_prev_eyes_seen: bool = False


def detect_fatigue(frame) -> str:
    """
    Returns: "Awake" | "Drowsy" | "Fatigued" | "Normal"
    Also tracks blink events for future use.
    """
    global _last_eye_time, _blink_count, _prev_eyes_seen

    try:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        eyes = _eye_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(20, 20),
        )
        eyes_visible = len(eyes) > 0

        # Blink detection: eyes were visible, now aren't
        if _prev_eyes_seen and not eyes_visible:
            _blink_count += 1

        _prev_eyes_seen = eyes_visible

        if eyes_visible:
            _last_eye_time = time.time()
            return "Awake"

        elapsed = time.time() - _last_eye_time

        if elapsed > 6:
            return "Fatigued"
        if elapsed > 3:
            return "Drowsy"
        return "Normal"

    except Exception as exc:
        logger.error("fatigue_detector error: %s", exc)
        return "Unknown"