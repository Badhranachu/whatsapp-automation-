"""Audit trail: record who did what. Never lets a logging problem break the real action."""
import logging

from .models import AuditLog

logger = logging.getLogger(__name__)

SENSITIVE = {'password', 'confirm_password', 'token'}


def role_of(user):
    if not user or not getattr(user, 'is_authenticated', False):
        return 'anonymous'
    return 'super_admin' if user.is_superuser else 'staff'


def _ip(request):
    if request is None:
        return ''
    # Behind nginx the real client address arrives in X-Forwarded-For.
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    return (forwarded.split(',')[0].strip() or request.META.get('REMOTE_ADDR', ''))[:45]


def diff(before, after):
    """{"field": {"from": old, "to": new}} for the fields that actually changed."""
    return {
        k: {'from': before.get(k), 'to': after.get(k)}
        for k in after
        if k not in SENSITIVE and before.get(k) != after.get(k)
    }


def record(request, action, entity_type, entity_id='', label='', changes=None, user=None):
    try:
        actor = user or (getattr(request, 'user', None) if request is not None else None)
        authed = bool(actor and getattr(actor, 'is_authenticated', False))
        clean = {k: v for k, v in (changes or {}).items() if k not in SENSITIVE}
        AuditLog.objects.create(
            actor=actor if authed else None,
            actor_email=(actor.email or actor.get_username()) if authed else '',
            actor_role=role_of(actor),
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id or ''),
            entity_label=str(label or '')[:200],
            changes=clean,
            ip_address=_ip(request),
        )
    except Exception:  # noqa: BLE001
        logger.exception('Could not write audit log')
