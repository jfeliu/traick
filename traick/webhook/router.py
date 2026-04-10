"""
Webhook endpoints for the Meta WhatsApp Cloud API.

GET  /webhook  — verification handshake (Meta calls this once when you set up the webhook)
POST /webhook  — inbound message notifications
"""

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request

from traick.ai.responder import generate_reply
from traick.config import settings
from traick.db.repository import (
    get_active_projects,
    get_recent_messages,
    save_raw_message,
)
from traick.webhook.models import WhatsAppMessage, WhatsAppWebhookPayload
from traick.whatsapp.sender import send_message

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook")


@router.get("")
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode", default=""),
    hub_verify_token: str = Query(alias="hub.verify_token", default=""),
    hub_challenge: str = Query(alias="hub.challenge", default=""),
):
    """Meta calls this endpoint to verify the webhook URL."""
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        logger.info("Webhook verified")
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


async def _handle_reply(from_number: str, incoming: str) -> None:
    """Generate and send a conversational reply in the background."""
    projects = await get_active_projects(from_number)
    recent = await get_recent_messages(from_number, limit=10)
    reply = await generate_reply(
        incoming=incoming,
        from_number=from_number,
        projects=projects,
        recent_messages=recent,
    )
    if reply:
        await send_message(to=from_number, body=reply)


@router.post("")
async def receive_message(request: Request, background_tasks: BackgroundTasks):
    """Receive inbound messages from Meta, persist them, and reply in the background."""
    try:
        body = await request.json()
        payload = WhatsAppWebhookPayload.model_validate(body)
    except Exception:
        logger.exception("Failed to parse webhook payload")
        # Always return 200 to Meta — otherwise it retries aggressively
        return {"status": "error"}

    for entry in payload.entry:
        for change in entry.changes:
            if change.field != "messages":
                continue
            for raw_msg in change.value.messages:
                try:
                    msg = WhatsAppMessage.from_raw(raw_msg)
                    if msg.type != "text" or msg.text is None:
                        continue
                    # Drop messages from numbers not in the whitelist
                    if (
                        settings.allowed_number_list
                        and msg.from_ not in settings.allowed_number_list
                    ):
                        logger.debug(
                            "Ignored message from unlisted number %s", msg.from_
                        )
                        continue
                    await save_raw_message(
                        wa_id=msg.id,
                        from_number=msg.from_,
                        body=msg.text.body,
                        timestamp=int(msg.timestamp),
                    )
                    logger.info("Saved message %s from %s", msg.id, msg.from_)
                    background_tasks.add_task(_handle_reply, msg.from_, msg.text.body)
                except Exception:
                    logger.exception("Failed to save message %s", raw_msg.get("id"))

    return {"status": "ok"}
