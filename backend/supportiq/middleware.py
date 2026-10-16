"""Minimal CORS middleware - no external dependency."""
import re

ALLOWED_ORIGIN_PATTERNS = [
    r"^https://supportiq-client\.vercel\.app$",
    r"^https://supportiq-client-.*\.vercel\.app$",
]

def cors_middleware(get_response):
    def middleware(request):
        # Handle preflight
        if request.method == "OPTIONS":
            from django.http import HttpResponse
            response = HttpResponse(status=200)
        else:
            response = get_response(request)
        
        origin = request.META.get("HTTP_ORIGIN", "")
        for pattern in ALLOWED_ORIGIN_PATTERNS:
            if re.match(pattern, origin):
                response["Access-Control-Allow-Origin"] = origin
                response["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
                response["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
                response["Access-Control-Allow-Credentials"] = "true"
                break
        return response
    return middleware
