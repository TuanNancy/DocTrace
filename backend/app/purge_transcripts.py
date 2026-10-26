"""Delete transcripts whose document retention window has expired.

Run from ``backend/`` (daily scheduler or a one-shot command)::

    python -m app.purge_transcripts

Deleting a conversation cascades its messages. Provider cost rows live in
``provider_calls`` and intentionally survive so usage reporting keeps history
without prompt or transcript content.
"""
import logging

from app.core.config import get_config
from app.services.transcripts import purge_expired_transcripts

logger = logging.getLogger(__name__)


def main() -> int:
    count = purge_expired_transcripts(get_config())
    logger.info("Purged %s expired transcripts", count)
    print(f"Purged {count} expired transcript(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
