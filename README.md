# Riva 1.0 AI Assistant

Riva1.o is an AI assistant created by **MD. Rifat Islam Rizvi**. She can respond in both text and voice mode, perform system tasks, and interact naturally with the user in a friendly way.

---

## Features

### 1. Wake-Up & Introduction

- **Voice mode uses a wake phrase:** say **"hi riva"** or **"hey riva"**.
- After you wake her once, **Riva stays awake until you say `go to sleep`** (so you don't need to repeat the wake phrase).
- Example:
  - User: "Hi Riva"
  - Riva: Introduces herself
  - User: "Open YouTube" (no wake phrase needed now)

- Fun and playful replies for casual or identity questions.

### 2. Supported Commands

| Command          | Description                           | Notes / Aliases |
|------------------|---------------------------------------|-----------------|
| `open vs code`   | Opens Visual Studio Code              | Also accepts: `open vscode`, `open this code`, `open base code`, `open best code` |
| `open chrome`    | Opens Google Chrome                   | Also accepts: `open google chrome` |
| `open youtube`   | Opens YouTube in Chrome (new tab)     | Also accepts: `new tab youtube`, `open tab youtube` |
| `open facebook`  | Opens Facebook in Chrome (new tab)    | Also accepts: `new tab facebook`, `open tab facebook`, `open fb` |
| `open gmail`     | Opens Gmail in Chrome (new tab)       | - |
| `open google`    | Opens Google in Chrome (new tab)      | - |
| `open whatsapp`  | Opens WhatsApp Desktop app            | Falls back to WhatsApp Web if the app is not available |
| `open whatsapp web` | Opens WhatsApp Web in Chrome (new tab) | Also accepts: `web whatsapp` |
| `open instagram` | Opens Instagram in Chrome (new tab)   | Also accepts: `open insta` |
| `open folder`    | Opens the current folder in Explorer  | - |
| `battery`        | Speaks the current battery percentage | - |
| `time` / `current time` | Speaks the current local time   | Also accepts: `what time` |
| `open your repo` | Opens this project's GitHub repository | Recommended phrase: `open your repo` |
| `shutdown`       | Shuts down the PC after confirmation  | - |
| `go to sleep` | Stops the assistant (and closes apps) | Also accepts: `sleep`, `exit` |

**Note:** If Chrome is not found on your PC, Riva will try to open the website in your default browser.

### 3. Conversation Style

- Friendly, natural, and casual tone.
- Concise and actionable responses.
- Confirms actions before performing important tasks (like shutdown).

### 4. Error Handling

- Attempts to guess misheard or unclear commands and confirms with the user.
- Example:
  - User: "open base code"
  - Riva: "Did you mean 'open VS Code'?"

### 5. Optional Fun Responses

- For casual greetings or identity questions, Riva can respond with playful jokes or witty replies.

---

## How to Use

1. Run the assistant script.
2. In **voice mode**, wake Riva once by saying: **"hi riva"** or **"hey riva"**.
3. Then speak commands normally until you say **`go to sleep`**.
4. In **text mode**, you can type commands directly.
5. Riva responds in text or voice and performs supported actions.

---

## Voice Accuracy Tips (Whisper)

- Riva trims silence and uses tuned Whisper decoding settings to reduce ভুলভাল transcription.
- If you speak Bangla/English mixed and detection gets confused, you can force language:
  - `RIVA_STT_LANG=en` (English)
  - `RIVA_STT_LANG=bn` (Bangla)

## Optional Settings

- `RIVA_AWAKE_WINDOW_SEC`
  - How long (seconds) Riva stays awake after the wake phrase.
  - Default: effectively "until exit/sleep".

---

## Developer Notes

- Built to work with **text-to-speech** and **speech recognition**.
- Commands can be updated or extended as needed.
- Misheard commands are handled intelligently to reduce errors.
