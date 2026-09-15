from __future__ import annotations

import logging

from app.observability import configure_observability


def main() -> None:
    configure_observability(service="release")

    # v1.12.1: the release phase is itself the production stability gate. It
    # runs real database bootstrap, Alembic and the actual FastAPI lifespan in
    # side-effect-safe smoke mode. Any NameError/import/startup regression
    # aborts the Heroku release before web/worker dynos are promoted.
    from scripts.startup_smoke import run as startup_smoke
    startup_smoke()

    from scripts.production_preflight import main as production_preflight
    production_preflight()
    logging.getLogger("amp.release").info(
        "Release gate PASS: lifecycle smoke + production preflight completed"
    )


if __name__ == "__main__":
    main()
