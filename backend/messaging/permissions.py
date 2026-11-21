"""Who may use the API.

The whole application API is for super admins only. This one class is the DRF default permission (see
REST_FRAMEWORK in config/settings.py), so every view is protected unless it says otherwise on purpose.
The only views that override it are the sign-in steps (they must be reachable before anyone is signed in).
"""
from rest_framework.permissions import BasePermission


def is_active_super_admin(user):
    """The one rule, read from the database user that the token belongs to (never from request data)."""
    return bool(user and user.is_authenticated and user.is_active and user.is_superuser)


class IsSuperAdmin(BasePermission):
    """Signed in (valid token) AND an active super admin.

    Not signed in -> 401 (TokenAuthentication supplies the challenge header).
    Signed in but not a super admin -> 403.
    """

    message = 'Super admin access is required.'

    def has_permission(self, request, view):
        return is_active_super_admin(request.user)

    def has_object_permission(self, request, view, obj):
        return is_active_super_admin(request.user)
