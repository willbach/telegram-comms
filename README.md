# Telegram Claude Bot

A Telegram bot that forwards messages to Claude Code SDK and returns responses. Supports text and voice messages with conversation persistence.

## Features

- **Claude Code Integration** - Messages are processed by Claude Code SDK with full tool access
- **Voice Messages** - Transcribed locally using Whisper, then sent to Claude
- **Named Sessions** - Create and switch between multiple conversation contexts
- **Session Persistence** - Sessions survive bot restarts
- **Admin Only** - Only chat administrators can interact with the bot
- **Mention Filtering** - Ignores messages that tag other users

## Commands

- `/new_session <name> <prompt>` - Create a new named session
- `/switch <name>` - Switch to a different session
- `/sessions` - List all sessions
- `/reset` - Clear current session

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Create `.env` file:
   ```
   BOT_TOKEN=your_telegram_bot_token
   CHAT_ID=your_chat_id
   ```

3. Run the bot:
   ```bash
   python main.py
   ```

## Requirements

- Python 3.10+
- ffmpeg (for voice message processing)
- Claude Code CLI installed and authenticated

## Configuration

Edit `.claude/settings.local.json` to configure permissions for the Claude agent.
