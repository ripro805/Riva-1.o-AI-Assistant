import pyttsx3
import sounddevice as sd
import numpy as np
import whisper
import sys
import subprocess
import os
import unicodedata
import re
import threading
import time
from typing import Optional


_ALLOWED_PUNCTUATION = set(".,?!:;।-—()[]{}'\"/\\")


_SPEAKING = threading.Event()
_AUDIO_IO_LOCK = threading.Lock()
_LAST_SPEAK_END_MONO = 0.0

# Small delay to avoid the mic capturing the tail end of the speaker output.
_POST_SPEAK_COOLDOWN_SEC = 0.45


def is_speaking() -> bool:
    """True while the assistant is actively speaking via TTS."""
    return _SPEAKING.is_set()


def _wait_for_safe_listen_window():
    """Block until it's safe to record audio (not speaking + cooldown passed)."""
    # Wait while speaking
    while is_speaking():
        time.sleep(0.05)

    # And wait a tiny bit after speaking ends to reduce echo pickup.
    while True:
        since = time.monotonic() - _LAST_SPEAK_END_MONO
        if since >= _POST_SPEAK_COOLDOWN_SEC:
            return
        time.sleep(0.05)


def _sanitize_for_speech(text: str) -> str:
    """Remove characters that TTS engines tend to read awkwardly.

    Keeps:
    - Letters/numbers across scripts (incl. Bangla)
    - Combining marks
    - Whitespace
    - A small set of basic punctuation

    Strips:
    - Emojis and most symbols (Unicode categories starting with 'S')
    - Control/format characters
    """
    if text is None:
        return ""

    cleaned_chars: list[str] = []
    for ch in str(text):
        if ch.isspace():
            cleaned_chars.append(" ")
            continue

        if ch in _ALLOWED_PUNCTUATION:
            cleaned_chars.append(ch)
            continue

        cat = unicodedata.category(ch)

        # Letters (L*), Marks (M*), Numbers (N*) are generally safe.
        if cat and cat[0] in ("L", "M", "N"):
            cleaned_chars.append(ch)
            continue

        # Drop control/format/private-use/surrogates and symbols (incl. emoji).
        # (We intentionally do *not* keep currency/math/other symbols.)
        if cat and (cat[0] in ("C", "S")):
            continue

        # For any remaining punctuation that isn't in our allowlist, drop it.
        # (Example: fancy quotes, bullets, etc.)
        # If you want to keep more punctuation later, add it to _ALLOWED_PUNCTUATION.
        continue

    cleaned = "".join(cleaned_chars)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned

def _init_tts_engine():
    """Initialize TTS engine with sensible defaults (Windows-friendly)."""
    try:
        # On Windows, using SAPI5 explicitly is usually the most reliable.
        if sys.platform.startswith("win"):
            return pyttsx3.init(driverName="sapi5")
        return pyttsx3.init()
    except Exception:
        # Fallback to default init if a driver isn't available.
        return pyttsx3.init()


engine = _init_tts_engine()
engine.setProperty("rate", 170)
engine.setProperty("volume", 1.0)


def _pick_preferred_windows_voice_name() -> Optional[str]:
    """Pick a likely female System.Speech voice if installed.

    Returns a voice name (e.g., "Microsoft Zira Desktop") or None.
    """
    if not sys.platform.startswith("win"):
        return None

    # Allow user override.
    env_name = (os.environ.get("RIVA_VOICE") or "").strip()
    if env_name:
        return env_name

    preferred = [
        # Common Windows female voices (names vary by Windows version/language pack)
        "Microsoft Zira Desktop",
        "Microsoft Hazel Desktop",
        "Microsoft Susan",
        "Microsoft Aria",
        "Microsoft Jenny",
        "Microsoft Sonia",
    ]

    try:
        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Add-Type -AssemblyName System.Speech; "
                "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                "$s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        voices = [v.strip() for v in out.splitlines() if v.strip()]
        if not voices:
            return None

        # First try exact preferred names.
        for p in preferred:
            if p in voices:
                return p

        # Then try fuzzy match (contains preferred token).
        lowered = {v.lower(): v for v in voices}
        for token in ("zira", "hazel", "aria", "jenny", "susan", "sonia"):
            for k, original in lowered.items():
                if token in k:
                    return original

        return None
    except Exception:
        return None


_WINDOWS_VOICE_NAME: Optional[str] = _pick_preferred_windows_voice_name()

# Pick a default voice if available (prevents "silent" engine on some setups)
try:
    voices = engine.getProperty("voices")
    if voices:
        # Try to align pyttsx3 voice with our Windows preference.
        chosen = None
        if _WINDOWS_VOICE_NAME:
            pref = _WINDOWS_VOICE_NAME.lower()
            for v in voices:
                name = (getattr(v, "name", "") or "").lower()
                vid = (getattr(v, "id", "") or "").lower()
                if pref in name or pref in vid:
                    chosen = v
                    break

        # Otherwise, try to pick a "female" voice if the engine exposes it.
        if chosen is None:
            for v in voices:
                meta = (getattr(v, "name", "") or "") + " " + (getattr(v, "id", "") or "")
                if "zira" in meta.lower() or "female" in meta.lower():
                    chosen = v
                    break

        engine.setProperty("voice", (chosen or voices[0]).id)
except Exception:
    pass

# Cache Whisper model (loading it every time is very slow)
_WHISPER_MODEL = None


def _get_whisper_model():
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        _WHISPER_MODEL = whisper.load_model("base")
    return _WHISPER_MODEL

def speak(text):
    cleaned = _sanitize_for_speech(str(text))
    print("AI:", cleaned)

    if not cleaned:
        return

    # Ensure we never talk while the mic is actively recording.
    with _AUDIO_IO_LOCK:
        _SPEAKING.set()

        # On Windows, System.Speech (SAPI) is often more reliable than pyttsx3 output.
        # We try it first; if it fails, we fall back to pyttsx3.
        try:
            if sys.platform.startswith("win"):
                try:
                    ps_text = cleaned.replace("'", "''")
                    ps_voice = (_WINDOWS_VOICE_NAME or "").replace("'", "''")
                    # If a preferred voice is known, select it (ignore failures).
                    select_voice = ""
                    if ps_voice:
                        select_voice = f"try {{ $s.SelectVoice('{ps_voice}'); }} catch {{ }}; "
                    subprocess.run(
                        [
                            "powershell",
                            "-NoProfile",
                            "-Command",
                            "Add-Type -AssemblyName System.Speech; "
                            "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                            "$s.Volume=100; $s.Rate=0; "
                            + select_voice +
                            f"$s.Speak('{ps_text}');",
                        ],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    return
                except Exception as e:
                    print(f"[tts windows fallback error] {e}")

            try:
                engine.say(cleaned)
                engine.runAndWait()
            except Exception as e:
                print(f"[tts error] {e}")
        finally:
            global _LAST_SPEAK_END_MONO
            _LAST_SPEAK_END_MONO = time.monotonic()
            _SPEAKING.clear()

def listen(verbose: bool = True):
    _wait_for_safe_listen_window()
    if verbose:
        print("Listening...")
    fs = 16000  # Sample rate
    duration = 5  # seconds
    if verbose:
        print("Say something...")

    # Ensure we never record while TTS is speaking.
    with _AUDIO_IO_LOCK:
        _wait_for_safe_listen_window()
        audio = sd.rec(int(duration * fs), samplerate=fs, channels=1, dtype='int16')
        sd.wait()

    audio = np.squeeze(audio)
    # Convert to float32 for whisper
    audio = audio.astype(np.float32) / 32768.0
    model = _get_whisper_model()
    result = model.transcribe(audio, fp16=False, language='en')
    command = result.get('text', '').strip()
    if command:
        if verbose:
            print("You:", command)
        return command.lower()
    return ""
