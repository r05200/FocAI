# Returned by SSE routes so /docs shows the stream's content type.
SSE_RESPONSES = {
    200: {
        "description": "Server-sent events. `event:` is the event `type`; `data:` is the event "
        "JSON (see pruner/core/events.py). Events carry a strictly increasing `seq`.",
        "content": {"text/event-stream": {}},
    }
}

# Sent with every SSE response: no caching, and no buffering by a proxy in front.
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
