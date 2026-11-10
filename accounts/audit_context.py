"""リクエスト中の操作主体を監査シグナルへ渡す。"""

from contextvars import ContextVar


current_actor = ContextVar("attendance_current_actor", default=None)


class AuditActorMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        actor = request.user if request.user.is_authenticated else None
        token = current_actor.set(actor)
        try:
            return self.get_response(request)
        finally:
            current_actor.reset(token)
