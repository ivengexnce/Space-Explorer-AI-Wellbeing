"""
MAITRI AI v5.0 — Complete Backend
Features:
  - Continuous face + emotion detection (DeepFace)
  - Real AI responses (Gemini / Groq / OpenAI / fallback)
  - Maitri speaks on EVERY emotion change automatically
  - Always-on mic: listens, speaks, loops back immediately
  - Behavior + fatigue + focus detection
  - WebSocket real-time streaming
  - Session analytics, reports, heatmap data
  - Alert system with cooldown
  - Music recommendations per emotion
"""

import sys, io, cv2, numpy as np, time, logging, threading, uuid
from collections import deque, Counter
from datetime import datetime
from functools import wraps

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room, leave_room

from Pys.report          import save_log, build_report_data
from Pys.voice_output    import speak, is_speaking
from Pys.vision_module   import detect_face_emotion
from Pys.fatigue_detector import detect_fatigue
from Pys.behavior_detector import detect_behavior
from Pys.ai_responder    import get_response, get_greeting, AI_PROVIDER, set_session_language, detect_language_from_text, LANG_DISPLAY
from Pys.alert_system    import check_alert
from Pys.audio_module    import record_audio, speech_to_text

# ── App ───────────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config["SECRET_KEY"] = "maitri-v5"
CORS(app, resources={r"/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading",
                    logger=False, engineio_logger=False)

# ── Logging (Windows UTF-8 safe) ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("maitri.log", encoding="utf-8"),
        logging.StreamHandler(io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
        )),
    ],
)
for noisy in ("werkzeug", "engineio", "socketio"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
# Suppress OPTIONS preflight spam
import logging as _log
class _NoOptions(logging.Filter):
    def filter(self, record):
        return "OPTIONS" not in (record.getMessage())
logging.getLogger("werkzeug").addFilter(_NoOptions())
logger = logging.getLogger(__name__)

# ── Tunable constants ─────────────────────────────────────────────────────────
WINDOW_SIZE        = 10    # emotion smoothing window
FACE_TIMEOUT       = 5     # seconds → "Not Attentive"
VOICE_AUTO_SEC     = 15    # periodic auto-voice if no mood change
ALERT_COOLDOWN     = 30    # seconds between same alert
TREND_WINDOW       = 30    # frames for trend analytics
FRAME_TIMEOUT      = 15    # seconds → session stale
WATCHDOG_SEC       = 5     # watchdog sweep interval
DETECT_TIMEOUT     = 8     # hard timeout on DeepFace call
MAX_ERRORS         = 10    # consecutive errors → degraded
MIN_FRAME_BYTES    = 1000  # minimum valid JPEG size

# ── Sessions ──────────────────────────────────────────────────────────────────
sessions: dict[str, dict] = {}
_ses_lock = threading.Lock()


def _new_session() -> dict:
    return {
        "emotion_window":    deque(maxlen=WINDOW_SIZE),
        "trend_log":         deque(maxlen=TREND_WINDOW),
        "full_log":          [],
        "conversation":      [],        # [{role, text, ts}]
        # timing
        "last_seen_time":    time.time(),
        "last_frame_time":   time.time(),
        "last_voice_time":   0,
        "last_alert_time":   0,
        # counters
        "frame_count":       0,
        "alert_count":       0,
        "error_count":       0,
        "consec_errors":     0,
        "mood_change_count": 0,
        # status
        "started_at":        datetime.utcnow().isoformat(),
        "status":            "active",
        # voice state
        "voice_status":      "",
        "spoken_text":       "",
        "ai_reply":          "",
        "music_rec":         "",
        "last_tip":          "",
        # biometric signals
        "last_detection_ms": 0,
        "zero_face_streak":  0,
        "behavior":          "Calm",
        "fatigue":           "Awake",
        "focus":             "Focused",
        # mood tracking
        "prev_emotion":      "",
        "current_emotion":   "neutral",
        "greeting_sent":     False,
        # continuous voice loop flag
        "voice_loop_active": False,
        # alert history (for report)
        "_alert_history":    [],
    }


def get_or_create(sid: str) -> dict:
    with _ses_lock:
        if sid not in sessions:
            sessions[sid] = _new_session()
            logger.info("Session created: %s", sid)
        return sessions[sid]


def require_session(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        sid = request.headers.get("X-Session-ID") or str(uuid.uuid4())
        request.sid_val = sid
        request.ses     = get_or_create(sid)
        return f(*args, **kwargs)
    return wrapper


# ── Watchdog ──────────────────────────────────────────────────────────────────
def _watchdog():
    logger.info("Watchdog started")
    while True:
        time.sleep(WATCHDOG_SEC)
        try:
            with _ses_lock:
                snap = list(sessions.items())
            for sid, s in snap:
                elapsed = time.time() - s["last_frame_time"]
                if elapsed > FRAME_TIMEOUT and s["status"] == "active":
                    s["status"] = "stale"
                    socketio.emit("session_health", {
                        "session_id": sid, "status": "stale",
                        "reason": f"No frames for {elapsed:.0f}s",
                        "timestamp": datetime.utcnow().isoformat(),
                    }, room=sid)
                # Voice loop watchdog: resurrect if it died unexpectedly
                vt = _voice_threads.get(sid) if "_voice_threads" in dir() else None
                if s.get("voice_loop_active") and (vt is None or not vt.is_alive()):
                    logger.warning("[%s] Voice loop died — restarting", sid)
                    start_voice_loop(s, sid)
                if s["consec_errors"] >= MAX_ERRORS and s["status"] != "degraded":
                    s["status"] = "degraded"
                    socketio.emit("session_health", {
                        "session_id": sid, "status": "degraded",
                        "reason": f"{s['consec_errors']} consecutive errors",
                        "timestamp": datetime.utcnow().isoformat(),
                    }, room=sid)
                if s["status"] == "active":
                    socketio.emit("heartbeat", {
                        "session_id": sid, "frame_count": s["frame_count"],
                        "last_frame_ago": round(elapsed, 1),
                        "timestamp": datetime.utcnow().isoformat(),
                    }, room=sid)
        except Exception as e:
            logger.error("Watchdog: %s", e)


threading.Thread(target=_watchdog, daemon=True, name="watchdog").start()


# ── Safe DeepFace detection (hard timeout) ────────────────────────────────────
def safe_detect(frame) -> tuple[list, float]:
    result, err = [], [None]

    def _run():
        try:
            result.extend(detect_face_emotion(frame) or [])
        except Exception as e:
            err[0] = e

    t = threading.Thread(target=_run, daemon=True)
    t0 = time.time()
    t.start(); t.join(timeout=DETECT_TIMEOUT)
    ms = (time.time() - t0) * 1000
    if t.is_alive():
        logger.warning("DeepFace timeout %.0fms", ms)
        return [], ms
    if err[0]:
        logger.error("DeepFace error: %s", err[0])
        return [], ms
    return result, ms


# ── Analysis helpers ──────────────────────────────────────────────────────────
def get_mental_state(log: list) -> str:
    if len(log) < 5: return "Analyzing..."
    c = Counter(log)
    if c["sad"]      >= 4: return "High Stress"
    if c["angry"]    >= 4: return "Aggressive"
    if c["fear"]     >= 3: return "Anxious"
    if c["happy"]    >= 4: return "Positive"
    if c["surprise"] >= 3: return "Stimulated"
    return "Stable"


def get_focus_state(detected: bool, s: dict) -> str:
    if detected:
        s["last_seen_time"] = time.time()
        s["zero_face_streak"] = 0
        return "Focused"
    s["zero_face_streak"] = s.get("zero_face_streak", 0) + 1
    return "Not Attentive" if time.time() - s["last_seen_time"] > FACE_TIMEOUT else "Idle"


def get_trend(trend_log: deque) -> dict:
    if not trend_log: return {}
    c = Counter(trend_log); n = len(trend_log)
    return {k: round(v / n * 100, 1) for k, v in c.most_common()}


# ── Maitri speak & respond helper ────────────────────────────────────────────
def maitri_respond(session: dict, sid: str, emotion: str,
                   user_text: str = "", prev_emotion: str = "",
                   mood_changed: bool = False):
    """
    Generate AI response, speak it, emit voice_update via WebSocket.
    This is the central function that powers ALL of Maitri's voice output.
    """
    ai = get_response(
        emotion, user_text,
        behavior=session.get("behavior", "Calm"),
        fatigue=session.get("fatigue", "Awake"),
        focus=session.get("focus", "Focused"),
        prev_emotion=prev_emotion if mood_changed else None,
        session_id=sid,
    )
    session["ai_reply"]  = ai["reply"]
    session["music_rec"] = ai["music"]
    session["last_tip"]  = ai["tip"]

    if user_text:
        session["conversation"].append({
            "role": "user", "text": user_text,
            "ts": datetime.utcnow().isoformat()
        })
    session["conversation"].append({
        "role": "maitri", "text": ai["reply"],
        "ts": datetime.utcnow().isoformat()
    })

    # Speak (non-blocking queue)
    speak(ai["reply"])
    # Mark session so transcript handler ignores Maitri's own voice
    session["maitri_speaking_until"] = time.time() + max(3.0, len(ai["reply"].split()) / 2.0)

    # Broadcast to frontend
    socketio.emit("voice_update", {
        "voice_status":  "speaking",
        "spoken_text":   user_text,
        "ai_reply":      ai["reply"],
        "music_rec":     ai["music"],
        "tip":           ai["tip"],
        "mood_label":    ai.get("mood_label", ""),
        "mood_changed":  mood_changed,
        "ai_powered":    ai.get("ai_powered", False),
        "ai_provider":   ai.get("provider", "fallback"),
        "timestamp":     datetime.utcnow().isoformat(),
    }, room=sid)

    logger.info("[%s] Maitri→ %s...", sid, ai["reply"][:60])


# ── Continuous voice loop ─────────────────────────────────────────────────────
# Runs in a daemon thread per session.
# Listens → transcribes → responds → repeats immediately.
_voice_lock = threading.Lock()


def continuous_voice_loop(session: dict, sid: str):
    """
    Always-on voice loop — NEVER stops unless explicitly told to.
    Bugs fixed:
      - Does NOT check session status (stale/degraded no longer kills voice)
      - maitri_respond errors are caught per-iteration, loop continues
      - Mic errors: retries after 1s, never exits
      - STT network errors: waits 2s then continues
      - TTS overlap: waits politely then listens again
    """
    logger.info("[%s] Voice loop started", sid)
    session["voice_loop_active"] = True
    consecutive_errors = 0

    while session.get("voice_loop_active", False):

        # ── Wait for TTS to finish + hardware drain before listening ─────
        # is_speaking() now includes a time-based buffer after runAndWait
        waited = 0
        while is_speaking() and waited < 60:   # max 18s wait
            time.sleep(0.3)
            waited += 1

        # Extra silence after speaking — prevents mic picking up echo/reverb
        # Scale with how long Maitri was speaking (longer speech = more reverb)
        if waited > 0:
            silence_buf = min(1.5, 0.3 + waited * 0.05)
            time.sleep(silence_buf)

        # ── Emit listening status ─────────────────────────────────────────
        try:
            session["voice_status"] = "Listening..."
            socketio.emit("voice_update", {
                "voice_status": "Listening...",
                "timestamp": datetime.utcnow().isoformat(),
            }, room=sid)
        except Exception:
            pass

        # ── Record ────────────────────────────────────────────────────────
        audio = None
        try:
            audio = record_audio(timeout=5, phrase_limit=12)
        except Exception as e:
            logger.error("[%s] record_audio exception: %s", sid, e)
            consecutive_errors += 1
            time.sleep(1)
            continue

        # ── Transcribe ────────────────────────────────────────────────────
        spoken = ""
        try:
            spoken = speech_to_text(audio)
        except Exception as e:
            logger.error("[%s] speech_to_text exception: %s", sid, e)
            consecutive_errors += 1
            time.sleep(1)
            continue

        # ── Respond if speech detected ────────────────────────────────────
        if spoken and spoken.strip():
            consecutive_errors = 0
            session["spoken_text"] = spoken.strip()
            logger.info("[%s] Heard: %s", sid, spoken.strip())

            try:
                session["voice_status"] = "Processing..."
                socketio.emit("voice_update", {
                    "voice_status": "Processing...",
                    "spoken_text":  spoken.strip(),
                    "timestamp":    datetime.utcnow().isoformat(),
                }, room=sid)
            except Exception:
                pass

            try:
                maitri_respond(
                    session, sid,
                    emotion=session.get("current_emotion", "neutral"),
                    user_text=spoken.strip(),
                    prev_emotion=session.get("prev_emotion", ""),
                    mood_changed=False,
                )
                session["last_voice_time"] = time.time()
            except Exception as e:
                logger.error("[%s] maitri_respond error: %s", sid, e)
                # Don't stop the loop — just log and continue listening

        else:
            # No speech or timeout — loop back silently
            consecutive_errors = max(0, consecutive_errors - 1)

        # ── Back-off if too many consecutive errors (e.g. no internet) ────
        if consecutive_errors >= 5:
            logger.warning("[%s] Voice loop: %d consecutive errors, pausing 5s", sid, consecutive_errors)
            time.sleep(5)
            consecutive_errors = 0  # reset and try again

    session["voice_status"] = ""
    session["voice_loop_active"] = False
    logger.info("[%s] Voice loop stopped", sid)


# Track voice threads so we can check if they're still alive
_voice_threads: dict[str, threading.Thread] = {}

def start_voice_loop(session: dict, sid: str):
    """
    Start the continuous voice loop.
    Resurrects the thread if it died unexpectedly.
    """
    existing = _voice_threads.get(sid)
    if existing and existing.is_alive():
        logger.info("[%s] Voice loop already running", sid)
        return
    # Reset the flag so the loop body runs
    session["voice_loop_active"] = True
    t = threading.Thread(
        target=continuous_voice_loop,
        args=(session, sid), daemon=True, name=f"voice-{sid[:8]}"
    )
    _voice_threads[sid] = t
    t.start()
    logger.info("[%s] Voice loop thread started (tid=%s)", sid, t.ident)


def stop_voice_loop(session: dict):
    session["voice_loop_active"] = False


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def home():
    return jsonify({
        "status": "running", "service": "MAITRI AI", "version": "5.0",
        "ai_provider": AI_PROVIDER, "time": datetime.utcnow().isoformat(),
    })


@app.route("/analyze", methods=["POST"])
@require_session
def analyze():
    ses = request.ses
    sid = request.sid_val

    try:
        # ── Decode frame ──────────────────────────────────────────────────
        f = request.files.get("image")
        if not f: return jsonify({"error": "No image"}), 400

        raw = f.read()
        if len(raw) < MIN_FRAME_BYTES:
            return jsonify({"error": "Frame too small"}), 422

        frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            ses["consec_errors"] += 1
            return jsonify({"error": "Decode failed"}), 422

        ses["last_frame_time"] = time.time()
        ses["frame_count"]    += 1

        # Recover from stale
        if ses["status"] == "stale":
            ses["status"] = "active"
            socketio.emit("session_health", {
                "session_id": sid, "status": "active",
                "reason": "Frames resumed", "timestamp": datetime.utcnow().isoformat(),
            }, room=sid)

        # ── Behavior (fast, no model) ──────────────────────────────────────
        behavior = detect_behavior(frame)
        ses["behavior"] = behavior

        # ── Face + emotion ─────────────────────────────────────────────────
        faces, det_ms = safe_detect(frame)
        ses["last_detection_ms"] = det_ms

        if not faces:
            ses["consec_errors"] += 1
            focus = get_focus_state(False, ses)
            if ses["zero_face_streak"] >= WINDOW_SIZE:
                ses["emotion_window"].clear()

            p = _build_payload(sid, ses, {
                "emotion": "No face detected", "raw_emotion": "No face",
                "confidence": None, "bounding_boxes": [], "all_emotions": {},
                "state": "Unknown", "focus": focus, "fatigue": "Unknown",
                "alert": None, "reply": "Please stay in frame.",
                "music_rec": ses["music_rec"], "tip": ses["last_tip"],
                "mood_label": "", "behavior": behavior,
                "det_ms": round(det_ms), "mood_changed": False,
            })
            socketio.emit("analysis_update", p, room=sid)
            return jsonify(p)

        # ── Face found ─────────────────────────────────────────────────────
        ses["consec_errors"] = 0
        if ses["status"] == "degraded": ses["status"] = "active"

        primary    = faces[0]
        raw_emo    = primary.get("emotion", "neutral")
        confidence = primary.get("confidence")
        bboxes     = [f2.get("bbox") for f2 in faces if f2.get("bbox")]
        all_emos   = primary.get("all_emotions", {})

        ses["emotion_window"].append(raw_emo)
        ses["trend_log"].append(raw_emo)
        ses["full_log"].append(raw_emo)
        final_emo = Counter(ses["emotion_window"]).most_common(1)[0][0]

        state   = get_mental_state(list(ses["emotion_window"]))
        focus   = get_focus_state(True, ses)
        fatigue = detect_fatigue(frame)
        trend   = get_trend(ses["trend_log"])

        ses["fatigue"]         = fatigue
        ses["focus"]           = focus
        ses["current_emotion"] = final_emo

        # ── Greet on first detection ───────────────────────────────────────
        if not ses["greeting_sent"]:
            ses["greeting_sent"] = True
            greet = get_greeting(session_id=sid)
            ses["ai_reply"]  = greet["reply"]
            ses["music_rec"] = greet["music"]
            ses["last_tip"]  = greet["tip"]
            ses["conversation"].append({
                "role": "maitri", "text": greet["reply"],
                "ts": datetime.utcnow().isoformat()
            })
            speak(greet["reply"])
            socketio.emit("voice_update", {
                "voice_status": "speaking",
                "ai_reply":     greet["reply"],
                "music_rec":    greet["music"],
                "tip":          greet["tip"],
                "mood_label":   greet["mood_label"],
                "mood_changed": False,
                "ai_powered":   False,
                "ai_provider":  "greeting",
                "timestamp":    datetime.utcnow().isoformat(),
            }, room=sid)
            # Start continuous voice loop
            start_voice_loop(ses, sid)

        # ── Detect mood change → immediate Maitri response ────────────────
        prev_emo      = ses["prev_emotion"]
        mood_changed  = bool(prev_emo) and prev_emo != final_emo
        ses["prev_emotion"] = final_emo

        now = time.time()
        if mood_changed:
            ses["mood_change_count"] += 1
            logger.info("[%s] Mood: %s → %s", sid, prev_emo, final_emo)
            # Respond immediately to mood change (non-blocking thread)
            threading.Thread(
                target=maitri_respond,
                kwargs=dict(session=ses, sid=sid, emotion=final_emo,
                            user_text="", prev_emotion=prev_emo,
                            mood_changed=True),
                daemon=True
            ).start()
            ses["last_voice_time"] = now
        elif now - ses["last_voice_time"] > VOICE_AUTO_SEC and not is_speaking():
            # Periodic check-in even if mood stable
            threading.Thread(
                target=maitri_respond,
                kwargs=dict(session=ses, sid=sid, emotion=final_emo,
                            user_text="", prev_emotion="",
                            mood_changed=False),
                daemon=True
            ).start()
            ses["last_voice_time"] = now

        # ── Alert (with cooldown) ──────────────────────────────────────────
        alert = check_alert(list(ses["emotion_window"]))
        if alert and (now - ses["last_alert_time"]) < ALERT_COOLDOWN:
            alert = None
        elif alert:
            ses["last_alert_time"] = now
            ses["alert_count"]    += 1
            ses["_alert_history"].append({
                "alert": alert, "frame": ses["frame_count"],
                "ts": datetime.utcnow().isoformat()
            })

        # ── Build payload ──────────────────────────────────────────────────
        p = _build_payload(sid, ses, {
            "emotion": final_emo, "raw_emotion": raw_emo,
            "confidence": confidence, "bounding_boxes": bboxes,
            "all_emotions": all_emos, "state": state, "focus": focus,
            "fatigue": fatigue, "alert": alert,
            "reply":     ses["ai_reply"],
            "music_rec": ses["music_rec"],
            "tip":       ses["last_tip"],
            "mood_label": "",
            "trend": trend, "behavior": behavior,
            "det_ms": round(det_ms), "mood_changed": mood_changed,
            "mood_change_count": ses["mood_change_count"],
        })
        socketio.emit("analysis_update", p, room=sid)

        logger.info("[%s] f=%d emo=%s→%s state=%s det=%.0fms",
                    sid, ses["frame_count"], prev_emo or "?", final_emo, state, det_ms)
        return jsonify(p)

    except Exception as e:
        ses["consec_errors"] += 1
        ses["error_count"]   += 1
        logger.exception("[%s] Error: %s", sid, e)
        return jsonify({"error": str(e)}), 500


def _build_payload(sid: str, ses: dict, data: dict) -> dict:
    base = {
        "session_id":        sid,
        "session_status":    ses["status"],
        "frame_count":       ses["frame_count"],
        "alert_count":       ses["alert_count"],
        "detection_ms":      data.pop("det_ms", 0),
        "voice_status":      ses["voice_status"],
        "spoken_text":       ses["spoken_text"],
        "ai_voice_reply":    ses["ai_reply"],
        "music_rec":         ses["music_rec"],
        "tip":               ses["last_tip"],
        "trend":             data.pop("trend", get_trend(ses["trend_log"])),
        "mood_change_count": ses.get("mood_change_count", 0),
        "ai_provider":       AI_PROVIDER,
        "timestamp":         datetime.utcnow().isoformat(),
    }
    base.update(data)
    return base


# ── Voice control endpoints ───────────────────────────────────────────────────
@app.route("/session/<session_id>/voice/start", methods=["POST"])
def voice_start(session_id: str):
    with _ses_lock:
        ses = sessions.get(session_id)
    if not ses: return jsonify({"error": "Not found"}), 404
    start_voice_loop(ses, session_id)
    return jsonify({"status": "voice loop started"})


@app.route("/session/<session_id>/voice/stop", methods=["POST"])
def voice_stop(session_id: str):
    with _ses_lock:
        ses = sessions.get(session_id)
    if not ses: return jsonify({"error": "Not found"}), 404
    stop_voice_loop(ses)
    return jsonify({"status": "voice loop stopped"})


# ── Standard CRUD routes ──────────────────────────────────────────────────────
@app.route("/session/<session_id>/report")
def report(session_id: str):
    with _ses_lock: ses = sessions.get(session_id)
    if not ses: return jsonify({"error": "Not found"}), 404
    log = ses["full_log"]; c = Counter(log)
    return jsonify({
        "session_id": session_id, "started_at": ses["started_at"],
        "generated_at": datetime.utcnow().isoformat(),
        "status": ses["status"], "frame_count": ses["frame_count"],
        "alert_count": ses["alert_count"], "mood_change_count": ses.get("mood_change_count", 0),
        "error_count": ses["error_count"], "last_detection_ms": ses["last_detection_ms"],
        "emotion_distribution": dict(c.most_common()),
        "dominant_emotion": c.most_common(1)[0][0] if log else None,
        "final_mental_state": get_mental_state(log[-10:] if log else []),
        "trend": get_trend(ses["trend_log"]), "log_length": len(log),
        "last_spoken_text": ses["spoken_text"], "last_ai_reply": ses["ai_reply"],
        "last_music_rec": ses["music_rec"],
        "conversation_turns": len(ses["conversation"]),
        "ai_provider": AI_PROVIDER,
    })


@app.route("/session/<session_id>/conversation")
def conversation(session_id: str):
    with _ses_lock: ses = sessions.get(session_id)
    if not ses: return jsonify({"error": "Not found"}), 404
    return jsonify({"conversation": ses["conversation"], "count": len(ses["conversation"])})


@app.route("/session/<session_id>/save", methods=["POST"])
def save(session_id: str):
    with _ses_lock: ses = sessions.get(session_id)
    if not ses: return jsonify({"error": "Not found"}), 404
    try:
        # Build rich meta for the report
        meta = {
            "started_at":        ses.get("started_at", ""),
            "frame_count":       ses.get("frame_count", 0),
            "alert_count":       ses.get("alert_count", 0),
            "mood_change_count": ses.get("mood_change_count", 0),
            "ai_provider":       AI_PROVIDER,
            "status":            ses.get("status", ""),
            "last_detection_ms": ses.get("last_detection_ms", 0),
        }
        data = save_log(
            ses["full_log"], session_id,
            conversation=ses.get("conversation", []),
            alerts=ses.get("_alert_history", []),
            session_meta=meta,
        )
        paths = data.get("_saved_paths", {})
        return jsonify({
            "status":  "saved",
            "paths":   paths,
            "entries": len(ses["full_log"]),
            "score":   data.get("wellbeing_score"),
            "grade":   data.get("wellbeing_grade"),
        })
    except Exception as e:
        logger.exception("Save failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/session/<session_id>/report-full")
def report_full(session_id: str):
    """
    Returns the complete rich report JSON for frontend rendering.
    Does NOT save to disk (use /save for that).
    """
    with _ses_lock: ses = sessions.get(session_id)
    if not ses: return jsonify({"error": "Not found"}), 404
    try:
        meta = {
            "started_at":        ses.get("started_at", ""),
            "frame_count":       ses.get("frame_count", 0),
            "alert_count":       ses.get("alert_count", 0),
            "mood_change_count": ses.get("mood_change_count", 0),
            "ai_provider":       AI_PROVIDER,
            "status":            ses.get("status", ""),
            "last_detection_ms": ses.get("last_detection_ms", 0),
            "fatigue":           ses.get("fatigue", ""),
            "behavior":          ses.get("behavior", ""),
            "focus":             ses.get("focus", ""),
            "last_music_rec":    ses.get("music_rec", ""),
            "last_tip":          ses.get("last_tip", ""),
        }
        data = build_report_data(
            ses["full_log"], session_id,
            conversation=ses.get("conversation", []),
            alerts=ses.get("_alert_history", []),
            session_meta=meta,
        )
        # Remove raw log from response to keep payload small
        data.pop("_full_log", None)
        return jsonify(data)
    except Exception as e:
        logger.exception("report-full error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/reports")
def list_reports():
    """List all saved report files in the reports/ folder."""
    from pathlib import Path
    import os
    report_dir = Path("reports")
    if not report_dir.exists():
        return jsonify({"reports": []})
    files = []
    for f in sorted(report_dir.glob("report_*.json"), reverse=True):
        try:
            stat = f.stat()
            files.append({
                "filename": f.name,
                "path":     str(f),
                "size_kb":  round(stat.st_size / 1024, 1),
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
        except Exception:
            pass
    return jsonify({"reports": files[:50]})  # last 50


@app.route("/session/<session_id>/recover", methods=["POST"])
def recover(session_id: str):
    with _ses_lock: ses = sessions.get(session_id)
    if not ses: return jsonify({"error": "Not found"}), 404
    old = ses["status"]
    ses.update({"status": "active", "consec_errors": 0,
                "zero_face_streak": 0, "last_frame_time": time.time()})
    socketio.emit("session_health", {
        "session_id": session_id, "status": "active",
        "reason": "Manual recovery", "timestamp": datetime.utcnow().isoformat(),
    }, room=session_id)
    return jsonify({"status": "recovered", "from": old})


@app.route("/session/<session_id>", methods=["DELETE"])
def delete(session_id: str):
    with _ses_lock:
        ses = sessions.pop(session_id, None)
    if ses: stop_voice_loop(ses)
    return jsonify({"status": "deleted" if ses else "not found"})


@app.route("/sessions")
def list_sessions():
    with _ses_lock:
        return jsonify([{
            "session_id": sid, "started_at": s["started_at"],
            "status": s["status"], "frame_count": s["frame_count"],
            "current_emotion": s.get("current_emotion", ""),
            "voice_active": s.get("voice_loop_active", False),
        } for sid, s in sessions.items()])


@app.route("/ai-status")
def ai_status():
    from ai_responder import GEMINI_KEY, OPENAI_KEY, GROQ_KEY
    return jsonify({
        "provider": AI_PROVIDER,
        "gemini_ready": bool(GEMINI_KEY),
        "openai_ready": bool(OPENAI_KEY),
        "groq_ready":   bool(GROQ_KEY),
        "fallback_active": AI_PROVIDER == "fallback",
        "message": (
            f"Maitri is powered by {AI_PROVIDER.upper()} AI"
            if AI_PROVIDER != "fallback"
            else "No API key set. Set GEMINI_API_KEY (free) for real AI."
        ),
    })


@app.route("/health")
def health():
    return jsonify({
        "status": "ok", "version": "5.0", "ai_provider": AI_PROVIDER,
        "active_sessions": sum(1 for s in sessions.values() if s["status"] == "active"),
        "total_sessions": len(sessions),
        "voice_loops_active": sum(1 for s in sessions.values() if s.get("voice_loop_active")),
        "time": datetime.utcnow().isoformat(),
    })


# ── WebSocket events ──────────────────────────────────────────────────────────
@socketio.on("connect")
def on_connect():
    logger.info("WS connect: %s", request.sid)


@socketio.on("disconnect")
def on_disconnect():
    logger.info("WS disconnect: %s", request.sid)


@socketio.on("join")
def on_join(data):
    sid = data.get("session_id", str(uuid.uuid4()))
    join_room(sid)
    get_or_create(sid)
    emit("joined", {"session_id": sid, "status": "ok", "ai_provider": AI_PROVIDER})


@socketio.on("leave")
def on_leave(data):
    sid = data.get("session_id")
    if sid: leave_room(sid)


@socketio.on("ping_session")
def on_ping(_):
    emit("pong_session", {"time": datetime.utcnow().isoformat()})


@socketio.on("set_language")
def on_set_language(data):
    """User selected their music language preference from the modal."""
    sid  = data.get("session_id", "")
    lang = data.get("lang", "hindi").lower().strip()
    if not sid: return

    set_session_language(sid, lang)
    lang_display = LANG_DISPLAY.get(lang, lang.title())
    logger.info("[%s] Language set via modal: %s", sid, lang)

    # Confirm back to frontend
    emit("language_update", {
        "session_id":   sid,
        "lang":         lang,
        "lang_display": lang_display,
    }, room=sid)

    # Maitri speaks a warm confirmation
    ses = get_or_create(sid)
    confirm_msg = (
        f"Wonderful! I'll recommend {lang_display} music for you from now on. "
        f"I love that — it makes everything feel more personal. 🎵"
    )
    ses["ai_reply"] = confirm_msg
    speak(confirm_msg)
    socketio.emit("voice_update", {
        "voice_status": "speaking",
        "ai_reply":     confirm_msg,
        "timestamp":    datetime.utcnow().isoformat(),
    }, room=sid)


@socketio.on("client_transcript")
def on_transcript(data):
    """
    Receives browser Web Speech API transcript.
    Echo guard: ignores transcript if Maitri is currently speaking
    (prevents her own TTS from being transcribed as user input).
    """
    sid  = data.get("session_id", "")
    text = (data.get("text") or "").strip()
    if not sid or not text: return

    # ── Echo guard ────────────────────────────────────────────────────────
    ses = sessions.get(sid)
    if ses:
        maitri_end = ses.get("maitri_speaking_until", 0)
        if time.time() < maitri_end:
            logger.info("[%s] Echo guard: ignoring transcript while Maitri is speaking: %s", sid, text[:40])
            return
        # Also reject transcripts that are suspiciously similar to Maitri's last reply
        last_reply = ses.get("ai_reply", "").lower()
        if last_reply and len(text) > 10:
            t_words = set(text.lower().split())
            r_words = set(last_reply.split())
            overlap = len(t_words & r_words)
            if overlap / max(len(t_words), 1) > 0.40:
                logger.info("[%s] Echo guard: transcript looks like Maitri's own speech (%.0f%% overlap), ignoring: %s",
                            sid, overlap/len(t_words)*100, text[:40])
                return

    # ── Detect language preference from user speech ───────────────────────────
    detected_lang = detect_language_from_text(text.lower())
    if detected_lang:
        set_session_language(sid, detected_lang)
        lang_display = LANG_DISPLAY.get(detected_lang, detected_lang.title())
        logger.info("[%s] Language preference detected from speech: %s", sid, detected_lang)
        # Emit language change to frontend
        socketio.emit("language_update", {
            "session_id": sid,
            "lang": detected_lang,
            "lang_display": lang_display,
        }, room=sid)

    ses = get_or_create(sid)
    ses["spoken_text"] = text
    ses["last_voice_time"] = time.time()

    # Respond in background so socket event returns fast
    threading.Thread(
        target=maitri_respond,
        kwargs=dict(session=ses, sid=sid,
                    emotion=ses.get("current_emotion", "neutral"),
                    user_text=text, prev_emotion="", mood_changed=False),
        daemon=True
    ).start()


@socketio.on("stop_voice")
def on_stop_voice(data):
    sid = data.get("session_id", "")
    if not sid: return
    ses = sessions.get(sid)
    if ses:
        stop_voice_loop(ses)
        emit("voice_update", {"voice_status": "stopped",
                               "timestamp": datetime.utcnow().isoformat()})


@socketio.on("start_voice")
def on_start_voice(data):
    sid = data.get("session_id", "")
    if not sid: return
    ses = get_or_create(sid)
    start_voice_loop(ses, sid)
    emit("voice_update", {"voice_status": "Listening...",
                           "timestamp": datetime.utcnow().isoformat()})


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("MAITRI AI v5.0 starting — AI provider: %s", AI_PROVIDER)
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
