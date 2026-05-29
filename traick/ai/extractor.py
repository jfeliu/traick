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
- Extract action items and deadlines from the messages. Every active project must have at least one action item — if no specific sub-tasks are mentioned, create one action item that captures the main thing to be done.
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
        project_lines = []
        for p in existing_projects:
            line = f'- "{p["name"]}": {p["description"] or "no description"} (status: {p["status"]})'
            if p.get("open_tasks"):
                line += f'\n  Open tasks: {p["open_tasks"]}'
            project_lines.append(line)
        context = (
            "\n\nExisting projects already tracked for this person:\n"
            + "\n".join(project_lines)
            + "\n\nIMPORTANT: Before creating a new project, check whether the message could be "
            "an update to any existing project based on topic similarity — not just exact name. "
            "If a match is plausible, update the existing project using its EXACT name as listed above. "
            "Only create a new project when the content clearly doesn't relate to any existing one."
        )

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


class _FollowUpSuggestion(BaseModel):
    message: str
    days: int


async def generate_follow_up_for_project(project: dict) -> tuple[str, int]:
    """
    Generate a follow-up reminder for a project that has no pending follow-up scheduled.
    Returns (message_text, days_until_send).
    Falls back to a generic message on failure.
    """
    base_client = get_client()
    client = instructor.from_openai(base_client, mode=instructor.Mode.JSON)

    prompt = (
        f'Project: {project["name"]}\n'
        f'Description: {project.get("description") or "no description"}\n'
        f'Last updated: {project.get("updated_at", "unknown")}\n\n'
        "Write a short, friendly WhatsApp follow-up reminder for this project. "
        "Choose 1–14 days based on urgency (recent/urgent = fewer days, longer-term = more). "
        'Output JSON with "message" (the reminder text) and "days" (integer).'
    )

    try:
        result = await client.chat.completions.create(
            model=settings.ai_model,
            max_tokens=256,
            response_model=_FollowUpSuggestion,
            messages=[
                {
                    "role": "system",
                    "content": "You generate concise WhatsApp follow-up reminders for a project tracker. Output ONLY valid JSON.",
                },
                {"role": "user", "content": prompt},
            ],
        )
        return result.message, result.days
    except Exception:
        logger.exception("Failed to generate follow-up for project '%s'", project.get("name"))
        return f"Any updates on {project['name']}?", 7
