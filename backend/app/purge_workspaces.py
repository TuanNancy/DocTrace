"""One bounded recovery pass: python -m app.purge_workspaces."""
from app.core.config import get_config
from app.core.observability import configure_logging
from app.services.failures import flush_failures
from app.services.purges import advance_purges


def main() -> None:
    config = get_config()
    configure_logging(config, install_root=True)
    advance_purges(config)
    flush_failures(config)


if __name__ == "__main__":
    main()
