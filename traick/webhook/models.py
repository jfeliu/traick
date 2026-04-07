"""Pydantic models for inbound Meta WhatsApp Cloud API webhook payloads."""

from typing import Any
from pydantic import BaseModel


class WhatsAppTextMessage(BaseModel):
    body: str


class WhatsAppMessage(BaseModel):
    id: str
    from_: str
    timestamp: str
    type: str
    text: WhatsAppTextMessage | None = None

    model_config = {"populate_by_name": True, "extra": "allow"}

    @classmethod
    def from_raw(cls, data: dict) -> "WhatsAppMessage":
        # Meta uses "from" which is a Python keyword — remap it
        if "from" in data:
            data = {**data, "from_": data.pop("from")}
        return cls.model_validate(data)


class WhatsAppContact(BaseModel):
    profile: dict[str, Any] = {}
    wa_id: str


class WhatsAppValue(BaseModel):
    messaging_product: str
    metadata: dict[str, Any] = {}
    contacts: list[WhatsAppContact] = []
    messages: list[dict[str, Any]] = []  # raw dicts, parsed individually


class WhatsAppChange(BaseModel):
    value: WhatsAppValue
    field: str


class WhatsAppEntry(BaseModel):
    id: str
    changes: list[WhatsAppChange]


class WhatsAppWebhookPayload(BaseModel):
    object: str
    entry: list[WhatsAppEntry]
