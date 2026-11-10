"""本番用ブラウザーセキュリティヘッダー。"""


class ContentSecurityPolicyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["Content-Security-Policy"] = (
            "default-src 'self'; "
            "base-uri 'self'; form-action 'self'; object-src 'none'; "
            "frame-ancestors 'none'; "
            "script-src 'self'; "
            "style-src 'self' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net; "
            "img-src 'self' data:; connect-src 'self'"
        )
        return response
