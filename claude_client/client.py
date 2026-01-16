"""Claude Code SDK client wrapper."""

from typing import AsyncIterator, Optional
from claude_code_sdk import query, ClaudeCodeOptions, ResultMessage

from .models import ClaudeConfig, Message, MessageRole


class ClaudeClient:
    """Client for interacting with Claude Code programmatically."""

    def __init__(self, config: ClaudeConfig = None):
        """Initialize the client with optional configuration.

        Args:
            config: Configuration options for Claude. Uses defaults if None.
        """
        self.config = config or ClaudeConfig()
        self.history: list[Message] = []
        self.session_id: Optional[str] = None  # For conversation continuity

    async def send(self, prompt: str, resume_session: Optional[str] = None) -> tuple[str, Optional[str]]:
        """Send a prompt and get the full response.

        Args:
            prompt: The message to send to Claude.
            resume_session: Optional session ID to resume a previous conversation.

        Returns:
            Tuple of (response text, session_id for continuation).
        """
        # Record user message
        self.history.append(Message(role=MessageRole.USER, content=prompt))

        options = ClaudeCodeOptions(
            max_turns=self.config.max_turns,
            system_prompt=self.config.system_prompt,
            cwd=self.config.working_directory,
            permission_mode='bypassPermissions' if self.config.bypass_permissions else 'default',
            resume=resume_session,  # Resume previous conversation if provided
        )

        response_parts = []
        session_id = None
        async for message in query(prompt=prompt, options=options):
            # Extract text content from message
            if hasattr(message, 'content') and message.content:
                for block in message.content:
                    if hasattr(block, 'text'):
                        response_parts.append(block.text)
            # Capture session_id from ResultMessage
            if isinstance(message, ResultMessage) and hasattr(message, 'session_id'):
                session_id = message.session_id

        response = ''.join(response_parts)

        # Record assistant message
        self.history.append(Message(role=MessageRole.ASSISTANT, content=response))

        return response, session_id

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        """Send a prompt and stream response chunks.

        Args:
            prompt: The message to send to Claude.

        Yields:
            Text chunks as they arrive from Claude.
        """
        self.history.append(Message(role=MessageRole.USER, content=prompt))

        options = ClaudeCodeOptions(
            max_turns=self.config.max_turns,
            system_prompt=self.config.system_prompt,
            cwd=self.config.working_directory,
            permission_mode='bypassPermissions' if self.config.bypass_permissions else 'default',
        )

        response_parts = []
        async for message in query(prompt=prompt, options=options):
            if hasattr(message, 'content') and message.content:
                for block in message.content:
                    if hasattr(block, 'text'):
                        response_parts.append(block.text)
                        yield block.text

        # Record full response
        self.history.append(
            Message(role=MessageRole.ASSISTANT, content=''.join(response_parts))
        )

    def clear_history(self):
        """Clear the conversation history."""
        self.history.clear()

    def get_history(self) -> list[Message]:
        """Get the conversation history.

        Returns:
            List of messages in the conversation.
        """
        return self.history.copy()
