import re

from django.conf import settings

from rest_framework import serializers

from .models import MessageTemplate

E164_RE = re.compile(r'^[1-9]\d{7,14}$')
MAX_MESSAGE_LENGTH = 4096  # WhatsApp text body limit
MAX_CAPTION_LENGTH = 1024  # WhatsApp image caption limit
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # WhatsApp image limit
IMAGE_SIGNATURES = {
    b'\x89PNG\r\n\x1a\n': 'image/png',
    b'\xff\xd8\xff': 'image/jpeg',
}


NATIONAL_LENGTH = 10  # a number typed without country code, e.g. 9876543210


def add_default_country_code(digits):
    """Prefix the configured default country code to a bare 10-digit national number.

    Numbers typed with +, 00 or a country code already are left alone.
    """
    code = str(getattr(settings, 'DEFAULT_COUNTRY_CODE', '') or '').lstrip('+')
    if not code or not digits.isdigit():
        return digits
    if len(digits) == NATIONAL_LENGTH + 1 and digits.startswith('0'):
        digits = digits[1:]  # drop the local trunk zero
    if len(digits) == NATIONAL_LENGTH:
        return code + digits
    return digits


class SendMessageSerializer(serializers.Serializer):
    phone_number = serializers.CharField()
    # Optional. Without an image the template is sent and this is ignored;
    # with an image it becomes the caption.
    message = serializers.CharField(
        max_length=MAX_MESSAGE_LENGTH, required=False, allow_blank=True
    )
    image = serializers.FileField(required=False)

    def validate_phone_number(self, value):
        # Strip common formatting: spaces, dashes, dots, parentheses, leading '+'.
        cleaned = re.sub(r'[\s\-().]', '', value)
        if cleaned.startswith('+'):
            cleaned = cleaned[1:]
        elif cleaned.startswith('00'):
            cleaned = cleaned[2:]
        else:
            cleaned = add_default_country_code(cleaned)
        if not E164_RE.match(cleaned):
            raise serializers.ValidationError(
                'Enter a valid international phone number (E.164), e.g. +919876543210.'
            )
        return cleaned

    def validate_image(self, f):
        if f.size > MAX_IMAGE_BYTES:
            raise serializers.ValidationError('Image must be 5 MB or smaller.')
        head = f.read(8)
        f.seek(0)
        for signature, mime in IMAGE_SIGNATURES.items():
            if head.startswith(signature):
                f.detected_mime = mime  # trust the file contents, not the client's claim
                return f
        raise serializers.ValidationError('Only JPEG or PNG images are supported.')

    def validate(self, attrs):
        if attrs.get('image') and len(attrs.get('message', '')) > MAX_CAPTION_LENGTH:
            raise serializers.ValidationError(
                {'message': f'Caption must be {MAX_CAPTION_LENGTH} characters or fewer.'}
            )
        return attrs


class MessageTemplateSerializer(serializers.ModelSerializer):
    name = serializers.CharField(max_length=100)
    description = serializers.CharField(max_length=1024, required=False, allow_blank=True, default='')
    question_count = serializers.SerializerMethodField()
    run_count = serializers.SerializerMethodField()

    class Meta:
        model = MessageTemplate
        fields = ['id', 'name', 'description', 'question_count', 'run_count', 'created_at']
        read_only_fields = ['id', 'created_at']

    def get_question_count(self, obj):
        return obj.questions.count()

    def get_run_count(self, obj):
        return obj.runs.count()

    def validate_name(self, value):
        return value.strip()

    def validate_description(self, value):
        return value.strip()
