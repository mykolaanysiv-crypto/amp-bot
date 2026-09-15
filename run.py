import asyncio

from app.observability import configure_observability
from app.main import main

if __name__ == "__main__":
    configure_observability(service="worker")
    asyncio.run(main())
