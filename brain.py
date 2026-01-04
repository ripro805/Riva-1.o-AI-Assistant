import os
import random
import json
import psutil
import shutil
import subprocess

from speech import speak
from moods import get_mood
from jokes import confused, greetings, random_reply

MEMORY_FILE = "memory.json"
WAKE_WORD = "riva"

ASSISTANT_NAME = "Riva"
CREATOR_NAME = "MD. Rifat Islam Rizvi"


_SITE_TARGETS: list[tuple[str, str, tuple[str, ...]]] = [
    ("Facebook", "https://www.facebook.com/", ("facebook", "face book", "fb")),
    ("YouTube", "https://www.youtube.com/", ("youtube", "you tube")),
    ("Gmail", "https://mail.google.com/", ("gmail", "g mail")),
    ("Google", "https://www.google.com/", ("google",)),
    # Keep WhatsApp Web only for explicit "web" requests.
    ("WhatsApp Web", "https://web.whatsapp.com/", ("whatsapp web", "web whatsapp", "whats web")),
    ("Instagram", "https://www.instagram.com/", ("instagram", "insta")),
]


def _open_whatsapp_desktop() -> bool:
    """Open WhatsApp Desktop app on Windows.

    Returns True if we successfully triggered a launch attempt.

    Notes:
    - The `whatsapp:` protocol is supported when WhatsApp Desktop is installed.
    - The AppUserModelId used below is a common Microsoft Store package id; it may vary.
    """
    # 1) Try protocol handler (best effort).
    try:
        subprocess.Popen(
            ["cmd", "/c", "start", "", "whatsapp:"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        pass

    # 2) Try common Microsoft Store AppUserModelId.
    try:
        subprocess.Popen(
            [
                "explorer.exe",
                "shell:AppsFolder\\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def _find_chrome_exe() -> str | None:
    """Best-effort lookup for Google Chrome on Windows.

    Returns a path to chrome.exe if found, otherwise None.
    """
    for name in ("chrome", "chrome.exe"):
        p = shutil.which(name)
        if p:
            return p

    program_files = os.environ.get("PROGRAMFILES", r"C:\\Program Files")
    program_files_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\\Program Files (x86)")
    local_app_data = os.environ.get("LOCALAPPDATA", "")

    candidates = [
        os.path.join(program_files, "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(program_files_x86, "Google", "Chrome", "Application", "chrome.exe"),
    ]
    if local_app_data:
        candidates.append(os.path.join(local_app_data, "Google", "Chrome", "Application", "chrome.exe"))

    for c in candidates:
        if os.path.exists(c):
            return c

    return None


def _open_chrome(url: str | None = None) -> bool:
    """Open Google Chrome (optionally a URL).

    Returns True if Chrome was launched, False if we had to fall back.
    """
    chrome = _find_chrome_exe()
    if chrome:
        args = [chrome]
        if url:
            # Passing a URL typically opens a new tab if Chrome is already running.
            args.extend(["--new-tab", url])
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True

    # Fallback: open URL in default browser if present.
    if url:
        try:
            os.startfile(url)  # type: ignore[attr-defined]
        except Exception:
            return False
        return False

    return False


def _match_site_target(command: str) -> tuple[str, str] | None:
    t = (command or "").lower()
    for display_name, url, patterns in _SITE_TARGETS:
        if any(p in t for p in patterns):
            return display_name, url
    return None


def _intro_text() -> str:
    return f"Hi! I'm {ASSISTANT_NAME}, your AI assistant created by {CREATOR_NAME}. How can I help you today?"


def _capabilities_lines() -> list[str]:
    return [
        "I can: open VS Code, open Chrome, open websites (YouTube/Facebook), open the current folder, check battery, shut down your PC, and exit.",
        "Try: open vs code; open chrome; open youtube; open folder; battery; shutdown; exit."
    ]


def _is_yes(text: str) -> bool:
    t = (text or "").lower()
    return any(w in t for w in ("yes", "yeah", "yep", "ok", "okay", "confirm", "do it", "sure"))


def _is_no(text: str) -> bool:
    t = (text or "").lower()
    return any(w in t for w in ("no", "nope", "cancel", "stop", "don't", "do not"))

def load_memory():
    with open(MEMORY_FILE, "r") as f:
        data = json.load(f)
        # Backward-compatible defaults
        data.setdefault("pending_action", None)
        data.setdefault("pending_url", None)
        return data

def save_memory(data):
    with open(MEMORY_FILE, "w") as f:
        json.dump(data, f, indent=2)

def process(command, require_wake_word: bool = True):
    # Normalize
    command = (command or "").lower().strip()

    memory = load_memory()

    # Handle confirmations first (e.g., shutdown confirmation)
    pending = memory.get("pending_action")
    if pending:
        if _is_yes(command):
            if pending == "shutdown":
                speak("Confirmed. Shutting down now.")
                memory["pending_action"] = None
                memory["pending_url"] = None
                save_memory(memory)
                os.system("shutdown /s /t 5")
                return
            elif pending == "open_vscode":
                speak("Okay. Opening VS Code.")
                memory["pending_action"] = None
                memory["pending_url"] = None
                save_memory(memory)
                os.system("code")
                return
            elif pending == "open_folder":
                speak("Okay. Opening the current folder.")
                memory["pending_action"] = None
                memory["pending_url"] = None
                save_memory(memory)
                os.system("explorer .")
                return
            elif pending == "open_chrome":
                speak("Okay. Opening Chrome.")
                url = memory.get("pending_url")
                memory["pending_action"] = None
                memory["pending_url"] = None
                save_memory(memory)
                launched = _open_chrome(url=url)
                if not launched and not url:
                    speak("I couldn't find Chrome on this PC.")
                elif not launched and url:
                    speak("I couldn't find Chrome, so I opened it in your default browser.")
                return

            # Unknown pending action
            speak("Confirmed.")
            memory["pending_action"] = None
            memory["pending_url"] = None
            save_memory(memory)
            return

        if _is_no(command):
            speak("Okay, cancelled.")
            memory["pending_action"] = None
            memory["pending_url"] = None
            save_memory(memory)
            return

        speak("Please say yes to confirm, or say cancel.")
        return

    # Wake-word gate (optional). To make voice use nicer, we still allow greetings
    # without the wake word.
    if require_wake_word and WAKE_WORD not in command:
        if "hello" in command or "hi" in command:
            speak(random_reply(greetings))
        return

    # If wake word exists, remove it (even when require_wake_word=False)
    woke = False
    if WAKE_WORD in command:
        command = command.replace(WAKE_WORD, "").strip()
        woke = True

    mood = get_mood()
    memory["last_command"] = command
    save_memory(memory)

    # If user just woke you up (e.g., "hey riva") with no extra command
    if woke and not command:
        speak(_intro_text())
        for line in _capabilities_lines():
            speak(line)
        return


    if "hello" in command or "hi" in command:
        speak(random_reply(greetings))

    elif (
        "help" in command
        or "what can you do" in command
        or "commands" in command
        or "features" in command
        or "capabilities" in command
    ):
        speak("Here is what I can do right now.")
        speak("Open VS Code: say open vs code.")
        speak("Open Chrome: say open chrome.")
        speak("Open a site in Chrome: say open youtube or open facebook.")
        speak("Open WhatsApp app: say open whatsapp.")
        speak("Open WhatsApp Web in Chrome: say open whatsapp web.")
        speak("Open current folder: say open folder.")
        speak("Check battery: say battery.")
        speak("Shutdown PC: say shutdown (I will ask you to confirm).")
        speak("Exit: say exit or sleep.")

        # Mention wake word behavior (if enabled).
        if require_wake_word:
            speak(f"If wake word is enabled, say {WAKE_WORD} first.")
        else:
            speak("Wake word is optional.")

    elif (
        "who are you" in command
        or "what are you" in command
        or "introduce yourself" in command
        or "your name" in command
    ):
        speak(_intro_text())

    elif "who am i" in command or "do you know me" in command:
        whoami = [
            "You are my favorite human. Probably.",
            "You are the boss of this PC.",
            "You are a legend in progress.",
            "You are the one who keeps giving me tasks. And I respect that.",
            "You are the reason my code exists.",
        ]
        speak(random.choice(whoami))

    # Fuzzy matching for 'open vs code' to handle mis-transcriptions
    elif (
        "open vscode" in command
        or "open vs code" in command
        or "open this code" in command  # common mis-transcription
        or "open base code" in command  # another possible mis-transcription
        or "open best code" in command
    ):
        speak("Opening VS Code. Programmer mode on 🤓")
        os.system("code")

    # If it's close to the intent, confirm instead of doing the wrong thing.
    elif "open" in command and "code" in command:
        speak("Did you mean 'open VS Code'?")
        memory["pending_action"] = "open_vscode"
        memory["pending_url"] = None
        save_memory(memory)

    # Chrome / website shortcuts
    elif (
        "open chrome" in command
        or "open google chrome" in command
        or command.strip() == "chrome"
    ):
        speak("Opening Chrome.")
        launched = _open_chrome()
        if not launched:
            speak("I couldn't find Chrome on this PC.")

    # WhatsApp Desktop (prefer app over web)
    elif (
        ("open" in command or "start" in command)
        and ("whatsapp" in command or "what's app" in command or "what app" in command)
        and "web" not in command
    ):
        speak("Opening WhatsApp app.")
        ok = _open_whatsapp_desktop()
        if not ok:
            speak("I couldn't open the WhatsApp app. Opening WhatsApp Web instead.")
            _open_chrome(url="https://web.whatsapp.com/")

    elif (
        ("open" in command or "new tab" in command or "open tab" in command)
        and _match_site_target(command) is not None
    ):
        site = _match_site_target(command)
        assert site is not None
        site_name, url = site
        speak(f"Opening {site_name}.")
        launched = _open_chrome(url=url)
        if not launched:
            speak("I couldn't find Chrome, so I opened it in your default browser.")

    elif "open" in command and ("chrome" in command or "crome" in command or "chrom" in command):
        speak("Did you mean 'open chrome'?")
        memory["pending_action"] = "open_chrome"
        memory["pending_url"] = None
        save_memory(memory)

    elif "open folder" in command:
        speak("Opening current folder.")
        os.system("explorer .")

    elif "open" in command and "folder" in command:
        speak("Did you mean 'open folder'?")
        memory["pending_action"] = "open_folder"
        memory["pending_url"] = None
        save_memory(memory)

    elif "battery" in command:
        battery = psutil.sensors_battery()
        speak(f"Battery is {battery.percent} percent.")

    elif "shutdown" in command:
        if mood == "happy":
            speak("You did great today.")
        elif mood == "sleepy":
            speak("Finally… good night.")

        speak("Do you want me to shut down the PC? Please say yes to confirm, or say cancel.")
        memory["pending_action"] = "shutdown"
        memory["pending_url"] = None
        save_memory(memory)

    elif "exit" in command or "sleep" in command:
        speak("Okay, I am going offline now.")
        exit()

    else:
        speak(random_reply(confused))
