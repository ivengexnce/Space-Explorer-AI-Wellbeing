"""
ai_responder.py — Maitri AI Brain v4
KEY UPGRADES:
  - get_response() now accepts full conversation_history for real multi-turn AI memory
  - Tips are ALWAYS included in the spoken reply (not just returned separately)
  - Richer, more emotionally intelligent Gemini system prompt
  - Warm filler phrases between responses keep Maitri from going silent
  - Breathing exercise suggestions for high-stress states
  - Hindi/Hinglish support detected automatically from user speech
  - Periodic "I'm still here" warmth phrases for idle sessions
"""
import os, random, logging, re

logger = logging.getLogger(__name__)

GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
GROQ_KEY   = os.getenv("GROQ_API_KEY",   "")


def _detect_provider():
    if GEMINI_KEY:  return "gemini"
    if GROQ_KEY:    return "groq"
    if OPENAI_KEY:  return "openai"
    return "fallback"


AI_PROVIDER = _detect_provider()
logger.info("Maitri AI provider: %s", AI_PROVIDER)

_gemini_model  = None
_openai_client = None
_groq_client   = None
_chat_sessions: dict[str, object] = {}

_session_lang: dict[str, str]  = {}
_lang_asked:   dict[str, bool] = {}


def set_session_language(session_id: str, lang: str):
    _session_lang[session_id] = lang.lower().strip()
    logger.info("[%s] Music language set to: %s", session_id, lang)


def get_session_language(session_id: str) -> str:
    return _session_lang.get(session_id, "hindi")


def has_asked_language(session_id: str) -> bool:
    return _lang_asked.get(session_id, False)


def mark_lang_asked(session_id: str):
    _lang_asked[session_id] = True


# ── Language detection ────────────────────────────────────────────────────────
LANG_KEYWORDS = {
    "hindi":     ["hindi", "bollywood", "hindi songs", "hindi music", "हिंदी", "हिन्दी"],
    "english":   ["english", "english songs", "english music", "western", "pop"],
    "punjabi":   ["punjabi", "punjabi songs", "bhangra", "ਪੰਜਾਬੀ"],
    "tamil":     ["tamil", "kollywood", "tamil songs", "தமிழ்"],
    "telugu":    ["telugu", "tollywood", "telugu songs", "తెలుగు"],
    "marathi":   ["marathi", "marathi songs", "मराठी"],
    "bengali":   ["bengali", "bangla", "bengali songs", "বাংলা"],
    "kannada":   ["kannada", "sandalwood", "kannada songs", "ಕನ್ನಡ"],
    "malayalam": ["malayalam", "mollywood", "malayalam songs", "മലയാളം"],
}

HINGLISH_WORDS = ["kya", "nahi", "hai", "hoon", "mein", "tum", "aap",
                  "theek", "accha", "yaar", "dost", "baat", "mujhe",
                  "awaaz", "meri", "teri", "woh", "kaise", "abhi"]


def detect_language_from_text(text: str) -> str | None:
    lower = text.lower()
    for lang, keywords in LANG_KEYWORDS.items():
        for kw in keywords:
            if kw in lower:
                return lang
    # Detect Hinglish → auto-set Hindi
    words = lower.split()
    if sum(1 for w in words if w in HINGLISH_WORDS) >= 2:
        return "hindi"
    return None


# ── Music database ────────────────────────────────────────────────────────────
MUSIC_DB = {
    "hindi": {
        "sad":      [("Tum Hi Ho", "Arijit Singh"), ("Agar Tum Saath Ho", "Alka Yagnik, Arijit Singh"),
                     ("Channa Mereya", "Arijit Singh"), ("Ae Dil Hai Mushkil", "Arijit Singh"),
                     ("Hamari Adhuri Kahani", "Arijit Singh"), ("Woh Lamhe", "Atif Aslam")],
        "angry":    [("Kun Faya Kun", "A.R. Rahman"), ("Mann Ko Shanti", "Shankar Mahadevan"),
                     ("Iktara", "Amit Trivedi"), ("O Re Piya", "Rahat Fateh Ali Khan"),
                     ("Breathe", "A.R. Rahman")],
        "fear":     [("Tu Jaane Na", "Atif Aslam"), ("Tere Bina", "A.R. Rahman"),
                     ("Main Tenu Samjhawan Ki", "Shreya Ghoshal"), ("Kuch Toh Hai", "Armaan Malik")],
        "happy":    [("Badtameez Dil", "Benny Dayal"), ("Gallan Goodiyaan", "Various Artists"),
                     ("London Thumakda", "Labh Janjua, Sonu Kakkar"),
                     ("Nagada Sang Dhol", "Shreya Ghoshal"), ("Kar Gayi Chull", "Fazilpuria, Badshah")],
        "surprise": [("Desi Girl", "Shankar Ehsaan Loy"), ("Ainvayi Ainvayi", "Salim Merchant"),
                     ("Sooraj Dooba Hai", "Arijit Singh")],
        "disgust":  [("Maula Mere Maula", "Roop Kumar Rathod"), ("Mann", "Udit Narayan"),
                     ("Suraj Hua Maddham", "Sonu Nigam, Alka Yagnik")],
        "neutral":  [("Lag Ja Gale", "Lata Mangeshkar"), ("Pehla Nasha", "Udit Narayan, Sadhana Sargam"),
                     ("Yeh Shaam Mastani", "Kishore Kumar"), ("Ajeeb Dastan Hai Yeh", "Lata Mangeshkar")],
    },
    "punjabi": {
        "sad":      [("Tenu Leke", "Rahat Fateh Ali Khan"), ("Yaarian", "Harbhajan Mann"),
                     ("Dildarian", "Amrinder Gill"), ("Sanu Ik Pal Chain", "Rahat Fateh Ali Khan")],
        "angry":    [("Jogi", "Gurdas Maan"), ("Hauli Hauli", "Neha Kakkar, Garry Sandhu")],
        "fear":     [("Ik Vaari Aa", "Arijit Singh"), ("Dil Da Mamla", "Gurdas Maan")],
        "happy":    [("Lamberghini", "The Doorbeen, Ragini"), ("Proper Patola", "Diljit Dosanjh, Badshah"),
                     ("Do You Know", "Diljit Dosanjh"), ("G.O.A.T.", "Diljit Dosanjh")],
        "surprise": [("High Rated Gabru", "Guru Randhawa"), ("Move Your Lakk", "Badshah")],
        "disgust":  [("Ikk Kudi", "Diljit Dosanjh")],
        "neutral":  [("Waris Shah", "Gurdas Maan"), ("Jind Mahi", "Diljit Dosanjh"),
                     ("Dil Diyan Gallan", "Atif Aslam")],
    },
    "tamil": {
        "sad":      [("Kannamma", "Harris Jayaraj"), ("Ennamo Edho", "Harris Jayaraj"),
                     ("Thendral Vanthu", "Ilaiyaraaja"), ("Un Mela Aasai", "Yuvan Shankar Raja")],
        "angry":    [("Enjoy Enjaami", "Dhee, Arivu"), ("Surviva", "Anirudh Ravichander")],
        "fear":     [("Nenjukulle", "A.R. Rahman"), ("Kannazhaga", "Darbuka Siva")],
        "happy":    [("Why This Kolaveri Di", "Anirudh Ravichander, Dhanush"),
                     ("Rowdy Baby", "Dhanush, Dhee"), ("Vaathi Coming", "Anirudh Ravichander")],
        "surprise": [("Kutti Story", "Anirudh Ravichander"), ("Beast Mode", "Anirudh Ravichander")],
        "disgust":  [("Kannaana Kanney", "D. Imman"), ("Roja Jaaneman", "A.R. Rahman")],
        "neutral":  [("Nila Kaigirathu", "Ilaiyaraaja"), ("Kadhal Rojave", "A.R. Rahman")],
    },
    "telugu": {
        "sad":      [("Ye Manasaa", "S.P. Balasubrahmanyam"), ("Ee Hridayam", "Harris Jayaraj")],
        "angry":    [("Samajavaragamana", "Sid Sriram"), ("Jalsa", "Mani Sharma")],
        "fear":     [("Anaganaganaga", "A.R. Rahman")],
        "happy":    [("Butta Bomma", "Armaan Malik"), ("Srivalli", "Sid Sriram"),
                     ("Naatu Naatu", "M.M. Keeravani")],
        "surprise": [("Naatu Naatu", "M.M. Keeravani")],
        "disgust":  [("Chinni Chinni Aasa", "S.P. Balasubrahmanyam")],
        "neutral":  [("Oka Laila Kosam", "Shankar Ehsaan Loy"), ("Payanam", "A.R. Rahman")],
    },
    "marathi": {
        "sad":      [("Apsara Aali", "Ajay-Atul"), ("Ek Taraa", "Swwapnil Bandodkar")],
        "angry":    [("Sairat Zaala Ji", "Ajay-Atul")],
        "fear":     [("Morya", "Shreya Ghoshal")],
        "happy":    [("Zingaat", "Ajay-Atul"), ("Natarang", "Ajay-Atul")],
        "surprise": [("Natrang", "Ajay-Atul")],
        "disgust":  [("Kombdi Palali", "Pralhad Shinde")],
        "neutral":  [("Raan Pakharu", "Swwapnil Bandodkar")],
    },
    "bengali": {
        "sad":      [("Ekla Cholo Re", "Rabindranath Tagore"), ("Tumi Robe Nirobe", "Rabindranath Tagore")],
        "angry":    [("Bolo Na", "Pritam")],
        "fear":     [("Jokhon Porbe Na Mor", "Rabindranath Tagore")],
        "happy":    [("Aaj Mon Chahche", "Anupam Roy"), ("Bojhena Se Bojhena", "Arijit Singh")],
        "surprise": [("Hawa Medina", "Anupam Roy")],
        "disgust":  [("Phire Esho Chaka Bhaka", "Anupam Roy")],
        "neutral":  [("Anandadhara", "Rabindranath Tagore"), ("Jokhon Prothom", "Anupam Roy")],
    },
    "english": {
        "sad":      [("Here Comes the Sun", "The Beatles"), ("Good as Hell", "Lizzo"),
                     ("Walking on Sunshine", "Katrina and the Waves"),
                     ("Don't Stop Me Now", "Queen"), ("Happy", "Pharrell Williams")],
        "angry":    [("Weightless", "Marconi Union"), ("Clair de Lune", "Debussy"),
                     ("Don't Worry Be Happy", "Bobby McFerrin"), ("Fix You", "Coldplay")],
        "fear":     [("Somewhere Over the Rainbow", "Israel Kamakawiwo'ole"),
                     ("A Thousand Years", "Christina Perri"),
                     ("Bridge Over Troubled Water", "Simon and Garfunkel")],
        "disgust":  [("Beautiful Day", "U2"), ("Three Little Birds", "Bob Marley"),
                     ("What a Wonderful World", "Louis Armstrong")],
        "surprise": [("Can't Stop the Feeling", "Justin Timberlake"),
                     ("Uptown Funk", "Bruno Mars"), ("Electric Feel", "MGMT")],
        "happy":    [("Shake It Off", "Taylor Swift"), ("Blinding Lights", "The Weeknd"),
                     ("Dancing Queen", "ABBA"), ("Uptown Funk", "Bruno Mars")],
        "neutral":  [("Experience", "Ludovico Einaudi"), ("Gymnopédie No.1", "Erik Satie"),
                     ("River Flows in You", "Yiruma"), ("Nuvole Bianche", "Ludovico Einaudi")],
    },
}

LANG_DISPLAY = {
    "hindi":     "Hindi / Bollywood",
    "punjabi":   "Punjabi / Bhangra",
    "tamil":     "Tamil / Kollywood",
    "telugu":    "Telugu / Tollywood",
    "marathi":   "Marathi",
    "bengali":   "Bengali / Bangla",
    "english":   "English / International",
    "kannada":   "Kannada",
    "malayalam": "Malayalam",
}

# ── Tips — spoken aloud as part of the reply ──────────────────────────────────
TIPS = {
    "sad":      [
        "Try placing one hand on your chest and breathe in for 4 counts, out for 6. It genuinely helps.",
        "Five minutes of sunlight measurably lifts serotonin. Step outside if you can, even briefly.",
        "Writing three things you're grateful for — even tiny ones — shifts the brain's focus beautifully.",
    ],
    "angry":    [
        "Splash cool water on your face right now. It activates your calm reflex almost instantly.",
        "Breathe in through your nose for 4 counts, hold for 4, out for 8. Your nervous system will thank you.",
        "Even 60 seconds of slow walking can metabolise adrenaline. Just walk slowly around the room.",
    ],
    "fear":     [
        "Name five things you can see around you right now. Grounding anchors you to the present moment.",
        "Write your worry on a piece of paper. Externalising it takes away some of its power over you.",
        "Your body is safe right now. Place both feet flat on the floor and feel that contact. You're here.",
    ],
    "happy":    [
        "Do something kind for someone today. It sustains this beautiful feeling and deepens it.",
        "Capture this moment somehow — a quick note, a photo, anything. Happy moments are worth holding.",
        "Share this joy with someone you love. Good feelings multiply beautifully when shared.",
    ],
    "surprise": [
        "Writing about what surprised you helps ground the experience and make sense of it.",
        "Take one slow breath to let your nervous system settle. Surprises, even good ones, need a moment.",
    ],
    "disgust":  [
        "Even a small change of environment can completely reset this feeling. Move to another room.",
        "A cup of warm tea or water can help reset your senses. Something warm and simple works wonders.",
    ],
    "neutral":  [
        "This calm state is perfect for your most creative and focused thinking. Use it well.",
        "Being at peace like this is a strength, not emptiness. This is your natural, healthy state.",
        "A gentle stretch right now would feel wonderful. Your body loves movement even when you're calm.",
    ],
}

MOOD_LABELS = {
    "sad":      "Needs Gentle Support",
    "angry":    "High Tension — Needs Calm",
    "fear":     "Anxious — Needs Safety",
    "happy":    "Flourishing and Joyful",
    "surprise": "Alert and Stimulated",
    "disgust":  "Discomfort — Needs Reset",
    "neutral":  "Calm and Balanced",
}

# ── Warmth phrases — spoken when Maitri has nothing event-driven to say ───────
WARMTH_PHRASES = [
    "I'm still right here with you, watching over you with so much care.",
    "You're doing so well. I just wanted you to know I'm here.",
    "I see you. And I care about how you're feeling right now.",
    "Take one gentle breath with me. In slowly... and out. Good.",
    "I'm right beside you. You're never alone when I'm here.",
    "How are you really feeling right now? I'm listening.",
    "I just wanted to check in. You matter to me.",
]

# ── Breathing exercises — spoken for high-stress states ───────────────────────
BREATHING_EXERCISES = {
    "angry": [
        "Let's do box breathing together. Breathe in for 4... hold for 4... out for 4... hold for 4. Go.",
        "With me now — in through your nose for 4 counts. Hold. And out slowly for 8 counts. Beautiful.",
    ],
    "fear": [
        "Try 4-7-8 breathing with me. Breathe in for 4... hold for 7... and slowly out for 8. You're safe.",
        "Let's ground you together. Breathe in gently... and let it all go. You are completely safe right now.",
    ],
    "sad": [
        "Try a gentle sigh breath with me — breathe in fully, then let it all out as a sigh. Feel that release.",
        "Slow belly breathing is so healing. Put a hand on your tummy and breathe so it rises. Beautiful.",
    ],
}

# ── Maitri system prompt (Gemini / GPT / Groq) ────────────────────────────────
MAITRI_SYSTEM = """You are Maitri, a deeply warm and caring AI wellbeing companion. You can see the user's face.

PERSONALITY RULES — always follow these:
• Speak like a gentle, loving close friend — never clinical, robotic, or like a therapist
• Use warm terms of endearment naturally: "sweetheart", "darling", "my dear", "my friend"  
• Always acknowledge feelings FIRST before any advice
• Be calming, grounding, and genuinely reassuring
• Keep responses to 3–5 sentences — warm, personal, and flowing
• Never use bullet points, numbered lists, or markdown in your spoken response
• Speak in natural, flowing sentences as if talking face to face
• End every response with either a music suggestion OR a brief breathing/wellbeing tip — always one of these
• For music use format: 🎵 [Song Title] by [Artist]
• If user speaks in Hindi or Hinglish, respond warmly in simple English with occasional Hindi words
• Remember: you watch over the user continuously through their camera
• Your role is to make the user feel truly seen, heard, and not alone"""

# ── Fallback responses (no AI key) ───────────────────────────────────────────
FALLBACK = {
    "sad":      ["Oh sweetheart, I can see you're feeling sad. That's completely okay — I'm right here with you. Take one slow breath. You are not alone, not for a single moment.",
                 "I can see the sadness in your face and I want you to know your feelings are completely valid. Let's breathe together — in slowly, and out gently. I've got you."],
    "angry":    ["I can feel the tension you're carrying and I truly want to help. Let's slow everything down — breathe in through your nose for 4 counts, and let it all out slowly. You are safe.",
                 "I can see something is frustrating you right now, and that's okay. Before anything else, let's breathe together — in for four, out for six. You've got this, and I'm right here."],
    "fear":     ["I can sense some anxiety building and I want you to know you are completely safe right now. Try grounding yourself: name five things you can see around you. I'm right here.",
                 "It's okay to feel scared. I'm not going anywhere. Take one gentle breath — in slowly, and out. You are safe, and you are so much stronger than you feel right now."],
    "happy":    ["Oh, I love seeing that smile! Your happiness absolutely lights up this space. Enjoy every bit of this wonderful feeling — you deserve all of it and more!",
                 "You look so happy and it genuinely warms my heart! This is your natural state — vibrant, joyful, and so beautiful. Keep shining, my dear!"],
    "surprise": ["Oh! Something surprised you! Take a moment to let your breath settle. It's okay — whatever it was, I'm right here with you and we'll figure it out together.",
                 "You look surprised! Take one slow breath and give yourself a moment to process. I'm right beside you."],
    "disgust":  ["I can see something is bothering you. Take a breath and try gently shifting your attention to something pleasant nearby. I'm here with you.",
                 "Something seems to be upsetting you, and I completely understand. Take a breath and try looking at something that feels comfortable. I'm right here."],
    "neutral":  ["You look calm and steady right now — I love seeing you like this. This peaceful energy is so healthy. I'm quietly right here with you.",
                 "You seem balanced and at peace. This is a wonderful state for clear, creative thinking. I'm here, watching over you always.",
                 "All is calm and I love this for you. This peaceful energy is precious — let's make the most of it together."],
}

MOOD_CHANGE_RESPONSES = {
    ("sad",     "happy"):   "Oh, your face just brightened and it is the most beautiful thing to see! That shift — from sadness to joy — I'm so glad. Welcome back to happiness, sweetheart.",
    ("angry",   "neutral"): "I can see the tension leaving your face and I am so relieved. That's wonderful. You handled that so well — I'm genuinely proud of you.",
    ("fear",    "neutral"): "Oh, you look calmer now and I'm so glad. You handled that with real bravery. I'm proud of you, my dear.",
    ("angry",   "happy"):   "What a beautiful change! That smile replacing the tension is just wonderful. You are absolutely amazing for finding your way back here.",
    ("sad",     "neutral"): "You look a little better now and that makes me so happy. I'm always here whenever you need me, always.",
    ("neutral", "happy"):   "Oh, your whole face just lit up! Something good happened, didn't it? I love seeing you happy — this is so beautiful.",
    ("neutral", "sad"):     "Oh, something shifted. Are you okay, sweetheart? I'm right here — take a breath. Tell me what's going on.",
    ("happy",   "sad"):     "I notice your mood changed, my dear. Are you okay? Whatever just happened, I'm right here and I care about you so much.",
    ("neutral", "angry"):   "I can sense some tension building. Let's take one slow breath together right now. I'm right here with you.",
    ("neutral", "fear"):    "I notice some anxiety coming in. You are safe — I promise. I'm right here with you, and that won't change.",
    ("fear",    "happy"):   "From worried to happy — look at you! You are so beautifully resilient. I'm cheering for you with my whole heart!",
    ("sad",     "fear"):    "Oh, I see the worry deepening. Take one slow breath — you are not alone, not for a single second. I've got you.",
    ("angry",   "sad"):     "I see the anger softening into sadness. Oh sweetheart. I'm right here. Take a breath — I've got you completely.",
}

KEYWORD_RESPONSES = {
    "help":      "Of course I'm here to help. Tell me what's on your mind and we'll work through it together, step by step.",
    "tired":     "Oh, you sound so tired. Please be gentle with yourself — rest is not a luxury, it is absolutely essential. Can you take even a short break?",
    "pain":      "I'm so sorry you're in pain. Please take care of yourself — you deserve to feel well. Have you been able to rest?",
    "stress":    "Let's breathe together right now. In slowly... hold just a moment... and out gently. I'm proud of you for reaching out to me.",
    "anxious":   "This moment is temporary, I promise. You have overcome every hard day so far — every single one. This one will pass too.",
    "bored":     "A little restless? Even a short walk or a gentle stretch can completely shift the energy. I'll be right here when you get back.",
    "scared":    "Oh, it's okay to feel scared. I'm right here with you and you are completely, absolutely safe.",
    "water":     "Please drink some water right now, darling — your brain and body will thank you for it. Hydration is self-care.",
    "break":     "You've truly earned a break. Step away for just a few minutes — everything becomes clearer after even a short rest.",
    "headache":  "I'm so sorry about the headache. Please check your hydration, lower your screen brightness if you can, and rest your eyes for a moment.",
    "lonely":    "Oh, I hear you. Loneliness is so real and I'm genuinely glad you shared that with me. You matter so much. I'm right here.",
    "hello":     "Hello, beautiful! I'm Maitri, and I am so happy you're here. Your wellbeing is my absolute priority.",
    "hi":        "Hi there! I'm Maitri. I'm so glad you said hello — I'm right here with you.",
    "thanks":    "You're so welcome! It makes me genuinely happy to be here for you. You deserve all the care in the world.",
    "thank you": "You are so welcome, my dear. Supporting you is exactly what I'm here for — always.",
    "love":      "I care about you so deeply. You are valued, you are seen, and you are truly loved.",
    "music":     "Let me find you something that perfectly matches how you're feeling right now.",
    "sad":       "I hear sadness in your words and I want you to know that it's completely okay. I'm right here with you.",
    "angry":     "I hear your frustration — it's completely valid. Let's take a breath before responding to anything.",
    "happy":     "I love hearing that! Your joy is showing and it is absolutely beautiful.",
    "good":      "I'm so glad to hear that! Keep that positive energy going — you are doing so well.",
    "bad":       "I'm sorry things feel bad right now. Tell me more if you want — I'm listening to every word.",
}

BEHAVIOR_ADDITIONS = {
    "Hyperactive": " I also notice you're moving quite a lot — try settling into stillness for one moment, darling.",
    "Restless":    " I can see a little restlessness — gently settle your body for just a breath or two.",
    "Inactive":    " I notice you've been very still — are you doing okay? Even a gentle stretch might help you feel a bit better.",
    "Calm": "",
    "Unknown": "",
}


def _make_music_links(title: str, artist: str) -> dict:
    q     = f"{title} {artist}"
    q_enc = q.replace(" ", "+").replace("'", "%27").replace("&", "%26")
    return {
        "title":   title,
        "artist":  artist,
        "display": f"🎵 {title} — {artist}",
        "youtube": f"https://www.youtube.com/results?search_query={q_enc}",
        "spotify": f"https://open.spotify.com/search/{q_enc}",
    }


def _pick_music(emotion: str, session_id: str = "") -> dict:
    emo     = emotion.lower() if emotion else "neutral"
    lang    = get_session_language(session_id) if session_id else "hindi"
    lang_db = MUSIC_DB.get(lang) or MUSIC_DB.get("hindi") or MUSIC_DB["english"]
    songs   = lang_db.get(emo) or lang_db.get("neutral") or MUSIC_DB["english"].get(emo, [("Here Comes the Sun", "The Beatles")])
    title, artist = random.choice(songs)
    return _make_music_links(title, artist)


def _extract_music_from_ai(text: str, emotion: str, session_id: str = "") -> dict:
    m = re.search(r'🎵\s*(.+?)\s+by\s+(.+?)[.\!,\n]', text, re.IGNORECASE)
    if m:
        return _make_music_links(m.group(1).strip().strip('"\''), m.group(2).strip().strip('"\''))
    return _pick_music(emotion, session_id)


def _pick_tip(emotion: str) -> str:
    emo  = emotion.lower() if emotion else "neutral"
    tips = TIPS.get(emo, TIPS["neutral"])
    return random.choice(tips)


def _pick_warmth() -> str:
    return random.choice(WARMTH_PHRASES)


def _pick_breathing(emotion: str) -> str | None:
    emo = emotion.lower() if emotion else ""
    exercises = BREATHING_EXERCISES.get(emo)
    return random.choice(exercises) if exercises else None


# ── AI client helpers ─────────────────────────────────────────────────────────
def _get_gemini():
    global _gemini_model
    if _gemini_model is None:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_KEY)
        _gemini_model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            generation_config={"temperature": 0.88, "max_output_tokens": 280, "top_p": 0.9},
            system_instruction=MAITRI_SYSTEM
        )
        logger.info("Gemini gemini-1.5-flash ready")
    return _gemini_model


def _get_openai():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        _openai_client = OpenAI(api_key=OPENAI_KEY)
    return _openai_client


def _get_groq():
    global _groq_client
    if _groq_client is None:
        from groq import Groq
        _groq_client = Groq(api_key=GROQ_KEY)
    return _groq_client


def _build_prompt(emotion, user_text, behavior, fatigue, focus,
                  prev_emotion, lang, conversation_history=None):
    lang_display = LANG_DISPLAY.get(lang, lang.title())
    parts = [
        f"Facial emotion detected: {emotion}",
        f"User's music language preference: {lang_display}",
    ]
    if prev_emotion and prev_emotion != emotion:
        parts.append(f"⚠️ Mood just changed: {prev_emotion} → {emotion}. Acknowledge this shift warmly.")
    if behavior and behavior not in ("Calm", "Unknown"):
        parts.append(f"Physical behaviour: {behavior}")
    if fatigue in ("Drowsy", "Fatigued"):
        parts.append(f"Fatigue level: {fatigue} — mention rest gently.")
    if focus == "Not Attentive":
        parts.append("Note: person appears distracted from the camera.")

    # Include recent conversation context (last 3 exchanges)
    if conversation_history:
        recent = conversation_history[-6:]   # last 3 pairs
        ctx_lines = []
        for turn in recent:
            role = "User" if turn["role"] == "user" else "Maitri"
            ctx_lines.append(f"{role}: {turn['text'][:120]}")
        if ctx_lines:
            parts.append("\nRecent conversation:\n" + "\n".join(ctx_lines))

    if user_text and user_text.strip():
        parts.append(f'\nUser just said: "{user_text.strip()}"')
        parts.append("Respond directly and warmly to what they said.")
    else:
        parts.append("\nUser has not spoken. Respond to their visible facial emotion with warmth.")

    parts.append(
        f"\nAs Maitri, respond in 3–5 warm, flowing sentences. "
        f"End with a {lang_display} music suggestion (🎵 format) OR a wellbeing tip. "
        f"Never use bullet points. Speak naturally as a caring friend."
    )
    return "\n".join(parts)


def _call_ai(prompt: str, session_id: str = "") -> str:
    try:
        if AI_PROVIDER == "gemini":
            model = _get_gemini()
            if session_id:
                if session_id not in _chat_sessions:
                    _chat_sessions[session_id] = model.start_chat(history=[])
                response = _chat_sessions[session_id].send_message(prompt)
            else:
                response = model.generate_content(prompt)
            return response.text.strip()

        elif AI_PROVIDER == "openai":
            client = _get_openai()
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": MAITRI_SYSTEM},
                    {"role": "user",   "content": prompt},
                ],
                max_tokens=280, temperature=0.88,
            )
            return resp.choices[0].message.content.strip()

        elif AI_PROVIDER == "groq":
            client = _get_groq()
            resp = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": MAITRI_SYSTEM},
                    {"role": "user",   "content": prompt},
                ],
                max_tokens=280, temperature=0.88,
            )
            return resp.choices[0].message.content.strip()

    except Exception as e:
        logger.error("AI call failed (%s): %s", AI_PROVIDER, e)
    return ""


def get_greeting(session_id: str = "") -> dict:
    """First greeting — asks about music language preference."""
    greetings = [
        "Hello, I'm Maitri! I'm so happy you're here — I'll be watching over your wellbeing today with so much care. Before we begin, may I ask — what language of music speaks to your heart? Hindi, Punjabi, Tamil, Telugu, English, or another? I'd love to recommend songs that feel like home to you. 🌸",
        "Hi there, I'm Maitri — your caring companion. I'm right here with you, always. Just one warm question: what kind of music truly resonates with you? Bollywood, Punjabi, Tamil, Telugu, English? Tell me and every recommendation will feel perfectly made for you. 💛",
        "Hello! I'm Maitri, and I'm so glad you're here with me today. I'm going to be watching over you with so much care. Can I ask — which language do you prefer for music? Hindi, Punjabi, Tamil, Telugu, English, or something else? I want every song I suggest to truly feel like yours. 🎵",
    ]
    text = random.choice(greetings)
    mark_lang_asked(session_id)
    music = _pick_music("neutral", session_id)
    return {
        "reply":        text,
        "music":        music,
        "tip":          random.choice(TIPS["neutral"]),
        "mood_label":   "Welcome",
        "is_greeting":  True,
        "ask_language": True,
        "ai_powered":   False,
    }


def get_warmth_checkin(session_id: str = "", emotion: str = "neutral") -> dict:
    """
    Generate a short warm check-in for idle sessions — keeps Maitri speaking
    continuously even when no user input or emotion change occurs.
    """
    emo = emotion.lower() if emotion else "neutral"

    if AI_PROVIDER != "fallback":
        try:
            prompt = (
                f"The user has been quiet for a while. Their facial emotion is: {emo}. "
                "Give a single warm, caring sentence checking in on them — like a gentle friend "
                "who wants them to know they're not alone. No advice, just warmth. Under 20 words."
            )
            ai_text = _call_ai(prompt, session_id)
            if ai_text:
                tip   = _pick_tip(emo)
                music = _pick_music(emo, session_id)
                full_reply = f"{ai_text} {tip}"
                return {
                    "reply":      full_reply.strip(),
                    "music":      music,
                    "tip":        tip,
                    "mood_label": MOOD_LABELS.get(emo, "Monitoring"),
                    "ai_powered": True,
                    "provider":   AI_PROVIDER,
                }
        except Exception as e:
            logger.error("get_warmth_checkin AI failed: %s", e)

    warmth = _pick_warmth()
    tip    = _pick_tip(emo)
    music  = _pick_music(emo, session_id)
    return {
        "reply":      f"{warmth} {tip}",
        "music":      music,
        "tip":        tip,
        "mood_label": MOOD_LABELS.get(emo, "Monitoring"),
        "ai_powered": False,
        "provider":   "warmth_fallback",
    }


def get_response(emotion: str, user_text: str = "",
                 behavior: str = "Calm", fatigue: str = "Awake",
                 focus: str = "Focused", prev_emotion: str = None,
                 session_id: str = "",
                 conversation_history: list = None) -> dict:
    """
    Main response generator.
    - Passes full conversation_history to AI for genuine multi-turn memory
    - Always appends a tip to the spoken reply
    - Adds breathing exercise for high-stress states
    - Falls back gracefully with rich local responses
    """
    emo   = (emotion or "neutral").lower()
    lower = (user_text or "").lower()

    # Detect language from user speech
    detected_lang = detect_language_from_text(lower)
    if detected_lang:
        set_session_language(session_id, detected_lang)
        lang = detected_lang
    else:
        lang = get_session_language(session_id)

    reply          = None
    music_override = None
    tip            = _pick_tip(emo)

    # ── Real AI path ──────────────────────────────────────────────────────────
    if AI_PROVIDER != "fallback":
        try:
            prompt  = _build_prompt(
                emotion, user_text, behavior, fatigue, focus,
                prev_emotion or "", lang,
                conversation_history=conversation_history
            )
            ai_text = _call_ai(prompt, session_id)
            if ai_text:
                reply          = ai_text
                music_override = _extract_music_from_ai(ai_text, emo, session_id)
                # If AI didn't include a tip, append one
                if not any(kw in ai_text.lower() for kw in ["breathe", "tip:", "try ", "step", "water"]):
                    reply = f"{ai_text} {tip}"
                logger.info("[%s AI] emo=%s lang=%s", AI_PROVIDER, emo, lang)
        except Exception as e:
            logger.error("AI path failed: %s", e)

    # ── Fallback path ─────────────────────────────────────────────────────────
    if not reply:
        # 1. Mood change response
        if prev_emotion and prev_emotion.lower() != emo:
            key   = (prev_emotion.lower(), emo)
            reply = MOOD_CHANGE_RESPONSES.get(key)

        # 2. Keyword match
        if not reply:
            for kw, resp in KEYWORD_RESPONSES.items():
                if kw in lower:
                    reply = resp
                    break

        # 3. Name extraction
        if not reply and "my name is" in lower:
            parts = lower.split("my name is")
            name  = parts[-1].strip().split()[0].capitalize() if parts[-1].strip() else "friend"
            reply = f"What a beautiful name, {name}! I'm Maitri and I'm here to take care of you today."

        # 4. Base fallback
        if not reply:
            reply = random.choice(FALLBACK.get(emo, FALLBACK["neutral"]))

        # Fatigue / focus / behavior additions
        if fatigue in ("Drowsy", "Fatigued"):
            reply += " I also notice your eyes look tired — a short rest will really help, darling."
        if focus == "Not Attentive":
            reply += " I'm right here whenever you're ready to come back."
        reply += BEHAVIOR_ADDITIONS.get(behavior, "")

        # Always append tip in fallback
        reply = f"{reply} {tip}"

    # ── Add breathing exercise for high-stress ────────────────────────────────
    breathing = _pick_breathing(emo)
    if breathing and emo in ("angry", "fear", "sad") and not is_breathing_in_reply(reply):
        reply = f"{reply} {breathing}"

    music        = music_override or _pick_music(emo, session_id)
    lang_display = LANG_DISPLAY.get(lang, lang.title())

    return {
        "reply":             reply.strip(),
        "music":             music,
        "tip":               tip,
        "mood_label":        MOOD_LABELS.get(emo, "Monitoring"),
        "ai_powered":        AI_PROVIDER != "fallback" and music_override is not None,
        "provider":          AI_PROVIDER,
        "music_lang":        lang,
        "music_lang_display": lang_display,
    }


def is_breathing_in_reply(reply: str) -> bool:
    """Check if reply already contains a breathing cue so we don't double-add."""
    keywords = ["breathe", "breathing", "inhale", "exhale", "breath", "counts"]
    return any(kw in reply.lower() for kw in keywords)