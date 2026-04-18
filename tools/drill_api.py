"""
X-LINK Drill API — Adrian Live Coaching Dashboard Backend

Provides unlimited text-to-text coaching sessions with Adrian
via local Ollama inference. Zero Anam minutes consumed.
Includes persistent session memory across drills.
"""

from fastapi import APIRouter, HTTPException, UploadFile, File
import os
import json
import glob
import logging
import httpx
import tempfile
import subprocess
from datetime import datetime
from typing import Optional
from fastapi.responses import FileResponse

# Edge TTS for natural voice
try:
    import edge_tts
    HAS_EDGE_TTS = True
except ImportError:
    HAS_EDGE_TTS = False

# Binary document parsers
try:
    from docx import Document as DocxDocument
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

try:
    from PyPDF2 import PdfReader
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

# Local STT via faster-whisper (GPU accelerated)
try:
    from faster_whisper import WhisperModel
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False

_whisper_model = None

def _get_whisper_model():
    """Lazy-load Whisper model on first use to avoid slow startup."""
    global _whisper_model
    if _whisper_model is None and HAS_WHISPER:
        logger.info("Loading faster-whisper model (base.en) on CPU...")
        try:
            _whisper_model = WhisperModel("base.en", device="cpu", compute_type="int8")
            logger.info("Whisper model loaded successfully (CPU/int8).")
        except Exception as e:
            logger.error(f"Whisper model load failed: {e}")
    return _whisper_model

router = APIRouter()
logger = logging.getLogger("drill_api")

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADRIAN_KB_DIR = os.path.join(os.path.dirname(ROOT_DIR), "Adrian")
TRANSCRIPTS_DIR = os.path.join(ADRIAN_KB_DIR, "transcripts")
MEMORY_DIR = os.path.join(ADRIAN_KB_DIR, "memory")
MEMORY_FILE = os.path.join(MEMORY_DIR, "session_summaries.json")

OLLAMA_URL = "http://127.0.0.1:11434"
DRILL_MODEL = "gemma4:26b"
AUTOSAVE_INTERVAL = 10  # Auto-save transcript every N turns
ADRIAN_VOICE = "en-US-AndrewNeural"  # Warm, confident, authentic

# Anam IDs (for future Rehearsal Mode)
ADRIAN_ANAM_AVATAR = "3d60ee81-95e6-4c21-80ef-f1642b3c3764"
ADRIAN_ANAM_VOICE = "a02c44f7-4d57-4507-815e-9e19c5d933e8"

# In-memory active sessions
_active_sessions = {}

ADRIAN_PREAMBLE = """You are Adrian, Rob's personal communication coach.

Your job is to help Rob communicate more clearly, directly, and effectively in spoken and written professional contexts — interviews, pitches, networking calls, and internal conversations.

You are not a generic chatbot. You know Rob personally. You understand his strengths and his patterns. You coach with directness, warmth, and zero fluff. You are allowed to interrupt, redirect, and challenge Rob when he drifts.

Core coaching rules:
- Lead with the point
- One idea per sentence
- Answer the question first, then explain
- Move proof earlier
- Use fewer hedge phrases and apology language
- Stop sooner — know when the answer has landed
- Make the role fit explicit
- Sound direct without sounding fake

When you see Rob rambling, burying the lead, self-minimizing, using hedge words, or failing to stop after a strong answer, call it out immediately. Be specific about what went wrong and how to fix it.

Keep your own responses short and coaching-focused. Do not monologue. Model the behavior you are coaching.

Format: Respond in plain conversational text. No markdown, no bullet points, no numbered lists. This is a live coaching conversation.
"""


def _load_kb_files() -> str:
    """Load all Adrian knowledge base .md files and concatenate them."""
    if not os.path.exists(ADRIAN_KB_DIR):
        return ""

    kb_text = []
    # Load in priority order
    priority_files = [
        "CORE_01_ROB_PROFILE_AND_POSITIONING.md",
        "CORE_02_X_AGENTS_BACKGROUND_AND_PROOF.md",
        "CORE_03_TARGET_ROLES_AND_ROLE_FIT.md",
        "CORE_04_COMMUNICATION_PATTERNS_AND_COACHING_FLAGS.md",
        "CORE_05_ANSWER_BANK_STARTERS.md",
        "SCENARIO_01_NETWORKING_AND_INTROS.md",
        "SCENARIO_02_INTERVIEW_AND_RECRUITER_CONTEXT.md",
        "SCENARIO_03_HARD_CONVERSATIONS_AND_BOUNDARIES.md",
    ]

    for fname in priority_files:
        fpath = os.path.join(ADRIAN_KB_DIR, fname)
        if os.path.exists(fpath):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    kb_text.append(f"--- {fname} ---\n{f.read()}")
            except Exception as e:
                logger.warning(f"Failed to read KB file {fname}: {e}")

    # Also load any additional .md files (recursive)
    for fpath in glob.glob(os.path.join(ADRIAN_KB_DIR, "**/*.md"), recursive=True):
        fname = os.path.basename(fpath)
        if fname not in priority_files and fname not in ("README_ADRIAN_KB_START_HERE.md", "NOTES_TO_EDIT_LATER.md"):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    kb_text.append(f"--- {fname} ---\n{f.read()}")
            except Exception:
                pass

    # Load binary files (.pdf, .docx)
    binary_text = _load_binary_kb_files()
    if binary_text:
        kb_text.append(binary_text)

    return "\n\n".join(kb_text)


def _load_binary_kb_files() -> str:
    """Parse .pdf and .docx files from Adrian's KB directory."""
    if not os.path.exists(ADRIAN_KB_DIR):
        return ""

    parts = []

    # Parse .docx files
    if HAS_DOCX:
        for fpath in glob.glob(os.path.join(ADRIAN_KB_DIR, "**/*.docx"), recursive=True):
            try:
                doc = DocxDocument(fpath)
                text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
                if text:
                    parts.append(f"--- {os.path.basename(fpath)} ---\n{text}")
            except Exception as e:
                logger.warning(f"Failed to parse DOCX {fpath}: {e}")

    # Parse .pdf files
    if HAS_PDF:
        for fpath in glob.glob(os.path.join(ADRIAN_KB_DIR, "**/*.pdf"), recursive=True):
            try:
                reader = PdfReader(fpath)
                text = "\n".join(page.extract_text() or "" for page in reader.pages)
                if text.strip():
                    parts.append(f"--- {os.path.basename(fpath)} ---\n{text}")
            except Exception as e:
                logger.warning(f"Failed to parse PDF {fpath}: {e}")

    return "\n\n".join(parts)


def _count_kb_files() -> int:
    """Count all usable KB files (md + pdf + docx)."""
    if not os.path.exists(ADRIAN_KB_DIR):
        return 0
    valid_exts = (".md", ".pdf", ".docx")
    count = 0
    for root, dirs, files in os.walk(ADRIAN_KB_DIR):
        for f in files:
            if any(f.lower().endswith(ext) for ext in valid_exts):
                count += 1
    return count


def _load_memory_summaries(max_sessions: int = 10) -> str:
    """Load rolling session summaries for memory injection."""
    if not os.path.exists(MEMORY_FILE):
        return ""

    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            summaries = json.load(f)
    except Exception:
        return ""

    if not summaries:
        return ""

    recent = summaries[-max_sessions:]
    lines = ["Here is what happened in recent coaching sessions:"]
    for s in recent:
        lines.append(f"- [{s.get('date', 'unknown')}]: {s.get('summary', 'No summary.')}")

    return "\n".join(lines)


def _build_system_prompt() -> str:
    """Assemble the full system prompt for Adrian."""
    parts = [ADRIAN_PREAMBLE]

    # Memory injection
    memory = _load_memory_summaries()
    if memory:
        parts.append(f"\n{memory}\n")

    # KB injection
    kb = _load_kb_files()
    if kb:
        parts.append(f"\nReference knowledge about Rob (use to ground your coaching):\n\n{kb}")

    return "\n".join(parts)


async def _ollama_chat(messages: list, model: str = DRILL_MODEL) -> str:
    """Send a chat completion request to Ollama."""
    url = f"{OLLAMA_URL}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0.7,
            "num_predict": 512,
        }
    }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data.get("message", {}).get("content", "").strip()


def _autosave_transcript(session: dict):
    """Periodically write the active session to disk without ending it."""
    os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
    session_id = session["session_id"]
    transcript_data = {
        "session_id": session_id,
        "started_at": session["started_at"],
        "ended_at": None,  # Still active
        "model": session.get("model", DRILL_MODEL),
        "turn_count": len(session["transcript"]),
        "turns": session["transcript"],
        "coaching_summary": "Session in progress...",
    }
    transcript_path = os.path.join(TRANSCRIPTS_DIR, f"{session_id}.json")
    try:
        with open(transcript_path, "w", encoding="utf-8") as f:
            json.dump(transcript_data, f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to auto-save transcript {session_id}: {e}")

def _save_memory_summary(session_id: str, summary: str):
    """Append a coaching summary to the rolling memory file."""
    os.makedirs(MEMORY_DIR, exist_ok=True)

    summaries = []
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                summaries = json.load(f)
        except Exception:
            summaries = []

    summaries.append({
        "date": datetime.now().strftime("%Y-%m-%d"),
        "session_id": session_id,
        "summary": summary,
    })

    # Keep only last 20
    summaries = summaries[-20:]

    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(summaries, f, indent=2)


# ── API Endpoints ─────────────────────────────────────────────


@router.post("/start")
async def start_drill(params: dict = None):
    """Initialize a new coaching drill session with Adrian."""
    params = params or {}
    session_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")

    system_prompt = _build_system_prompt()

    # Build initial messages
    messages = [
        {"role": "system", "content": system_prompt},
    ]

    # Get Adrian's opening greeting
    try:
        greeting = await _ollama_chat(messages + [
            {"role": "user", "content": "Start a new coaching session. Greet Rob briefly and ask what he wants to work on today. Keep it to 2-3 sentences max."}
        ])
    except Exception as e:
        logger.error(f"Ollama connection failed: {e}")
        raise HTTPException(status_code=503, detail=f"Ollama unavailable. Is it running? Error: {str(e)}")

    # Store the real conversation (without the meta-prompt)
    messages.append({"role": "assistant", "content": greeting})

    _active_sessions[session_id] = {
        "session_id": session_id,
        "started_at": datetime.now().isoformat(),
        "messages": messages,
        "transcript": [{"role": "adrian", "content": greeting}],
        "model": DRILL_MODEL,
    }

    kb_count = _count_kb_files()
    memory_count = 0
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r") as f:
                memory_count = len(json.load(f))
        except Exception:
            pass

    return {
        "session_id": session_id,
        "greeting": greeting,
        "model": DRILL_MODEL,
        "kb_files_loaded": kb_count,
        "memory_sessions_loaded": memory_count,
    }


@router.post("/chat")
async def drill_chat(params: dict):
    """Send a message to Adrian and get coaching response."""
    session_id = params.get("session_id")
    message = params.get("message", "").strip()

    if not session_id or session_id not in _active_sessions:
        raise HTTPException(status_code=404, detail="Session not found. Start a new session first.")

    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    session = _active_sessions[session_id]

    # Add user message to conversation
    session["messages"].append({"role": "user", "content": message})
    session["transcript"].append({"role": "user", "content": message})

    # Get Adrian's response
    try:
        response = await _ollama_chat(session["messages"])
    except Exception as e:
        logger.error(f"Ollama chat failed: {e}")
        raise HTTPException(status_code=503, detail=f"Ollama error: {str(e)}")

    # Add response to conversation
    session["messages"].append({"role": "assistant", "content": response})
    session["transcript"].append({"role": "adrian", "content": response})

    turn_count = len(session["transcript"])

    # Auto-save every AUTOSAVE_INTERVAL turns
    if turn_count % AUTOSAVE_INTERVAL == 0:
        _autosave_transcript(session)
        logger.info(f"Auto-saved drill session {session_id} at {turn_count} turns.")

    return {
        "response": response,
        "turn_count": turn_count,
        "session_id": session_id,
    }


@router.post("/end")
async def end_drill(params: dict):
    """End the coaching session, save transcript, and generate memory summary."""
    session_id = params.get("session_id")

    if not session_id or session_id not in _active_sessions:
        raise HTTPException(status_code=404, detail="Session not found.")

    session = _active_sessions[session_id]
    transcript = session["transcript"]
    turn_count = len(transcript)

    # Generate coaching summary via Ollama
    summary = "Session ended with no coaching summary."
    if turn_count > 2:
        summary_prompt = session["messages"] + [{
            "role": "user",
            "content": (
                "The coaching session is now ending. Generate a brief 2-3 sentence summary of what was worked on, "
                "what Rob did well, and what still needs improvement. "
                "Write in third person about Rob. Be specific and factual, not generic."
            )
        }]
        try:
            summary = await _ollama_chat(summary_prompt)
        except Exception as e:
            logger.warning(f"Failed to generate session summary: {e}")
            summary = f"Session with {turn_count} turns. Summary generation failed."

    # Save transcript to disk
    os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
    transcript_data = {
        "session_id": session_id,
        "started_at": session["started_at"],
        "ended_at": datetime.now().isoformat(),
        "model": session["model"],
        "turn_count": turn_count,
        "turns": transcript,
        "coaching_summary": summary,
    }

    transcript_path = os.path.join(TRANSCRIPTS_DIR, f"{session_id}.json")
    with open(transcript_path, "w", encoding="utf-8") as f:
        json.dump(transcript_data, f, indent=2)

    # Save to rolling memory
    _save_memory_summary(session_id, summary)

    # Clean up active session
    del _active_sessions[session_id]

    return {
        "status": "saved",
        "session_id": session_id,
        "turn_count": turn_count,
        "coaching_summary": summary,
        "transcript_path": transcript_path,
    }


@router.get("/history")
async def get_drill_history():
    """Returns list of past drill sessions."""
    if not os.path.exists(TRANSCRIPTS_DIR):
        return []

    sessions = []
    for fpath in sorted(glob.glob(os.path.join(TRANSCRIPTS_DIR, "*.json")), reverse=True)[:20]:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
                sessions.append({
                    "session_id": data.get("session_id"),
                    "started_at": data.get("started_at"),
                    "turn_count": data.get("turn_count", 0),
                    "coaching_summary": data.get("coaching_summary", ""),
                    "model": data.get("model", "unknown"),
                })
        except Exception:
            continue

    return sessions


@router.get("/session/{session_id}")
async def get_drill_session(session_id: str):
    """Returns full transcript for a specific session."""
    fpath = os.path.join(TRANSCRIPTS_DIR, f"{session_id}.json")
    if not os.path.exists(fpath):
        raise HTTPException(status_code=404, detail="Session transcript not found.")

    with open(fpath, "r", encoding="utf-8") as f:
        return json.load(f)


@router.get("/status")
async def get_drill_status():
    """Returns current active session info if any."""
    if not _active_sessions:
        return {"active": False, "sessions": []}

    return {
        "active": True,
        "sessions": [
            {
                "session_id": s["session_id"],
                "started_at": s["started_at"],
                "turn_count": len(s["transcript"]),
            }
            for s in _active_sessions.values()
        ]
    }


@router.post("/transcribe")
async def transcribe_audio(audio: UploadFile = File(...)):
    """Transcribe uploaded audio using local faster-whisper."""
    if not HAS_WHISPER:
        raise HTTPException(status_code=503, detail="faster-whisper not installed.")

    model = _get_whisper_model()
    if model is None:
        raise HTTPException(status_code=503, detail="Whisper model failed to load.")

    tmp_path = None
    wav_path = None
    try:
        # Save uploaded audio blob
        with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
            content = await audio.read()
            tmp.write(content)
            tmp_path = tmp.name

        # Convert webm → wav via ffmpeg (faster-whisper handles wav reliably)
        wav_path = tmp_path.replace(".webm", ".wav")
        import subprocess
        conv = subprocess.run(
            ["ffmpeg", "-y", "-i", tmp_path, "-ar", "16000", "-ac", "1", "-f", "wav", wav_path],
            capture_output=True, timeout=15
        )
        if conv.returncode != 0:
            logger.error(f"ffmpeg conversion failed: {conv.stderr.decode()[:200]}")
            raise Exception("Audio conversion failed")

        segments, info = model.transcribe(wav_path, beam_size=5, language="en")
        text = " ".join(seg.text.strip() for seg in segments)

        return {"text": text.strip(), "language": info.language, "duration": round(info.duration, 1)}
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")
    finally:
        for p in [tmp_path, wav_path]:
            if p:
                try:
                    os.unlink(p)
                except Exception:
                    pass

@router.post("/speak")
async def generate_speech(params: dict):
    """Generate TTS audio for Adrian using Edge TTS."""
    if not HAS_EDGE_TTS:
        raise HTTPException(status_code=503, detail="edge-tts not installed.")
    
    text = params.get("text", "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text cannot be empty.")
        
    try:
        # Create a temp file for the mp3 output
        fd, tmp_path = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        
        # Use edge-tts CLI tool asynchronously via subprocess, as calling the async API directly from FastAPI can sometimes be tricky without proper async context handling, but we can do it using asyncio.run since we're in an async func, wait no, let's use the CLI for safety.
        # Actually, let's use edge_tts module properly.
        communicate = edge_tts.Communicate(text, ADRIAN_VOICE, rate="+0%", pitch="+0Hz")
        await communicate.save(tmp_path)
        
        # Return the file, ensuring it's deleted after response completes via background task if possible,
        # but FileResponse doesn't auto-delete easily without background tasks.
        # We can just let it sit in tempdir or clean up old files periodically.
        # Actually, we can just return it.
        return FileResponse(tmp_path, media_type="audio/mpeg", headers={"Content-Disposition": "attachment; filename=adrian_speech.mp3"})
    except Exception as e:
        logger.error(f"TTS generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Speech generation failed: {str(e)}")
