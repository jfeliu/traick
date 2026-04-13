"""
Generate a conversational reply to an incoming WhatsApp message.

Uses project context and recent conversation history so the model can respond
intelligently on behalf of the user — e.g. confirming details with a provider,
asking for updates, or acknowledging progress.
"""

from __future__ import annotations

import logging

from traick.ai.client import get_client
from traick.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a helpful assistant managing personal projects via WhatsApp on behalf of the user.
When someone sends a message, your job is to reply naturally and move the conversation forward.

You will receive context (projects and conversation history) followed by the incoming message.

Guidelines:
- Reply in the same language as the incoming message.
- Be concise and friendly — this is WhatsApp, not email.
- If the message is about a known project, acknowledge the update and ask the right next question if needed.
- If the message confirms something (e.g. a visit, a deadline), confirm receipt and note any next steps. Unless you've already acknowledged the confirmation in a previous message, then just output exactly: NO_REPLY.
- If the message is ambiguous, ask a clarifying question.
- If no reply is needed, output exactly: NO_REPLY. Examples that require NO_REPLY:
  * Farewells or goodbyes (adéu, bye, hasta luego, fins aviat, ciao...)
  * Pure acknowledgments with no question (👍, ok, gràcies, entesos, perfecte...)
  * The contact already said goodbye earlier in the history
  * You already replied to this same message or a very similar one in the history
- Never make up facts. Only reference information from the project context provided.

IMPORTANT: Output ONLY your reply message. Do not repeat context, history, timestamps, or any other text."""


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
        project_context = f"<projects>\n{lines}\n</projects>\n\n"

    history_context = ""
    if recent_messages:
        lines = "\n".join(
            f"[{m['timestamp']}] {'You' if m.get('direction') == 'out' else 'Contact'}: {m['body']}"
            for m in recent_messages
        )
        history_context = f"<history>\n{lines}\n</history>\n\n"

    user_content = (
        f"{project_context}{history_context}"
        f"<incoming>\n{incoming}\n</incoming>\n\n"
        f"Reply:"
    )

    client = get_client()
    try:
        logger.debug("Responder prompt:\n%s", user_content)
        response = await client.chat.completions.create(
            model=settings.ai_model,
            max_tokens=512,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )
        raw = response.choices[0].message.content.strip()
        logger.debug("Responder raw response:\n%s", raw)
        # Guard against models echoing back context after the reply — take only
        # the first paragraph (content before the first blank line).
        reply = raw.split("\n\n")[0].strip()
        if reply.upper() == "NO_REPLY":
            logger.debug("Responder chose not to reply to message from %s", from_number)
            return None
        # Guard against sending the same message twice — if the reply is identical
        # to the last outgoing message, the model got stuck in a loop.
        last_outgoing = next(
            (m["body"] for m in reversed(recent_messages) if m.get("direction") == "out"),
            None,
        )
        if last_outgoing and reply.strip() == last_outgoing.strip():
            logger.debug("Reply identical to last outgoing message, suppressing for %s", from_number)
            return None
        logger.info("Generated reply for %s", from_number)
        return reply
    except Exception:
        logger.exception("Failed to generate reply for %s", from_number)
        return None
