"""
Batch-analyze unprocessed WhatsApp messages with Claude and extract structured
project/task data.

Uses:
  - claude-opus-4-6 with adaptive thinking
  - prompt caching (1h TTL) on the stable system prompt
  - client.messages.parse() for validated Pydantic output
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel

from traick.ai.client import get_client

logger = logging.getLogger(__name__)

MODEL = "claude-opus-4-6"

SYSTEM_PROMPT = """\
You are a personal project tracker. Your job is to read a batch of WhatsApp messages \
and extract project-related information from them.

For each batch of messages you receive, identify:
1. Projects mentioned (by name or clear description)
2. Action items, tasks, or next steps tied to each project
3. Any deadlines or time-sensitive details
4. Whether a project's status changed (active, paused, done)
5. Whether a follow-up reminder would be helpful

Rules:
- Only extract information that is clearly present in the messages.
- If multiple messages refer to the same project, merge them.
- For deadlines, output an ISO 8601 date string (e.g. "2026-04-15") or null.
- For follow-up suggestions, be specific and actionable (e.g. "Check if you finished \
the landing page design").
- If no project-related content is found, return an empty updates list.
- Project names should be concise (1-5 words).

Today's context: You are analyzing personal project updates and conversation snippets. \
The user wants to stay on top of their personal projects and needs gentle nudges when \
tasks fall through the cracks."""


class ActionItemExtract(BaseModel):
    description: str
    deadline_iso: str | None  # ISO 8601 date string or null


class FollowUpSuggestion(BaseModel):
    message: str  # The reminder message to send
    days_from_now: int  # When to send it


class ProjectUpdate(BaseModel):
    project_name: str
    project_status: Literal["active", "paused", "done"] | None
    description: str | None
    action_items: list[ActionItemExtract]
    suggested_follow_up: FollowUpSuggestion | None


class ExtractionResult(BaseModel):
    updates: list[ProjectUpdate]


async def extract_from_messages(
    messages: list[dict],
    existing_projects: list[dict] | None = None,
) -> ExtractionResult:
    """
    Send a batch of raw messages to Claude and get structured project updates back.

    Args:
        messages: List of raw_message dicts from the DB (keys: body, timestamp, from_number)
        existing_projects: Optional list of project dicts already in the DB for this owner.
                           Providing this lets Claude match messages to existing projects
                           instead of creating duplicates.

    Returns:
        ExtractionResult with a list of ProjectUpdate objects
    """
    if not messages:
        return ExtractionResult(updates=[])

    # Format messages as a numbered list for the prompt
    formatted = "\n".join(
        f"[{i+1}] {m['body']}" for i, m in enumerate(messages)
    )

    context = ""
    if existing_projects:
        project_lines = "\n".join(
            f"- {p['name']}: {p['description'] or 'no description'} (status: {p['status']})"
            for p in existing_projects
        )
        context = f"\n\nExisting projects already tracked for this person:\n{project_lines}\n\nMatch messages to these projects by name when relevant. Use the exact existing project name if the message clearly refers to it."

    user_content = f"Analyze these WhatsApp messages and extract project information:{context}\n\nMessages:\n{formatted}"

    client = get_client()

    try:
        response = await client.messages.parse(
            model=MODEL,
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    # Cache the system prompt for 1h — it never changes between calls
                    "cache_control": {"type": "ephemeral", "ttl": "1h"},
                }
            ],
            messages=[{"role": "user", "content": user_content}],
            output_format=ExtractionResult,
        )

        result = response.parsed_output
        if result is None:
            logger.warning("Claude returned unparseable output, skipping batch")
            return ExtractionResult(updates=[])

        logger.info(
            "Extracted %d project updates from %d messages (cache_read=%s)",
            len(result.updates),
            len(messages),
            response.usage.cache_read_input_tokens,
        )
        return result

    except Exception:
        logger.exception("Extraction failed")
        return ExtractionResult(updates=[])
