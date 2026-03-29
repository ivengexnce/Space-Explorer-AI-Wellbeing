import cv2
import logging
import numpy as np

logger = logging.getLogger(__name__)

# ── Haar cascade for fast face detection ─────────────────────────────────────
_face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)

# ── DeepFace import with graceful fallback ────────────────────────────────────
try:
    from deepface import DeepFace
    _DEEPFACE_OK = True
    logger.info("DeepFace loaded successfully")
except ImportError:
    _DEEPFACE_OK = False
    logger.warning("DeepFace not available — emotion detection disabled")


def detect_face_emotion(frame: np.ndarray) -> list[dict]:
    """
    Detect faces and emotions in a frame.

    Returns a list of dicts, one per face:
      {
        "emotion":    str,          # dominant emotion label
        "confidence": float | None, # 0.0–1.0 confidence
        "bbox":       (x, y, w, h), # bounding box in frame coords
        "all_emotions": dict        # full emotion probability map
      }

    Uses consistent key "bbox" (not "box") throughout.
    """
    results = []

    try:
        # ── Resize for speed ─────────────────────────────────────────────
        frame = cv2.resize(frame, (640, 480))
        gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # ── Fast Haar face detection ──────────────────────────────────────
        faces = _face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(60, 60),
        )

        if len(faces) == 0:
            return []

        if not _DEEPFACE_OK:
            # Return faces without emotion when DeepFace unavailable
            for (x, y, w, h) in faces:
                results.append({
                    "emotion":     "neutral",
                    "confidence":  None,
                    "bbox":        (int(x), int(y), int(w), int(h)),
                    "all_emotions": {},
                })
            return results

        # ── DeepFace emotion analysis ─────────────────────────────────────
        analysis = DeepFace.analyze(
            frame,
            actions=["emotion"],
            enforce_detection=False,
            detector_backend="opencv",
            silent=True,
        )

        if not isinstance(analysis, list):
            analysis = [analysis]

        for i, (x, y, w, h) in enumerate(faces):
            emotion      = "neutral"
            confidence   = None
            all_emotions = {}

            if i < len(analysis):
                entry        = analysis[i]
                emotion      = entry.get("dominant_emotion", "neutral")
                all_emotions = entry.get("emotion", {})
                # confidence = probability of dominant emotion (0–100 → 0.0–1.0)
                if emotion in all_emotions:
                    confidence = round(all_emotions[emotion] / 100.0, 3)

            results.append({
                "emotion":     emotion,
                "confidence":  float(confidence) if confidence is not None else None,
                "bbox":        (int(x), int(y), int(w), int(h)),
                "all_emotions": {k: float(v) for k, v in all_emotions.items()},
            })

    except Exception as exc:
        logger.error("detect_face_emotion error: %s", exc)

    return results