from django.conf import settings
from django.http import HttpRequest, JsonResponse


def health(request: HttpRequest) -> JsonResponse:
    if not settings.KVZ_PERSISTENCE.healthcheck():
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})
