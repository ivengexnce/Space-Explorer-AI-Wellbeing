import cv2
import numpy as np
import logging

logger = logging.getLogger(__name__)

_prev_frame = None


def detect_behavior(frame: np.ndarray) -> str:
    """
    Motion-based behavior classifier.
    Returns: "Hyperactive" | "Restless" | "Calm" | "Inactive"
    """
    global _prev_frame

    try:
        small  = cv2.resize(frame, (320, 240))
        gray   = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        gray   = cv2.GaussianBlur(gray, (5, 5), 0)

        if _prev_frame is None:
            _prev_frame = gray
            return "Calm"

        diff      = cv2.absdiff(_prev_frame, gray)
        _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        movement  = int(np.sum(thresh))

        _prev_frame = gray

        if movement > 3_000_000:
            return "Hyperactive"
        if movement > 1_000_000:
            return "Restless"
        if movement < 200_000:
            return "Inactive"
        return "Calm"

    except Exception as exc:
        logger.error("behavior_detector error: %s", exc)
        return "Unknown"