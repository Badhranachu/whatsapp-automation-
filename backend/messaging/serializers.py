import re

from rest_framework import serializers

E164_RE = re.compile(r'^[1-9]\d{7,14}$')
MAX_MESSAGE_LENGTH = 4096  # WhatsApp text body limit


class SendMessageSerializer(serializers.Serializer):
    phone_number = serializers.CharField()
    message = serializers.CharField(max_length=MAX_MESSAGE_LENGTH)

    def validate_phone_number(self, value):
        # Strip common formatting: spaces, dashes, dots, parentheses, leading '+'.
        cleaned = re.sub(r'[\s\-().]', '', value)
        if cleaned.startswith('+'):
            cleaned = cleaned[1:]
        elif cleaned.startswith('00'):
            cleaned = cleaned[2:]
        if not E164_RE.match(cleaned):
            raise serializers.ValidationError(
                'Enter a valid international phone number (E.164), e.g. +919876543210.'
            )
        return cleaned
