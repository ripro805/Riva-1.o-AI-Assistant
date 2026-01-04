import sys

from speech import listen, speak
from brain import process


def run_voice_mode():
    speak("Voice mode is running. Say 'hi riva' or 'hey riva' to wake me up.")
    while True:
        command = listen()
        if command:
            # Voice mode: wake phrase is required, and once awake it stays awake until exit.
            process(command, require_wake_word=True)


def run_text_mode():
    speak("Hi! I'm Riva, your AI assistant created by MD. Rifat Islam Rizvi. How can I help you today?")
    print("Tip: type 'help' to see what I can do.")
    while True:
        try:
            command = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            speak("Okay, I am going offline now.")
            return

        if not command:
            continue

        # In text mode, wake word is optional.
        process(command.lower(), require_wake_word=False)


if __name__ == "__main__":
    args = set(sys.argv[1:])
    voice_mode = "--voice" in args or "-v" in args
    text_mode = "--text" in args or "-t" in args

    if text_mode:
        print("[mode] TEXT — type commands at 'You>'")
        run_text_mode()
    else:
        # Default is voice mode, and you can also pass --voice explicitly.
        if voice_mode:
            print("[mode] VOICE")
        else:
            print("[mode] VOICE — tip: python main.py --text  (text mode)")
        run_voice_mode()
