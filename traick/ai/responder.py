"""
Generate a conversational reply to an incoming WhatsApp message.

Uses project context and recent conversation history so Claude can respond
intelligently on behalf of the user — e.g. confirming details with a provider,
asking for updates, or acknowledging progress.
"""

from __future__ import annotations

import logging

from traick.ai.client import get_client

logger = logging.getLogger(__name__)

MODEL = "claude-opus-4-6"

SYSTEM_PROMPT = """\
You are a helpful assistant managing personal projects via WhatsApp on behalf of the user.
When someone sends a message, your job is to reply naturally and move the conversation forward.

You have access to the user's current projects and recent conversation history.

Guidelines:
- Reply in the same language as the incoming message.
- Be concise and friendly — this is WhatsApp, not email.
- If the message is about a known project, acknowledge the update and ask the right next question.
- If the message confirms something (e.g. a visit, a deadline), confirm receipt and note any next steps.
- If the message is ambiguous, ask a clarifying question.
- If no reply is needed (e.g. spam, irrelevant content), reply with exactly: NO_REPLY
- Never make up facts. Only reference information from the project context provided."""


async def generate_reply(
    incoming: str,
    from_number: str,
    projects: list[dict],
    recent_messages: list[dict],
) -> str | None:
    """
    Generate a reply to an incoming message.

    Returns the reply text, or None if no reply should be sent.
    """
    project_context = ""
    if projects:
        lines = "\n".join(
            f"- {p['name']}: {p['description'] or 'no description'} (status: {p['status']})"
            for p in projects
        )
        project_context = f"\nTracked projects for this contact:\n{lines}\n"

    history_context = ""
    if recent_messages:
        lines = "\n".join(f"  [{m['timestamp']}] {m['body']}" for m in recent_messages)
        history_context = f"\nRecent conversation history:\n{lines}\n"

    user_content = (
        f"{project_context}{history_context}\n"
        f"Incoming message from {from_number}:\n{incoming}"
    )

    client = get_client()
    try:
        response = await client.messages.create(
            model=MODEL,
            max_tokens=512,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral", "ttl": "1h"},
                }
            ],
            messages=[{"role": "user", "content": user_content}],
        )
        reply = response.content[0].text.strip()
        if reply == "NO_REPLY":
            logger.debug("Responder chose not to reply to message from %s", from_number)
            return None
        logger.info("Generated reply for %s", from_number)
        return reply
    except Exception:
        logger.exception("Failed to generate reply for %s", from_number)
        return None
