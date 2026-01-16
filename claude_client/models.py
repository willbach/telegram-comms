"""Data models for Claude client."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class MessageRole(Enum):
    """Role of a message in a conversation."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


@dataclass
class ClaudeConfig:
    """Configuration for Claude client."""
    max_turns: int = 10
    system_prompt: Optional[str] = None
    working_directory: Optional[str] = None
    bypass_permissions: bool = False  # Auto-approve all tool uses


@dataclass
class Message:
    """A message in the conversation history."""
    role: MessageRole
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
