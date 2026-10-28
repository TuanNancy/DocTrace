"""Delete transcripts whose document retention window has expired.

Run from ``backend/`` (daily scheduler or a one-shot command)::

    python -m app.purge_transcripts

Deleting a conversation cascades its messages. Provider cost rows live in
``provider_calls`` and intentionally survive so usage reporting keeps history
without prompt or transcript content.
"""
import logging

from app.core.config import get_config
from app.core.observability import configure_logging
from app.services.transcripts import purge_expired_transcripts

logger = logging.getLogger("app.purge_transcripts")


def main() -> int:
    config = get_config()
    configure_logging(config, install_root=True)
    try:
        count = purge_expired_transcripts(config)
    except Exception:
        logger.exception("transcript_purge_failed")
        return 1
    logger.info("transcripts_purged", extra={"count": count})
    print(f"Purged {count} expired transcript(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
