"""
Send WhatsApp messages via the Meta Cloud API.

Docs: https://developers.facebook.com/docs/whatsapp/cloud-api/messages
"""

import logging

import httpx

from traick.config import settings

logger = logging.getLogger(__name__)

META_API_BASE = "https://graph.facebook.com/v20.0"
REMINDER_TEMPLATE_NAME = "traick_recordatori_v2"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.whatsapp_token}",
        "Content-Type": "application/json",
    }


async def send_message(to: str, body: str) -> bool:
    """
    Send a free-form text message (only works within the 24h customer service window).
    """
    url = f"{META_API_BASE}/{settings.whatsapp_phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to.lstrip("+"),
        "type": "text",
        "text": {"body": body},
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(url, json=payload, headers=_headers())
            resp.raise_for_status()
            logger.info("Sent message to %s", to)
            return True
        except httpx.HTTPStatusError as e:
            logger.error("Failed to send message to %s: %s %s", to, e.response.status_code, e.response.text)
            return False
        except Exception:
            logger.exception("Unexpected error sending message to %s", to)
            return False


async def send_template_message(to: str, body: str) -> bool:
    """
    Send a message using the approved reminder template.
    Works outside the 24h window — use this for proactive reminders.
    """
    url = f"{META_API_BASE}/{settings.whatsapp_phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to.lstrip("+"),
        "type": "template",
        "template": {
            "name": REMINDER_TEMPLATE_NAME,
            "language": {"code": "ca"},
            "components": [{
                "type": "body",
                "parameters": [{"type": "text", "text": body}],
            }],
        },
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(url, json=payload, headers=_headers())
            resp.raise_for_status()
            logger.info("Sent template message to %s", to)
            return True
        except httpx.HTTPStatusError as e:
            logger.error("Failed to send template message to %s: %s %s", to, e.response.status_code, e.response.text)
            return False
        except Exception:
            logger.exception("Unexpected error sending template message to %s", to)
            return False


async def create_reminder_template() -> bool:
    """
    Create the traick_reminder_v2 template in the Meta Business account.
    Template body is a single variable {{1}} so any reminder text can be passed in.
    Only needs to be called once — subsequent calls are safe (returns existing template).
    """
    url = f"{META_API_BASE}/{settings.whatsapp_business_account_id}/message_templates"
    payload = {
        "name": REMINDER_TEMPLATE_NAME,
        "language": "ca",
        "category": "UTILITY",
        "components": [{
            "type": "BODY",
            "text": "Hola! Com va? {{1}}. Gràcies.",
        }],
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(url, json=payload, headers=_headers())
            if resp.status_code == 400 and ("already exists" in resp.text.lower()):
                logger.info("Template '%s' already exists", REMINDER_TEMPLATE_NAME)
                return True
            resp.raise_for_status()
            data = resp.json()
            logger.info(
                "Template '%s' created (id=%s, status=%s)",
                REMINDER_TEMPLATE_NAME,
                data.get("id"),
                data.get("status"),
            )
            return True
        except httpx.HTTPStatusError as e:
            logger.error("Failed to create template: %s %s", e.response.status_code, e.response.text)
            return False
        except Exception:
            logger.exception("Unexpected error creating template")
            return False
