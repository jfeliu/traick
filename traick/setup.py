"""
CLI command to set up traick's Meta resources.

Currently: creates the WhatsApp message template used for proactive reminders.

Usage:
    traick-setup
"""

import asyncio
import logging

from traick.whatsapp.sender import REMINDER_TEMPLATE_NAME, create_reminder_template

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)


def run() -> None:
    print(f"Creating WhatsApp template '{REMINDER_TEMPLATE_NAME}'...")
    success = asyncio.run(create_reminder_template())
    if success:
        print("Done. The template may take a few minutes to be approved by Meta.")
        print("Check status at: developers.facebook.com → WhatsApp → Message Templates")
    else:
        print("Failed. Check logs above for details.")
