"""
APScheduler jobs that run inside the FastAPI process.

Jobs:
  - process_pending_messages  — every N minutes, batch-analyze unprocessed messages
  - send_due_reminders        — every M minutes, fire scheduled follow-up messages
"""

import logging
import time
from datetime import datetime, timezone

from traick.ai.extractor import extract_from_messages, generate_follow_up_for_project
from traick.config import settings
from traick.db.repository import (
    create_action_item,
    get_active_projects,
    get_active_projects_without_pending_followups,
    get_due_follow_ups,
    get_pending_messages,
    mark_follow_up_sent,
    mark_messages_processed,
    schedule_follow_up,
    upsert_project,
)
from traick.whatsapp.sender import send_template_message

logger = logging.getLogger(__name__)


async def _process_group(owner_number: str, messages: list[dict]) -> None:
    """Extract project updates from one contact's messages and persist them."""
    existing = await get_active_projects(owner_number)
    result = await extract_from_messages(messages, existing_projects=existing)

    for update in result.updates:
        project_id = await upsert_project(
            owner_number=owner_number,
            name=update.project_name,
            description=update.description,
            status=update.project_status or "active",
        )

        first_action_item_id: int | None = None
        for item in update.action_items:
            deadline_ts: int | None = None
            if item.deadline_iso:
                try:
                    dt = datetime.fromisoformat(item.deadline_iso).replace(
                        tzinfo=timezone.utc
                    )
                    deadline_ts = int(dt.timestamp())
                except ValueError:
                    logger.warning("Bad deadline format: %s", item.deadline_iso)

            action_item_id = await create_action_item(
                project_id=project_id,
                description=item.description,
                deadline=deadline_ts,
            )
            if first_action_item_id is None:
                first_action_item_id = action_item_id

        if update.follow_up_message and update.follow_up_days is not None:
            scheduled_at = int(time.time()) + update.follow_up_days * 86400
            await schedule_follow_up(
                project_id=project_id,
                action_item_id=first_action_item_id,
                message=update.follow_up_message,
                scheduled_at=scheduled_at,
            )
            logger.info(
                "Scheduled follow-up for '%s' (owner %s) in %d days",
                update.project_name,
                owner_number,
                update.follow_up_days,
            )


async def process_pending_messages() -> None:
    """
    Fetch unprocessed messages → group by sender → call Claude per group
    → upsert projects / action items / follow-ups scoped to each number.
    """
    messages = await get_pending_messages(limit=settings.batch_size)
    if not messages:
        return

    # Group by originating number so each contact's projects stay isolated
    groups: dict[str, list[dict]] = {}
    for msg in messages:
        groups.setdefault(msg["from_number"], []).append(msg)

    logger.info("Processing %d messages from %d number(s)", len(messages), len(groups))

    for owner_number, group in groups.items():
        await _process_group(owner_number, group)

    processed_ids = [m["id"] for m in messages]
    await mark_messages_processed(processed_ids)
    logger.info("Done — marked %d messages as processed", len(processed_ids))


async def ensure_active_project_followups() -> None:
    """
    Daily safety-net: find active projects with no pending follow-up and schedule one.
    Catches any project the extractor processed without a reminder suggestion.
    """
    projects = await get_active_projects_without_pending_followups()
    if not projects:
        return

    logger.info("Found %d active project(s) without a pending follow-up", len(projects))
    for project in projects:
        message, days = await generate_follow_up_for_project(project)
        scheduled_at = int(time.time()) + days * 86400
        await schedule_follow_up(
            project_id=project["id"],
            action_item_id=None,
            message=message,
            scheduled_at=scheduled_at,
        )
        logger.info(
            "Auto-scheduled follow-up for '%s' (owner %s) in %d days",
            project["name"],
            project["owner_number"],
            days,
        )


async def send_due_reminders() -> None:
    """Send all follow-up reminders whose scheduled_at time has passed."""
    follow_ups = await get_due_follow_ups()
    if not follow_ups:
        return

    logger.info("Sending %d due follow-up(s)", len(follow_ups))
    for fu in follow_ups:
        success = await send_template_message(to=fu["owner_number"], body=fu["message"])
        if success:
            await mark_follow_up_sent(fu["id"])
