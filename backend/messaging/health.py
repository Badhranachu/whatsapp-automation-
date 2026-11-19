import logging

from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

logger = logging.getLogger(__name__)


@never_cache
@require_safe
def health(request):
    """Liveness + database check for Docker health checks and deployment verification.

    Public on purpose (no login) and deliberately minimal: it reveals nothing about the
    configuration, paths or versions. 200 = Django is up and the database answers a query,
    503 = the database check failed.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except Exception:  # noqa: BLE001 - any database failure means "not healthy"
        logger.error('Health check: database query failed')
        return JsonResponse({'status': 'unavailable'}, status=503)
    return JsonResponse({'status': 'ok'})
