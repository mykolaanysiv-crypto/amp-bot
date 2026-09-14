import uvicorn
from app.config import get_settings

if __name__ == "__main__":
    s = get_settings(require_bot_token=False)
    uvicorn.run("app.web.app:app", host=s.web_host, port=s.web_port, reload=False)
