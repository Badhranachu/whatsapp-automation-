"""Read side of the audit trail (super admins only)."""
from django.db.models import Q
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AuditLog
from .users import IsSuperUser

LIMIT_DEFAULT = 100
LIMIT_MAX = 500


class AuditLogListView(APIView):
    """Newest first. Filters: ?q= (who / what), ?action=, ?entity=, ?role=, ?limit=."""

    permission_classes = [IsSuperUser]

    def get(self, request):
        rows = AuditLog.objects.all()
        q = request.query_params.get('q', '').strip()
        if q:
            rows = rows.filter(
                Q(actor_email__icontains=q) | Q(entity_label__icontains=q) | Q(entity_id__iexact=q)
            )
        for param, field in (('action', 'action'), ('entity', 'entity_type'), ('role', 'actor_role')):
            value = request.query_params.get(param, '').strip()
            if value:
                rows = rows.filter(**{field: value})
        try:
            limit = max(1, min(int(request.query_params.get('limit', LIMIT_DEFAULT)), LIMIT_MAX))
        except ValueError:
            limit = LIMIT_DEFAULT
        return Response([
            {
                'id': r.id,
                'actor_email': r.actor_email,
                'actor_role': r.actor_role,
                'action': r.action,
                'entity_type': r.entity_type,
                'entity_id': r.entity_id,
                'entity_label': r.entity_label,
                'changes': r.changes,
                'ip_address': r.ip_address,
                'created_at': r.created_at.isoformat(),
            }
            for r in rows[:limit]
        ])
