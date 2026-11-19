from django.db import models


class MessageLog(models.Model):
    """History of messages sent by this app and replies received via webhook."""

    OUT = 'out'
    IN = 'in'
    DIRECTION_CHOICES = [(OUT, 'Sent'), (IN, 'Received')]

    direction = models.CharField(max_length=3, choices=DIRECTION_CHOICES)
    phone_number = models.CharField(max_length=20, db_index=True)
    message_type = models.CharField(max_length=30)  # template, options, image, text, button_reply
    content = models.TextField(blank=True)
    wa_message_id = models.CharField(max_length=200, blank=True)
    # Delivery state of sent messages: accepted -> sent -> delivered -> read, or failed.
    status = models.CharField(max_length=20, blank=True)
    status_detail = models.TextField(blank=True)
    # Set for messages that belong to a template send (so History can show / filter by template).
    template = models.ForeignKey(
        'MessageTemplate', null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    flow_run = models.ForeignKey(
        'FlowRun', null=True, blank=True, on_delete=models.SET_NULL, related_name='messages'
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.direction} {self.phone_number} {self.message_type}'


STATUS_RANK = {'accepted': 0, 'sent': 1, 'delivered': 2, 'read': 3}


def update_status(wa_message_id, status, detail=''):
    """Apply a Meta delivery status to a sent message (ignores out-of-order updates)."""
    try:
        row = MessageLog.objects.filter(
            direction=MessageLog.OUT, wa_message_id=wa_message_id
        ).first()
        if not row:
            return
        if status != 'failed':
            if row.status == 'failed' or STATUS_RANK.get(status, -1) <= STATUS_RANK.get(row.status, -1):
                return
        row.status = status
        if detail:
            row.status_detail = detail
        row.save(update_fields=['status', 'status_detail'])
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception('Could not update message status')


def log_message(
    direction, phone_number, message_type, content='', wa_message_id='', template=None, flow_run=None
):
    """Best-effort history write; never lets a DB problem break a send/webhook."""
    try:
        return MessageLog.objects.create(
            template=template,
            flow_run=flow_run,
            direction=direction,
            phone_number=phone_number,
            message_type=message_type,
            content=content,
            wa_message_id=wa_message_id or '',
            status='accepted' if direction == MessageLog.OUT else '',
        )
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception('Could not save message history')
        return None


class MessageTemplate(models.Model):
    """A saved message template (name + description) managed from the website."""

    name = models.CharField(max_length=100)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return self.name


class Question(models.Model):
    """A question in a template's flow.

    The first question has no parent_option. Every other question hangs under
    exactly one option of an earlier question, so flows can nest as deep as needed.
    """

    template = models.ForeignKey(MessageTemplate, on_delete=models.CASCADE, related_name='questions')
    text = models.CharField(max_length=1024)  # WhatsApp interactive body limit
    parent_option = models.OneToOneField(
        'Option', null=True, blank=True, on_delete=models.CASCADE, related_name='next_question'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return self.text[:50]


class Option(models.Model):
    """An answer choice of a question (a WhatsApp reply button)."""

    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='options')
    title = models.CharField(max_length=20)  # WhatsApp button title limit
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return self.title


class FlowRun(models.Model):
    """One template send to one phone number, from the first question to the end.

    The template name and current question text are copied here so the record stays
    readable even if the template is edited or deleted later.
    """

    ACTIVE = 'active'
    COMPLETED = 'completed'
    FAILED = 'failed'
    STATUS_CHOICES = [(ACTIVE, 'Active'), (COMPLETED, 'Completed'), (FAILED, 'Failed')]

    template = models.ForeignKey(
        MessageTemplate, null=True, blank=True, on_delete=models.SET_NULL, related_name='runs'
    )
    template_name = models.CharField(max_length=100)
    phone_number = models.CharField(max_length=20, db_index=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=ACTIVE)
    # Where this person is now (the last question sent to them).
    current_question = models.ForeignKey(
        Question, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    current_text = models.CharField(max_length=1024, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-id']

    def __str__(self):
        return f'{self.template_name} -> {self.phone_number} ({self.status})'


class FlowStep(models.Model):
    """One event in a run, kept in order: question sent, option tapped, or a failure."""

    QUESTION_SENT = 'question_sent'
    OPTION_TAPPED = 'option_tapped'
    SEND_FAILED = 'send_failed'

    run = models.ForeignKey(FlowRun, on_delete=models.CASCADE, related_name='steps')
    order = models.PositiveIntegerField()
    kind = models.CharField(max_length=20)
    question = models.ForeignKey(Question, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    option = models.ForeignKey(Option, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    text = models.TextField(blank=True)  # question text or tapped option title, as it was at the time
    wa_message_id = models.CharField(max_length=200, blank=True)
    detail = models.TextField(blank=True)  # error reason for failed sends
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f'{self.run_id} #{self.order} {self.kind}'


def add_step(run, kind, *, question=None, option=None, text='', wa_message_id='', detail=''):
    """Append a step to a run, numbering it after the existing ones."""
    return FlowStep.objects.create(
        run=run,
        order=run.steps.count() + 1,
        kind=kind,
        question=question,
        option=option,
        text=text,
        wa_message_id=wa_message_id or '',
        detail=detail,
    )


class UserProfile(models.Model):
    """Extra details for a login account (the built-in User has no phone number)."""

    user = models.OneToOneField(
        'auth.User', on_delete=models.CASCADE, related_name='profile'
    )
    phone_number = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return f'Profile of {self.user_id}'
