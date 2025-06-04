# Telegram Chat Bot

A multifunctional Telegram bot built with `python-telegram-bot`. It supports AI chat responses, persona selection,
persona approval by admins, Blackjack gaming, and more.

---

## Features

- **AI Group Chat Assistant**: Responds in group chats when replied to or mentioned.
- **Persona Selection**: Users can choose a bot personality from a list.
- **Persona Submission & Approval**: Users submit custom personas, which admins can approve or reject.
- **Blackjack Game**: Simple group card game with betting support.
- **Logging**: Logs all interactions and errors.
- **Error Notifications**: Critical errors are reported to the admin.
- **Shutdown Command**: Admins can safely stop the bot from Telegram.

---

## Configuration

Create a dictionary named `bot` in `/app/config/config.py` with the required fields:

### Required Keys

- `log`: path to the log file (e.g., `"bot.log"`)
- `bot_token`: Telegram bot token
- `persona`: list of personas (e.g., `[{"t": "Friendly"}, {"t": "Grumpy"}]`)
- `key`: Gemini or AI model API key
- `admin`: admin user ID
- `bot_nickname`: the bot's @nickname
- `groups`: list of allowed group IDs
- `model`: AI model name to use

### Example

```python
bot = {
    "log": "bot.log",
    "bot_token": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
    "persona": [{"t": "Friendly AI"}, {"t": "Grumpy AI"}],
    "key": "your-api-key",
    "admin": 123456789,
    "bot_nickname": "@YourBotName",
    "groups": [-1009876543210],
    "model": ["gemini-1.5-pro"]
}
```

## Bot Commands

| Command        | Description                                       |
|----------------|---------------------------------------------------|
| `/select`      | Choose a predefined persona from the list         |
| `/persona`     | Submit a custom persona (admin approval needed)   |
| `/cancel`      | Cancel the current persona selection conversation |
| `/blackjack`   | Start a Blackjack game                            |
| `/add_balance` | Add balance to a user (admin only)                |
| `/stop_bot`    | Shut down the bot (admin only)                    |

---

## Blackjack Game Flow

1. Type `/blackjack` to start a game.
2. Players join via inline button.
3. After 30 seconds, the game begins.
4. Players bet using inline buttons.
5. Players choose to **Hit** or **Stand**.
6. Results and updated balances are shown.

---

## Persona Selection & Submission

### Select a Persona

- **Command**: `/select`
- A button list appears with available personas.
- Selection is updated immediately.

## Error Handling

- Critical errors are logged and sent to the admin via Telegram.
- Users receive a simple: “Something went wrong” message.
- Admin gets full traceback information for debugging.

---

## ⚙️ Setup

### Requirements

- Python 3.11+
- AI API Key for Google Gemini

---

## Install

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Up Your Configuration

### 3. Run the Bot

```bash
python3 -m app.bot
```

---

## License

This project is licensed under the MIT License - see the [LICENSE](./LICENSE) file for details.


