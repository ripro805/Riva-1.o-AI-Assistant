import os
import random
import json
import psutil

from speech import speak
from moods import get_mood
from jokes import confused, greetings, random_reply

MEMORY_FILE = "memory.json"
WAKE_WORD = "riva"

ASSISTANT_NAME = "Riva"
CREATOR_NAME = "MD. Rifat Islam Rizvi"


def _intro_text() -> str:
    return f"Hi! I'm {ASSISTANT_NAME}, your AI assistant created by {CREATOR_NAME}. How can I help you today?"


def _capabilities_lines() -> list[str]:
    return [
        "I can: open VS Code, open the current folder, check battery, shut down your PC, and exit.",
        "Try: open vs code; open folder; battery; shutdown; exit."
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
                save_memory(memory)
                os.system("shutdown /s /t 5")
                return
            elif pending == "open_vscode":
                speak("Okay. Opening VS Code.")
                memory["pending_action"] = None
                save_memory(memory)
                os.system("code")
                return
            elif pending == "open_folder":
                speak("Okay. Opening the current folder.")
                memory["pending_action"] = None
                save_memory(memory)
                os.system("explorer .")
                return

            # Unknown pending action
            speak("Confirmed.")
            memory["pending_action"] = None
            save_memory(memory)
            return

        if _is_no(command):
            speak("Okay, cancelled.")
            memory["pending_action"] = None
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
        save_memory(memory)

    elif "open folder" in command:
        speak("Opening current folder.")
        os.system("explorer .")

    elif "open" in command and "folder" in command:
        speak("Did you mean 'open folder'?")
        memory["pending_action"] = "open_folder"
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
        save_memory(memory)

    elif "exit" in command or "sleep" in command:
        speak("Okay, I am going offline now.")
        exit()

    else:
        speak(random_reply(confused))
