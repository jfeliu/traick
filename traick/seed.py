"""
CLI command to seed existing projects into the database.

Reads a free-form text description of your projects from a file or stdin,
runs it through the AI extractor, and persists the results — exactly as if
the text had arrived as a WhatsApp message from your own number.

Usage:
    traick-seed projects.txt
    echo "Working on X, next step is Y by Friday" | traick-seed
"""

import asyncio
import logging
import sys

from traick.config import settings
from traick.db.database import init_db
from traick.scheduler.jobs import _process_group

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)


def run() -> None:
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    text = text.strip()
    if not text:
        print("No input provided.", file=sys.stderr)
        sys.exit(1)

    asyncio.run(_seed(text))


async def _seed(text: str) -> None:
    await init_db()
    messages = [{"body": text, "from_number": settings.to_phone_number}]
    await _process_group(settings.to_phone_number, messages)
