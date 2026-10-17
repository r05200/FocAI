from typing import NoReturn

from fastapi import HTTPException


def not_implemented(what: str) -> NoReturn:
    """Placeholder body for a route whose logic has not been built yet."""
    raise HTTPException(status_code=501, detail=f"{what} is not implemented yet")


# Returned by SSE routes so /docs shows the stream's content type.
SSE_RESPONSES = {
    200: {
        "description": "Server-sent events. `event:` is the event `type`; `data:` is the event "
        "JSON (see pruner/core/events.py). Events carry a strictly increasing `seq`.",
        "content": {"text/event-stream": {}},
    }
}
