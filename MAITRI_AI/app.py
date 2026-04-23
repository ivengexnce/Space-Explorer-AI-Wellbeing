"""
MAITRI AI v5.0 — Railway-Ready Backend
"""

import os, sys, io, cv2, numpy as np, time, logging, threading, uuid
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
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "maitri-v5")

# ── CORS — allow InfinityFree domain ─────────────────────────────────────────
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")
CORS(app, resources={r"/*": {"origins": ALLOWED_ORIGIN}})
socketio = SocketIO(app, cors_allowed_origins=ALLOWED_ORIGIN,
                    async_mode="threading", logger=False, engineio_logger=False)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),   # Railway shows stdout logs
    ],
)
for noisy in ("werkzeug", "engineio", "socketio"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ── Tunable constants ─────────────────────────────────────────────────────────
WINDOW_SIZE        = 10
FACE_TIMEOUT       = 5
VOICE_AUTO_SEC     = 15
ALERT_COOLDOWN     = 30
TREND_WINDOW       = 30
FRAME_TIMEOUT      = 15
WATCHDOG_SEC       = 5
DETECT_TIMEOUT     = 8
MAX_ERRORS         = 10
MIN_FRAME_BYTES    = 1000

# ── Sessions ──────────────────────────────────────────────────────────────────
sessions: dict[str, dict] = {}
_ses_lock = threading.Lock()


def _new_session() -> dict:
    return {
        "emotion_window":    deque(maxlen=WINDOW_SIZE),
        "trend_log":         deque(maxlen=TREND_WINDOW),
        "full_log":          [],
        "conversation":      [],
        "last_seen_time":    time.time(),
        "last_frame_time":   time.time(),
        "last_voice_time":   0,
        "last_alert_time":   0,
        "frame_count":       0,
        "alert_count":       0,
        "error_count":       0,
        "consec_errors":     0,
        "mood_change_count": 0,
        "started_at":        datetime.utcnow().isoformat(),
        "status":            "active",
        "voice_status":      "",
        "spoken_text":       "",
        "ai_reply":          "",
        "music_rec":         "",
        "last_tip":          "",
        "last_detection_ms": 0,
        "zero_face_streak":  0,
        "behavior":          "Calm",
        "fatigue":           "Awake",
        "focus":             "Focused",
        "prev_emotion":      "",
        "current_emotion":   "neutral",
        "greeting_sent":     False,
        "voice_loop_active": False,
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


# ── Safe DeepFace detection ────────────────────────────────────────────────────
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


def maitri_respond(session: dict, sid: str, emotion: str,
                   user_text: str = "", prev_emotion: str = "",
                   mood_changed: bool = False):
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

    speak(ai["reply"])
    session["maitri_speaking_until"] = time.time() + max(3.0, len(ai["reply"].split()) / 2.0)

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


_voice_lock = threading.Lock()
_voice_threads: dict[str, threading.Thread] = {}


def continuous_voice_loop(session: dict, sid: str):
    logger.info("[%s] Voice loop started", sid)
    session["voice_loop_active"] = True
    consecutive_errors = 0

    while session.get("voice_loop_active", False):
        waited = 0
        while is_speaking() and waited < 60:
            time.sleep(0.3)
            waited += 1
        if waited > 0:
            time.sleep(min(1.5, 0.3 + waited * 0.05))

        try:
            session["voice_status"] = "Listening..."
            socketio.emit("voice_update", {
                "voice_status": "Listening...",
                "timestamp": datetime.utcnow().isoformat(),
            }, room=sid)
        except Exception:
            pass

        audio = None
        try:
            audio = record_audio(timeout=5, phrase_limit=12)
        except Exception as e:
            logger.error("[%s] record_audio exception: %s", sid, e)
            consecutive_errors += 1
            time.sleep(1)
            continue

        spoken = ""
        try:
            spoken = speech_to_text(audio)
        except Exception as e:
            logger.error("[%s] speech_to_text exception: %s", sid, e)
            consecutive_errors += 1
            time.sleep(1)
            continue

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
        else:
            consecutive_errors = max(0, consecutive_errors - 1)

        if consecutive_errors >= 5:
            logger.warning("[%s] Voice loop: %d errors, pausing 5s", sid, consecutive_errors)
            time.sleep(5)
            consecutive_errors = 0

    session["voice_status"] = ""
    session["voice_loop_active"] = False
    logger.info("[%s] Voice loop stopped", sid)


def start_voice_loop(session: dict, sid: str):
    existing = _voice_threads.get(sid)
    if existing and existing.is_alive():
        return
    session["voice_loop_active"] = True
    t = threading.Thread(
        target=continuous_voice_loop,
        args=(session, sid), daemon=True, name=f"voice-{sid[:8]}"
    )
    _voice_threads[sid] = t
    t.start()


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

        if ses["status"] == "stale":
            ses["status"] = "active"
            socketio.emit("session_health", {
                "session_id": sid, "status": "active",
                "reason": "Frames resumed", "timestamp": datetime.utcnow().isoformat(),
            }, room=sid)

        behavior = detect_behavior(frame)
        ses["behavior"] = behavior

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
            start_voice_loop(ses, sid)

        prev_emo     = ses["prev_emotion"]
        mood_changed = bool(prev_emo) and prev_emo != final_emo
        ses["prev_emotion"] = final_emo

        now = time.time()
        if mood_changed:
            ses["mood_change_count"] += 1
            logger.info("[%s] Mood: %s → %s", sid, prev_emo, final_emo)
            threading.Thread(
                target=maitri_respond,
                kwargs=dict(session=ses, sid=sid, emotion=final_emo,
                            user_text="", prev_emotion=prev_emo, mood_changed=True),
                daemon=True
            ).start()
            ses["last_voice_time"] = now
        elif now - ses["last_voice_time"] > VOICE_AUTO_SEC and not is_speaking():
            threading.Thread(
                target=maitri_respond,
                kwargs=dict(session=ses, sid=sid, emotion=final_emo,
                            user_text="", prev_emotion="", mood_changed=False),
                daemon=True
            ).start()
            ses["last_voice_time"] = now

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


@app.route("/session/<session_id>/voice/start", methods=["POST"])
def voice_start(session_id: str):
    with _ses_lock: ses = sessions.get(session_id)
    if not ses: return jsonify({"error": "Not found"}), 404
    start_voice_loop(ses, session_id)
    return jsonify({"status": "voice loop started"})


@app.route("/session/<session_id>/voice/stop", methods=["POST"])
def voice_stop(session_id: str):
    with _ses_lock: ses = sessions.get(session_id)
    if not ses: return jsonify({"error": "Not found"}), 404
    stop_voice_loop(ses)
    return jsonify({"status": "voice loop stopped"})


@app.route("/session/<session_id>/report")
def report(session_id: str):
    with _ses_lock: ses = sessions.get(session_id)
    if not ses: return jsonify({"error": "Not found"}), 404
    log = ses["full_log"]; c = Counter(log)
    return jsonify({
        "session_id": session_id, "started_at": ses["started_at"],
        "generated_at": datetime.utcnow().isoformat(),
        "status": ses["status"], "frame_count": ses["frame_count"],
        "alert_count": ses["alert_count"],
        "mood_change_count": ses.get("mood_change_count", 0),
        "error_count": ses["error_count"],
        "last_detection_ms": ses["last_detection_ms"],
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
            "status": "saved", "paths": paths,
            "entries": len(ses["full_log"]),
            "score": data.get("wellbeing_score"),
            "grade": data.get("wellbeing_grade"),
        })
    except Exception as e:
        logger.exception("Save failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/session/<session_id>/report-full")
def report_full(session_id: str):
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
        data.pop("_full_log", None)
        return jsonify(data)
    except Exception as e:
        logger.exception("report-full error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/health")
def health():
    return jsonify({
        "status": "ok", "version": "5.0", "ai_provider": AI_PROVIDER,
        "active_sessions": sum(1 for s in sessions.values() if s["status"] == "active"),
        "total_sessions": len(sessions),
        "voice_loops_active": sum(1 for s in sessions.values() if s.get("voice_loop_active")),
        "time": datetime.utcnow().isoformat(),
    })


@app.route("/sessions")
def list_sessions():
    with _ses_lock:
        return jsonify([{
            "session_id": sid, "started_at": s["started_at"],
            "status": s["status"], "frame_count": s["frame_count"],
            "current_emotion": s.get("current_emotion", ""),
            "voice_active": s.get("voice_loop_active", False),
        } for sid, s in sessions.items()])


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
    sid  = data.get("session_id", "")
    lang = data.get("lang", "hindi").lower().strip()
    if not sid: return
    set_session_language(sid, lang)
    lang_display = LANG_DISPLAY.get(lang, lang.title())
    logger.info("[%s] Language set: %s", sid, lang)
    emit("language_update", {
        "session_id": sid, "lang": lang, "lang_display": lang_display,
    }, room=sid)
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
    sid  = data.get("session_id", "")
    text = (data.get("text") or "").strip()
    if not sid or not text: return

    ses = sessions.get(sid)
    if ses:
        maitri_end = ses.get("maitri_speaking_until", 0)
        if time.time() < maitri_end:
            return
        last_reply = ses.get("ai_reply", "").lower()
        if last_reply and len(text) > 10:
            t_words = set(text.lower().split())
            r_words = set(last_reply.split())
            overlap = len(t_words & r_words)
            if overlap / max(len(t_words), 1) > 0.40:
                return

    detected_lang = detect_language_from_text(text.lower())
    if detected_lang:
        set_session_language(sid, detected_lang)
        lang_display = LANG_DISPLAY.get(detected_lang, detected_lang.title())
        socketio.emit("language_update", {
            "session_id": sid, "lang": detected_lang,
            "lang_display": lang_display,
        }, room=sid)

    ses = get_or_create(sid)
    ses["spoken_text"] = text
    ses["last_voice_time"] = time.time()

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


# ── Entry point — Railway uses PORT env var ───────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info("MAITRI AI v5.0 starting on port %d — AI: %s", port, AI_PROVIDER)
    socketio.run(app, host="0.0.0.0", port=port, debug=False)
