"""Telegram bot that forwards messages from @will_bach to Claude."""

import asyncio
import json
import os
import tempfile
import whisper
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
from claude_client import ClaudeClient, ClaudeConfig

load_dotenv()

ALLOWED_USERNAME = "will_bach"
ALLOWED_CHAT_ID = int(os.getenv("CHAT_ID", "0"))
SESSIONS_FILE = Path(__file__).parent / "sessions.json"

# Configure Claude with auto-approve for all tool uses
config = ClaudeConfig(bypass_permissions=True)
claude = ClaudeClient(config)

# Track sessions - supports both default chat sessions and named sessions
# Key format: chat_id for default, or "chat_id:session_name" for named sessions
sessions: dict[str, str] = {}

# Track which named session is active per chat (None = use default)
active_named_session: dict[int, str] = {}


def load_sessions():
    """Load sessions from disk."""
    global sessions, active_named_session
    if SESSIONS_FILE.exists():
        try:
            data = json.loads(SESSIONS_FILE.read_text())
            sessions = data.get("sessions", {})
            # Convert string keys back to int for active_named_session
            active_named_session = {
                int(k): v for k, v in data.get("active_named_session", {}).items()
            }
            print(f"Loaded {len(sessions)} sessions from disk")
        except Exception as e:
            print(f"Error loading sessions: {e}")
            sessions = {}
            active_named_session = {}


def save_sessions():
    """Save sessions to disk."""
    try:
        data = {
            "sessions": sessions,
            "active_named_session": {str(k): v for k, v in active_named_session.items()}
        }
        SESSIONS_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        print(f"Error saving sessions: {e}")


# Load existing sessions on startup
load_sessions()

# Load Whisper model (using "base" for balance of speed/accuracy)
print("Loading Whisper model...")
whisper_model = whisper.load_model("base")
print("Whisper model loaded.")


async def check_allowed(update: Update) -> bool:
    """Check if message is from allowed user in allowed chat."""
    if not update.message or not update.message.from_user:
        return False

    chat_id = update.message.chat_id
    username = update.message.from_user.username or "no_username"

    if chat_id != ALLOWED_CHAT_ID:
        print(f"[DEBUG] Ignoring - wrong chat {chat_id} (expected {ALLOWED_CHAT_ID})")
        return False

    if username != ALLOWED_USERNAME:
        print(f"[DEBUG] Ignoring - wrong user @{username} (expected @{ALLOWED_USERNAME})")
        return False

    return True


def get_user_mention(update: Update) -> str:
    """Get a mention string for the user."""
    user = update.message.from_user
    if user.username:
        return f"@{user.username}"
    else:
        # Use HTML mention if no username
        return f"[{user.first_name}](tg://user?id={user.id})"


def get_session_key(chat_id: int) -> str:
    """Get the session key for the current chat (default or named)."""
    named = active_named_session.get(chat_id)
    if named:
        return f"{chat_id}:{named}"
    return str(chat_id)


async def send_to_claude(chat_id: int, text: str, session_name: str = None) -> str:
    """Send text to Claude with conversation continuity."""
    # Determine session key
    if session_name:
        session_key = f"{chat_id}:{session_name}"
    else:
        session_key = get_session_key(chat_id)

    # Get existing session (if any)
    session_id = sessions.get(session_key)

    if session_id:
        print(f"Resuming session '{session_key}' ({session_id[:8]}...)")
    else:
        print(f"Starting new session '{session_key}'")

    # Send to Claude
    response, new_session_id = await claude.send(text, resume_session=session_id)

    # Store session ID for future messages
    if new_session_id:
        sessions[session_key] = new_session_id
        save_sessions()  # Persist to disk
        print(f"Session ID: {new_session_id[:8]}...")

    return response


async def handle_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /reset command - clear current session."""
    if not await check_allowed(update):
        return

    chat_id = update.message.chat_id
    session_key = get_session_key(chat_id)
    user_mention = get_user_mention(update)

    if session_key in sessions:
        del sessions[session_key]
        # Also clear active named session if any
        if chat_id in active_named_session:
            del active_named_session[chat_id]
        save_sessions()  # Persist to disk
        await update.message.reply_text(f"{user_mention} 🔄 Session cleared. Starting fresh!")
        print(f"Reset session for chat {chat_id}")
    else:
        await update.message.reply_text(f"{user_mention} No active session to reset.")


async def handle_new_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /new_session <name> <prompt> - create a new named session."""
    if not await check_allowed(update):
        return

    chat_id = update.message.chat_id
    args = context.args
    user_mention = get_user_mention(update)

    if not args or len(args) < 2:
        await update.message.reply_text(
            f"{user_mention} Usage: /new_session <name> <prompt>\n"
            "Example: /new_session debug Help me debug this issue"
        )
        return

    session_name = args[0]
    prompt = " ".join(args[1:])

    print(f"Creating new session '{session_name}' with prompt: {prompt[:50]}...")

    # Set this as the active named session
    active_named_session[chat_id] = session_name
    save_sessions()

    # Acknowledge
    ack_message = await update.message.reply_text(
        f"{user_mention} 🆕 Starting session '{session_name}'...\n🤔 Thinking..."
    )

    try:
        response = await send_to_claude(chat_id, prompt, session_name=session_name)
        print(f"Claude response: {response[:100]}...")
        await ack_message.edit_text(f"{user_mention} 📌 Session: {session_name}\n\n{response}")
    except Exception as e:
        print(f"Error: {e}")
        await ack_message.edit_text(f"{user_mention} Error: {e}")


async def handle_switch_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /switch <name> - switch to a named session."""
    if not await check_allowed(update):
        return

    chat_id = update.message.chat_id
    args = context.args
    user_mention = get_user_mention(update)

    if not args:
        # List available sessions
        chat_sessions = [k for k in sessions.keys() if k.startswith(f"{chat_id}:")]
        if chat_sessions:
            names = [k.split(":", 1)[1] for k in chat_sessions]
            current = active_named_session.get(chat_id, "default")
            await update.message.reply_text(
                f"{user_mention} 📋 Available sessions: {', '.join(names)}\n"
                f"Current: {current}\n\n"
                f"Use /switch <name> to switch, or /switch default for unnamed session"
            )
        else:
            await update.message.reply_text(f"{user_mention} No named sessions. Use /new_session to create one.")
        return

    session_name = args[0]

    if session_name == "default":
        if chat_id in active_named_session:
            del active_named_session[chat_id]
            save_sessions()
        await update.message.reply_text(f"{user_mention} 🔀 Switched to default session")
    else:
        session_key = f"{chat_id}:{session_name}"
        if session_key in sessions:
            active_named_session[chat_id] = session_name
            save_sessions()
            await update.message.reply_text(f"{user_mention} 🔀 Switched to session '{session_name}'")
        else:
            await update.message.reply_text(
                f"{user_mention} Session '{session_name}' not found. Use /new_session to create it."
            )


async def handle_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /sessions - list all sessions."""
    if not await check_allowed(update):
        return

    chat_id = update.message.chat_id
    user_mention = get_user_mention(update)

    # Find all sessions for this chat
    default_session = sessions.get(str(chat_id))
    named_sessions = {
        k.split(":", 1)[1]: v
        for k, v in sessions.items()
        if k.startswith(f"{chat_id}:") and ":" in k
    }

    current = active_named_session.get(chat_id, "default")

    lines = [f"{user_mention} 📋 **Sessions:**\n"]
    if default_session:
        marker = "→ " if current == "default" else "  "
        lines.append(f"{marker}default ({default_session[:8]}...)")
    else:
        lines.append("  default (no session)")

    for name, sid in named_sessions.items():
        marker = "→ " if current == name else "  "
        lines.append(f"{marker}{name} ({sid[:8]}...)")

    if not named_sessions and not default_session:
        lines.append("\nNo active sessions. Send a message to start one.")

    await update.message.reply_text("\n".join(lines))


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming text messages."""
    if not await check_allowed(update):
        return

    text = update.message.text
    if not text:
        return

    chat_id = update.message.chat_id
    session_name = active_named_session.get(chat_id)
    user_mention = get_user_mention(update)

    prefix = f"[{session_name}] " if session_name else ""
    print(f"{prefix}Processing text message: {text[:50]}...")

    # Immediately acknowledge the message
    ack_message = await update.message.reply_text(f"{user_mention} 🤔 Thinking...")

    try:
        response = await send_to_claude(chat_id, text)
        print(f"Claude response: {response[:100]}...")

        # Add session indicator if using named session
        session_prefix = f"📌 {session_name}\n\n" if session_name else ""
        await ack_message.edit_text(f"{user_mention} {session_prefix}{response}")
    except Exception as e:
        print(f"Error getting Claude response: {e}")
        await ack_message.edit_text(f"{user_mention} Error: {e}")


async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming voice messages."""
    if not await check_allowed(update):
        return

    voice = update.message.voice
    if not voice:
        return

    chat_id = update.message.chat_id
    session_name = active_named_session.get(chat_id)
    user_mention = get_user_mention(update)
    print(f"Processing voice message (duration: {voice.duration}s)...")

    # Acknowledge receipt
    ack_message = await update.message.reply_text(f"{user_mention} 🎤 Transcribing voice message...")

    try:
        # Download voice file
        voice_file = await context.bot.get_file(voice.file_id)

        # Save to temp file
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name
            await voice_file.download_to_drive(tmp_path)

        # Transcribe with Whisper (run in thread to not block)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: whisper_model.transcribe(tmp_path)
        )
        transcription = result["text"].strip()

        # Clean up temp file
        os.unlink(tmp_path)

        print(f"Transcription: {transcription[:100]}...")

        # Update acknowledgment with transcription
        await ack_message.edit_text(f"{user_mention} 🎤 \"{transcription}\"\n\n🤔 Thinking...")

        # Send to Claude with conversation continuity
        response = await send_to_claude(chat_id, transcription)
        print(f"Claude response: {response[:100]}...")

        # Add session indicator if using named session
        session_prefix = f"📌 {session_name}\n\n" if session_name else ""
        await ack_message.edit_text(f"{user_mention} 🎤 \"{transcription}\"\n\n{session_prefix}{response}")

    except Exception as e:
        print(f"Error processing voice message: {e}")
        await ack_message.edit_text(f"{user_mention} Error: {e}")


async def main():
    """Start the bot."""
    token = os.getenv("BOT_TOKEN")
    if not token:
        print("Error: BOT_TOKEN not found in environment variables")
        print("Please set BOT_TOKEN in your .env file")
        return

    # Remove quotes if present
    token = token.strip('"').strip("'")

    app = Application.builder().token(token).build()

    # Add command handlers
    app.add_handler(CommandHandler("reset", handle_reset))
    app.add_handler(CommandHandler("new_session", handle_new_session))
    app.add_handler(CommandHandler("switch", handle_switch_session))
    app.add_handler(CommandHandler("sessions", handle_sessions))

    # Add handlers for text and voice messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice_message))

    print(f"Bot started. Listening for messages from @will_bach in chat {ALLOWED_CHAT_ID}...")
    print("Supported: text messages, voice messages")
    print("Commands: /reset, /new_session, /switch, /sessions")
    print(f"Sessions file: {SESSIONS_FILE}")
    print("Press Ctrl+C to stop")

    # Initialize and start polling
    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=["message"])

    # Keep running until interrupted
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
