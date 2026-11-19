"""User management: super admins can list, add and remove other super admins."""
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import transaction
from rest_framework import serializers, status
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import UserProfile
from .serializers import SendMessageSerializer

MAX_EMAIL_LENGTH = 150  # the built-in User.username limit; the email is the username


class IsSuperUser(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_superuser and user.is_active)


def describe(user):
    profile = getattr(user, 'profile', None)
    return {
        'id': user.id,
        'email': user.email,
        'phone_number': profile.phone_number if profile else '',
        'is_active': user.is_active,
        'date_joined': user.date_joined.isoformat(),
    }


class CreateUserSerializer(serializers.Serializer):
    email = serializers.CharField(max_length=MAX_EMAIL_LENGTH)
    phone_number = serializers.CharField()
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)
    confirm_password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)

    def validate_email(self, value):
        value = value.strip().lower()
        try:
            validate_email(value)
        except DjangoValidationError:
            raise serializers.ValidationError('Enter a valid email address.')
        if User.objects.filter(email__iexact=value).exists() or User.objects.filter(
            username__iexact=value
        ).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value

    def validate_phone_number(self, value):
        # Same rules as the send forms.
        return SendMessageSerializer().validate_phone_number(value)

    def validate(self, attrs):
        if attrs['password'] != attrs['confirm_password']:
            raise serializers.ValidationError({'confirm_password': ['Passwords do not match.']})
        probe = User(username=attrs['email'], email=attrs['email'])
        try:
            validate_password(attrs['password'], probe)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'password': list(exc.messages)})
        return attrs


class UserListCreateView(APIView):
    permission_classes = [IsSuperUser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'user_admin'

    def get(self, request):
        users = User.objects.filter(is_superuser=True).select_related('profile').order_by('id')
        return Response([describe(u) for u in users])

    def post(self, request):
        serializer = CreateUserSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'error': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = serializer.validated_data
        with transaction.atomic():
            user = User.objects.create_user(
                username=data['email'], email=data['email'], password=data['password'],
            )
            user.is_staff = True
            user.is_superuser = True
            user.save(update_fields=['is_staff', 'is_superuser'])
            UserProfile.objects.create(user=user, phone_number=data['phone_number'])
        return Response({'success': True, 'user': describe(user)}, status=status.HTTP_201_CREATED)


class UserDeleteView(APIView):
    """Remove another super admin. Needs the caller's own password in the body."""

    permission_classes = [IsSuperUser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'admin_delete'

    def delete(self, request, user_id):
        password = str(request.data.get('password', ''))
        if not (password and request.user.check_password(password)):
            return Response(
                {'success': False, 'error': 'Wrong password. Nothing was deleted.'},
                status=status.HTTP_403_FORBIDDEN,  # not 401: the page would log the user out
            )
        target = User.objects.filter(pk=user_id, is_superuser=True).first()
        if not target:
            return Response({'success': False, 'error': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)
        if target.pk == request.user.pk:
            return Response(
                {'success': False, 'error': 'You cannot delete your own account.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        target.delete()  # also removes the profile and API token
        return Response(status=status.HTTP_204_NO_CONTENT)
