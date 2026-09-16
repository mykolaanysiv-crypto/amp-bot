import uvicorn

from app.config import get_settings
from app.observability import configure_observability

if __name__ == "__main__":
    configure_observability(service="web")
    s = get_settings(require_bot_token=False)
    uvicorn.run(
        "app.web.factory:create_app",
        factory=True,
        host=s.web_host,
        port=s.web_port,
        reload=False,
        log_config=None,
    )
