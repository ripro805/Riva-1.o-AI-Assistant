# Riva 1.0 AI Assistant

Riva1.o is an AI assistant created by **MD. Rifat Islam Rizvi**. She can respond in both text and voice mode, perform system tasks, and interact naturally with the user in a friendly way.

---

## Features

### 1. Wake-Up & Introduction

- When woken up, Riva greets the user and introduces herself.
- Example:
  - User: "Hey Riva!"
  - Riva: "Hello! I'm Riva, your AI assistant created by MD. Rifat Islam Rizvi. I can open VS Code, open Chrome (YouTube/Facebook), check battery, open folders, shut down your PC, and more. What would you like to do first?"

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
| `shutdown`       | Shuts down the PC after confirmation  | - |
| `exit` / `sleep` | Stops the assistant                   | - |

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
2. Wake Riva with your chosen wake word.
3. Speak or type commands.
4. Riva responds in text or voice and performs supported actions.

---

## Developer Notes

- Built to work with **text-to-speech** and **speech recognition**.
- Commands can be updated or extended as needed.
- Misheard commands are handled intelligently to reduce errors.
