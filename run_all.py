import asyncio
import uvicorn

from app.config import get_settings
from app.main import main as bot_main


async def main():
    settings = get_settings()
    server = uvicorn.Server(
        uvicorn.Config("app.web.app:app", host=settings.web_host, port=settings.web_port, log_level="info")
    )
    await asyncio.gather(bot_main(), server.serve())


if __name__ == "__main__":
    asyncio.run(main())
