"""ASGI entrypoint with CORS headers."""
import os
import re

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "supportiq.settings")

django_app = get_asgi_application()

ALLOWED_ORIGIN_PATTERNS = [
    r"^https://supportiq-client\.vercel\.app$",
    r"^https://supportiq-client-.*\.vercel\.app$",
]

async def application(scope, receive, send):
    if scope["type"] == "http":
        # Get origin from headers
        headers = dict(scope.get("headers", []))
        origin = headers.get(b"origin", b"").decode()
        
        # Check if origin is allowed
        allowed_origin = None
        for pattern in ALLOWED_ORIGIN_PATTERNS:
            if re.match(pattern, origin):
                allowed_origin = origin
                break
        
        # Handle preflight
        if scope["method"] == "OPTIONS":
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"access-control-allow-origin", allowed_origin.encode() if allowed_origin else b""),
                    (b"access-control-allow-methods", b"GET, POST, PUT, PATCH, DELETE, OPTIONS"),
                    (b"access-control-allow-headers", b"Content-Type, Authorization"),
                    (b"access-control-allow-credentials", b"true"),
                ],
            })
            await send({"type": "http.response.body", "body": b""})
            return
        
        # Wrap send to add CORS headers
        async def send_with_cors(message):
            if message["type"] == "http.response.start" and allowed_origin:
                headers = list(message.get("headers", []))
                headers.append((b"access-control-allow-origin", allowed_origin.encode()))
                headers.append((b"access-control-allow-credentials", b"true"))
                message["headers"] = headers
            await send(message)
        
        await django_app(scope, receive, send_with_cors)
    else:
        await django_app(scope, receive, send)
