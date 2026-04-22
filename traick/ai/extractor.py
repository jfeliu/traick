"""
Batch-analyze unprocessed WhatsApp messages with a local AI model and extract
structured project/task data.

Uses:
  - Ollama-hosted model via OpenAI-compatible API
  - instructor for validated Pydantic structured output
"""

from __future__ import annotations

import logging
from typing import Literal

import instructor
from pydantic import BaseModel, field_validator

from traick.ai.client import get_client
from traick.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a personal project tracker. Read a batch of WhatsApp messages and extract \
project-related information. Output ONLY valid JSON matching the schema below — no \
explanation, no markdown, no code fences.

Schema:
{
  "updates": [
    {
      "project_name": "Short name (1-5 words)",
      "project_status": "active" | "paused" | "done" | null,
      "description": "Brief description of the project" | null,
      "action_items": [
        {
          "description": "What needs to be done",
          "deadline_iso": "2026-04-15" | null
        }
      ],
      "follow_up_message": "Reminder message to send later" | null,
      "follow_up_days": 3 | null
    }
  ]
}

Rules:
- Extract action items and deadlines from the messages.
- If multiple messages refer to the same project, merge them.
- For deadlines, use ISO 8601 date format (e.g. "2026-04-15") or null.
- Always suggest a follow_up_message and follow_up_days for any active project — be proactive. Choose a sensible number of days based on urgency (same day = 1, this week = 3, longer term = 7+).
- follow_up_message and follow_up_days must both be set or both be null.
- If no project-related content is found, return {"updates": []}.

Example output:
{
  "updates": [
    {
      "project_name": "Website redesign",
      "project_status": "active",
      "description": "Redesigning the company website",
      "action_items": [
        {"description": "Send mockups to client", "deadline_iso": "2026-04-20"},
        {"description": "Review feedback", "deadline_iso": null}
      ],
      "follow_up_message": "Did you finish the mockups?",
      "follow_up_days": 3
    }
  ]
}"""


class ActionItemExtract(BaseModel):
    description: str = ""
    deadline_iso: str | None = None


class ProjectUpdate(BaseModel):
    project_name: str
    project_status: Literal["active", "paused", "done"] | None
    description: str | None
    action_items: list[ActionItemExtract]
    follow_up_message: str | None
    follow_up_days: int | None

    @field_validator("action_items", mode="before")
    @classmethod
    def drop_empty_action_items(cls, v: list) -> list:
        return [item for item in v if item and item.get("description")]


class ExtractionResult(BaseModel):
    updates: list[ProjectUpdate]


async def extract_from_messages(
    messages: list[dict],
    existing_projects: list[dict] | None = None,
) -> ExtractionResult:
    """
    Send a batch of raw messages to the local AI model and get structured project updates back.

    Args:
        messages: List of raw_message dicts from the DB (keys: body, timestamp, from_number)
        existing_projects: Optional list of project dicts already in the DB for this owner.

    Returns:
        ExtractionResult with a list of ProjectUpdate objects
    """
    if not messages:
        return ExtractionResult(updates=[])

    formatted = "\n".join(f"[{i + 1}] {m['body']}" for i, m in enumerate(messages))

    context = ""
    if existing_projects:
        project_lines = "\n".join(
            f"- {p['name']}: {p['description'] or 'no description'} (status: {p['status']})"
            for p in existing_projects
        )
        context = f"\n\nExisting projects already tracked for this person:\n{project_lines}\n\nMatch messages to these projects by name when relevant. Use the exact existing project name if the message clearly refers to it."

    user_content = f"Analyze these WhatsApp messages and extract project information:{context}\n\nMessages:\n{formatted}"

    base_client = get_client()
    client = instructor.from_openai(base_client, mode=instructor.Mode.JSON)

    try:
        logger.info("Extractor prompt:\n%s", user_content)
        result = await client.chat.completions.create(
            model=settings.ai_model,
            max_tokens=4096,
            response_model=ExtractionResult,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )
        logger.info("Extractor response:\n%s", result.model_dump_json(indent=2))

        logger.info(
            "Extracted %d project updates from %d messages",
            len(result.updates),
            len(messages),
        )
        return result

    except Exception:
        logger.exception("Extraction failed")
        return ExtractionResult(updates=[])
