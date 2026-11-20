"""Question flows: each template holds a tree of questions -> options -> questions ..."""

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import audit
from .models import FlowRun, FlowStep, MessageTemplate, Option, Question, add_step

MAX_OPTIONS = 3  # WhatsApp reply buttons: at most 3 per message
MAX_TITLE = 20  # button title limit
MAX_TEXT = 1024  # question text limit
MAX_DEPTH = 50  # guards against absurdly deep trees


def _bad(message, code=status.HTTP_400_BAD_REQUEST):
    return Response({'success': False, 'error': message}, status=code)


def _depth_of(question):
    """1 for the root question, 2 for a question under its option, and so on."""
    depth = 1
    while question.parent_option_id:
        question = question.parent_option.question
        depth += 1
    return depth


def build_flow(template):
    """Return (tree, stats) for a template using two queries, however deep it is."""
    questions = list(Question.objects.filter(template=template))
    options = list(Option.objects.filter(question__template=template))

    options_by_question = {}
    for o in options:
        options_by_question.setdefault(o.question_id, []).append(o)
    question_for_option = {q.parent_option_id: q for q in questions if q.parent_option_id}

    max_depth = 0

    def node(q, depth):
        nonlocal max_depth
        max_depth = max(max_depth, depth)
        return {
            'id': q.id,
            'text': q.text,
            'depth': depth,
            'wants_reply': q.wants_reply,
            'reply_thanks': q.reply_thanks,
            'options': [
                {
                    'id': o.id,
                    'title': o.title,
                    'next': node(question_for_option[o.id], depth + 1)
                    if o.id in question_for_option
                    else None,
                }
                for o in options_by_question.get(q.id, [])
            ],
        }

    root_question = next((q for q in questions if not q.parent_option_id), None)
    root = node(root_question, 1) if root_question else None
    stats = {'questions': len(questions), 'options': len(options), 'depth': max_depth}
    return root, stats


class FlowView(APIView):
    def get(self, request, template_id):
        template = get_object_or_404(MessageTemplate, pk=template_id)
        root, stats = build_flow(template)
        return Response({
            'template': {'id': template.id, 'name': template.name, 'description': template.description},
            'root': root,
            'stats': stats,
        })


def _clean_titles(raw):
    """Validate a list of option titles. Returns (titles, error)."""
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return None, 'Options must be a list.'
    if len(raw) > MAX_OPTIONS:
        return None, f'A question can have at most {MAX_OPTIONS} options (WhatsApp button limit).'
    titles, seen = [], set()
    for item in raw:
        title = str(item).strip()
        if not title:
            return None, 'Every option needs text.'
        if len(title) > MAX_TITLE:
            return None, f'Option text must be {MAX_TITLE} characters or fewer (WhatsApp button limit).'
        if title.casefold() in seen:
            return None, 'Options must be different from each other.'
        seen.add(title.casefold())
        titles.append(title)
    return titles, None


class QuestionCreateView(APIView):
    """Add the first question (no option_id) or a question under an option.

    An optional `options` list creates the question's options in the same request
    (all or nothing).
    """

    def post(self, request, template_id):
        template = get_object_or_404(MessageTemplate, pk=template_id)
        text = str(request.data.get('text', '')).strip()
        if not text:
            return _bad('Question text is required.')
        if len(text) > MAX_TEXT:
            return _bad(f'Question must be {MAX_TEXT} characters or fewer.')
        titles, error = _clean_titles(request.data.get('options'))
        if error:
            return _bad(error)
        try:
            wants, thanks = _reply_fields(request.data, 'Question', bool(titles))
        except ValueError as exc:
            return _bad(str(exc))

        option_id = request.data.get('option_id')
        parent = None
        if option_id in (None, ''):
            if Question.objects.filter(template=template, parent_option__isnull=True).exists():
                return _bad('This template already has a first question.')
        else:
            parent = Option.objects.filter(pk=option_id, question__template=template).first()
            if not parent:
                return _bad('Option not found in this template.', status.HTTP_404_NOT_FOUND)
            if Question.objects.filter(parent_option=parent).exists():
                return _bad('This option already leads to a question.')
            if _depth_of(parent.question) >= MAX_DEPTH:
                return _bad(f'Flows can be at most {MAX_DEPTH} questions deep.')

        with transaction.atomic():
            q = Question.objects.create(
                template=template, text=text, parent_option=parent, wants_reply=wants, reply_thanks=thanks
            )
            for title in titles:
                Option.objects.create(question=q, title=title)
        audit.record(
            request, 'create', 'question', q.id, q.text,
            {'template': template.name, 'options': titles, 'under_option': parent.title if parent else None},
        )
        return Response({'id': q.id, 'text': q.text}, status=status.HTTP_201_CREATED)


MAX_IMPORT_QUESTIONS = 200


def _import_node(template, node, parent, path, counter):
    """Validate one JSON node and create it (and everything below it). Raises ValueError."""
    if not isinstance(node, dict):
        raise ValueError(f'{path}: expected an object with "text".')
    counter[0] += 1
    if counter[0] > MAX_IMPORT_QUESTIONS:
        raise ValueError(f'A flow can have at most {MAX_IMPORT_QUESTIONS} questions.')
    text = str(node.get('text', '')).strip()
    if not text:
        raise ValueError(f'{path}: "text" is required.')
    if len(text) > MAX_TEXT:
        raise ValueError(f'{path}: text must be {MAX_TEXT} characters or fewer.')
    raw_options = node.get('options') or []
    if not isinstance(raw_options, list):
        raise ValueError(f'{path}: "options" must be a list.')
    if len(raw_options) > MAX_OPTIONS:
        raise ValueError(f'{path}: at most {MAX_OPTIONS} options (WhatsApp button limit).')

    wants, thanks = _reply_fields(node, path, bool(raw_options))
    question = Question.objects.create(
        template=template, text=text, parent_option=parent, wants_reply=wants, reply_thanks=thanks
    )
    seen = set()
    for i, raw in enumerate(raw_options, start=1):
        here = f'{path} > option {i}'
        item = raw
        if not isinstance(item, dict):
            raise ValueError(f'{here}: expected an object with "title" and "next".')
        title = str(item.get('title', '')).strip()
        if not title:
            raise ValueError(f'{here}: "title" is required.')
        if len(title) > MAX_TITLE:
            raise ValueError(f'{here}: title must be {MAX_TITLE} characters or fewer.')
        if title.casefold() in seen:
            raise ValueError(f'{here}: duplicate option "{title}".')
        seen.add(title.casefold())
        option = Option.objects.create(question=question, title=title)
        nxt = item.get('next')
        if nxt is None:
            # Every answer must lead somewhere: another question or a closing message.
            raise ValueError(f'{here} "{title}": needs a "next" (a follow-up question or a closing message).')
        # A "next" without options is a closing message (end note).
        _import_node(template, nxt, option, f'{here} "{title}"', counter)


class FlowImportView(APIView):
    """Build a template's whole question flow from nested JSON (all or nothing).

    Body: {"text": "Question", "options": [{"title": "Yes", "next": {"text": "Closing message"}}]}
    A "next" with no options is a closing message. Every option needs a "next". Only works while
    the template has no questions.
    """

    def post(self, request, template_id):
        template = get_object_or_404(MessageTemplate, pk=template_id)
        if Question.objects.filter(template=template).exists():
            return _bad('This template already has questions. Delete them first to import a new flow.')
        try:
            with transaction.atomic():
                _import_node(template, request.data, None, 'First question', [0])
        except ValueError as exc:
            return _bad(str(exc))
        root, stats = build_flow(template)
        audit.record(request, 'import', 'flow', template.id, template.name, stats)
        return Response({'root': root, 'stats': stats}, status=status.HTTP_201_CREATED)


def _reply_fields(raw, path, has_options):
    """Validate "wants_reply" / "reply_thanks" from JSON. Returns (wants_reply, thanks)."""
    wants = raw.get('wants_reply', False)
    if not isinstance(wants, bool):
        raise ValueError(f'{path}: "wants_reply" must be true or false.')
    thanks = str(raw.get('reply_thanks') or '').strip()
    if len(thanks) > MAX_TEXT:
        raise ValueError(f'{path}: "reply_thanks" must be {MAX_TEXT} characters or fewer.')
    if has_options and (wants or thanks):
        raise ValueError(f'{path}: only a closing message (no options) can collect a typed reply.')
    return wants, (thanks if wants else '')


def _node_id(raw, path, what):
    """An optional integer "id" from the JSON, or None."""
    value = raw.get('id')
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f'{path}: {what} "id" must be a number.')
    return value


def _sync_node(template, node, option, path, counter, stats):
    """Apply one question node (and everything below it) to the saved flow.

    A node whose "id" matches the saved item updates it in place; a node (or option) without an
    "id" is created, unless the slot is already filled, in which case the saved item is updated.
    Anything missing from the JSON is left untouched. Raises ValueError on bad input.
    """
    if not isinstance(node, dict):
        raise ValueError(f'{path}: expected an object with "text".')
    counter[0] += 1
    if counter[0] > MAX_IMPORT_QUESTIONS:
        raise ValueError(f'A flow can have at most {MAX_IMPORT_QUESTIONS} questions.')
    text = str(node.get('text', '')).strip()
    if not text:
        raise ValueError(f'{path}: "text" is required.')
    if len(text) > MAX_TEXT:
        raise ValueError(f'{path}: text must be {MAX_TEXT} characters or fewer.')
    raw_options = node.get('options') or []
    if not isinstance(raw_options, list):
        raise ValueError(f'{path}: "options" must be a list.')

    wanted = _node_id(node, path, 'question')
    existing = (
        Question.objects.filter(parent_option=option).first()
        if option
        else Question.objects.filter(template=template, parent_option__isnull=True).first()
    )
    if existing:
        if wanted is not None and wanted != existing.id:
            raise ValueError(f'{path}: question id {wanted} is not the question saved here ({existing.id}).')
        changed = []
        if existing.text != text:
            existing.text = text
            changed.append('text')
        if 'wants_reply' in node or 'reply_thanks' in node:
            wants, thanks = _reply_fields(node, path, bool(raw_options) or existing.options.exists())
            if (existing.wants_reply, existing.reply_thanks) != (wants, thanks):
                existing.wants_reply, existing.reply_thanks = wants, thanks
                changed += ['wants_reply', 'reply_thanks']
        if changed:
            existing.save(update_fields=changed)
            stats['updated_questions'] += 1
        question = existing
    else:
        if wanted is not None:
            raise ValueError(f'{path}: question id {wanted} does not exist here. Remove "id" to add a new question.')
        wants, thanks = _reply_fields(node, path, bool(raw_options))
        question = Question.objects.create(
            template=template, text=text, parent_option=option, wants_reply=wants, reply_thanks=thanks
        )
        stats['created_questions'] += 1

    saved = {o.id: o for o in question.options.all()}
    mentioned = set()
    titles = {}  # option id (or new index) -> final title, to check duplicates and the limit
    parsed = []
    for i, raw in enumerate(raw_options, start=1):
        here = f'{path} > option {i}'
        if not isinstance(raw, dict):
            raise ValueError(f'{here}: expected an object with "title".')
        title = str(raw.get('title', '')).strip()
        if not title:
            raise ValueError(f'{here}: "title" is required.')
        if len(title) > MAX_TITLE:
            raise ValueError(f'{here}: title must be {MAX_TITLE} characters or fewer.')
        oid = _node_id(raw, here, 'option')
        if oid is not None:
            if oid not in saved:
                raise ValueError(f'{here}: option id {oid} does not belong to this question.')
            if oid in mentioned:
                raise ValueError(f'{here}: option id {oid} appears twice.')
            mentioned.add(oid)
        parsed.append((here, oid, title, raw.get('next')))
        titles[oid if oid is not None else f'new{i}'] = title
    for oid, o in saved.items():
        titles.setdefault(oid, o.title)  # options not in the JSON keep their text
    if len(titles) > MAX_OPTIONS:
        raise ValueError(f'{path}: at most {MAX_OPTIONS} options (WhatsApp button limit).')
    folded = [t.casefold() for t in titles.values()]
    if len(set(folded)) != len(folded):
        raise ValueError(f'{path}: options must be different from each other.')

    for here, oid, title, nxt in parsed:
        if oid is None:
            if nxt is None:
                raise ValueError(f'{here} "{title}": needs a "next" (a follow-up question or a closing message).')
            opt = Option.objects.create(question=question, title=title)
            stats['created_options'] += 1
        else:
            opt = saved[oid]
            if opt.title != title:
                opt.title = title
                opt.save(update_fields=['title'])
                stats['updated_options'] += 1
        if nxt is not None:
            _sync_node(template, nxt, opt, f'{here} "{title}"', counter, stats)


class FlowSyncView(APIView):
    """Update a template's flow from JSON that carries the saved "id"s (all or nothing).

    Items with an id are updated in place, items without one are added, and items left out are
    not deleted. Body: the same nested shape the flow JSON box shows.
    """

    def post(self, request, template_id):
        template = get_object_or_404(MessageTemplate, pk=template_id)
        stats = {'created_questions': 0, 'updated_questions': 0, 'created_options': 0, 'updated_options': 0}
        try:
            with transaction.atomic():
                _sync_node(template, request.data, None, 'First question', [0], stats)
        except ValueError as exc:
            return _bad(str(exc))
        root, flow_stats = build_flow(template)
        audit.record(request, 'update', 'flow', template.id, template.name, stats)
        return Response({'root': root, 'stats': flow_stats, 'changes': stats})


def _title_error(question, title, exclude_id=None):
    """Return an error message if `title` is not allowed for an option of `question`."""
    if not title:
        return 'Option text is required.'
    if len(title) > MAX_TITLE:
        return f'Option text must be {MAX_TITLE} characters or fewer (WhatsApp button limit).'
    clash = question.options.filter(title__iexact=title)
    if exclude_id:
        clash = clash.exclude(pk=exclude_id)
    if clash.exists():
        return 'This question already has an option with that text.'
    return None


class OptionCreateView(APIView):
    def post(self, request, question_id):
        question = get_object_or_404(Question, pk=question_id)
        title = str(request.data.get('title', '')).strip()
        if question.options.count() >= MAX_OPTIONS and title:
            return _bad(f'A question can have at most {MAX_OPTIONS} options (WhatsApp button limit).')
        error = _title_error(question, title)
        if error:
            return _bad(error)
        o = Option.objects.create(question=question, title=title)
        audit.record(request, 'create', 'option', o.id, title, {'question': question.text})
        return Response({'id': o.id, 'title': o.title}, status=status.HTTP_201_CREATED)


class QuestionDeleteView(APIView):
    """Edit (PATCH text) or delete a question."""

    def patch(self, request, question_id):
        question = get_object_or_404(Question, pk=question_id)
        before = {'text': question.text, 'wants_reply': question.wants_reply, 'reply_thanks': question.reply_thanks}
        text = str(request.data.get('text', question.text)).strip()
        if not text:
            return _bad('Question text is required.')
        if len(text) > MAX_TEXT:
            return _bad(f'Question must be {MAX_TEXT} characters or fewer.')
        wants, thanks = question.wants_reply, question.reply_thanks
        if 'wants_reply' in request.data or 'reply_thanks' in request.data:
            merged = {'wants_reply': question.wants_reply, 'reply_thanks': question.reply_thanks, **request.data}
            try:
                wants, thanks = _reply_fields(merged, 'Question', question.options.exists())
            except ValueError as exc:
                return _bad(str(exc))
        question.text, question.wants_reply, question.reply_thanks = text, wants, thanks
        question.save(update_fields=['text', 'wants_reply', 'reply_thanks'])
        audit.record(
            request, 'update', 'question', question.id, text,
            audit.diff(before, {'text': text, 'wants_reply': wants, 'reply_thanks': thanks}),
        )
        return Response({
            'id': question.id, 'text': question.text,
            'wants_reply': question.wants_reply, 'reply_thanks': question.reply_thanks,
        })

    def delete(self, request, question_id):
        question = get_object_or_404(Question, pk=question_id)
        audit.record(
            request, 'delete', 'question', question.id, question.text,
            {'template': question.template.name, 'options': [o.title for o in question.options.all()]},
        )
        question.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class OptionDeleteView(APIView):
    """Edit (PATCH title) or delete an option."""

    def patch(self, request, option_id):
        option = get_object_or_404(Option, pk=option_id)
        title = str(request.data.get('title', '')).strip()
        error = _title_error(option.question, title, exclude_id=option.id)
        if error:
            return _bad(error)
        old = option.title
        option.title = title
        option.save(update_fields=['title'])
        audit.record(request, 'update', 'option', option.id, title, audit.diff({'title': old}, {'title': title}))
        return Response({'id': option.id, 'title': option.title})

    def delete(self, request, option_id):
        option = get_object_or_404(Option, pk=option_id)
        audit.record(request, 'delete', 'option', option.id, option.title, {'question': option.question.text})
        option.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


FLOW_BUTTON_PREFIX = 'flow_opt_'


def send_question(to, question, run=None):
    """Send a flow question: reply buttons when it has options, plain text otherwise.

    Logs the message (tagged with its template and run) and, when a run is given, records
    the step and moves the run to this question. Returns the Meta message id.
    """
    from .models import FlowRun, FlowStep, MessageLog, add_step, log_message
    from .services import send_buttons_message, send_text_message

    options = list(question.options.all())
    if options:
        message_id = send_buttons_message(
            to,
            question.text,
            [{'id': f'{FLOW_BUTTON_PREFIX}{o.id}', 'title': o.title} for o in options],
        )
    else:
        message_id = send_text_message(to, question.text)
    log_message(
        MessageLog.OUT, to, 'flow', question.text, message_id,
        template=question.template, flow_run=run,
    )
    if run is not None:
        add_step(
            run, FlowStep.QUESTION_SENT, question=question, text=question.text, wa_message_id=message_id
        )
        run.current_question = question
        run.current_text = question.text
        # A message with no options is an end note: the flow is finished for this person.
        run.status = FlowRun.ACTIVE if options else FlowRun.COMPLETED
        run.save()
    return message_id


MAX_RECIPIENTS = 50


class TemplateSendView(APIView):
    """Send a template's first question (with its options as buttons) to one or more numbers.

    Body: {"phone_numbers": ["+91 98765 43210", ...]} (a single "phone_number" also works).
    Every number is validated first; nothing is sent if any is invalid. Each number is then
    sent separately and gets its own result, so one failure doesn't stop the rest.
    """

    def post(self, request, template_id):
        from .serializers import SendMessageSerializer
        from .services import ConfigurationError, WhatsAppError

        template = get_object_or_404(MessageTemplate, pk=template_id)

        raw = request.data.get('phone_numbers')
        if raw is None:
            raw = [request.data.get('phone_number', '')]
        if not isinstance(raw, list) or not raw:
            return _bad('Add at least one phone number.')
        if len(raw) > MAX_RECIPIENTS:
            return _bad(f'You can send to at most {MAX_RECIPIENTS} numbers at a time.')

        numbers, invalid = [], []
        for item in raw:
            ser = SendMessageSerializer(data={'phone_number': str(item)})
            if ser.is_valid():
                number = ser.validated_data['phone_number']
                if number not in numbers:  # same number typed twice is sent once
                    numbers.append(number)
            else:
                invalid.append(str(item))
        if invalid:
            return Response(
                {
                    'success': False,
                    'message': 'Invalid input.',
                    'error': 'These numbers are not valid: ' + ', '.join(invalid),
                    'invalid': invalid,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        root = Question.objects.filter(template=template, parent_option__isnull=True).first()
        if not root:
            return _bad('This template has no questions yet. Add them in the Questions tab first.')

        results = []
        for number in numbers:
            run = FlowRun.objects.create(
                template=template, template_name=template.name, phone_number=number
            )
            try:
                message_id = send_question(number, root, run)
                results.append(
                    {'phone_number': number, 'success': True, 'message_id': message_id, 'run_id': run.id}
                )
            except (ConfigurationError, WhatsAppError) as exc:
                add_step(run, FlowStep.SEND_FAILED, question=root, text=root.text, detail=str(exc))
                run.status = FlowRun.FAILED
                run.current_question = root
                run.current_text = root.text
                run.save()
                results.append(
                    {'phone_number': number, 'success': False, 'error': str(exc), 'run_id': run.id}
                )
        sent = sum(1 for r in results if r['success'])
        audit.record(
            request, 'send', 'template_send', template.id, template.name,
            {'numbers': numbers, 'sent': sent, 'failed': len(results) - sent},
        )
        return Response({
            'success': sent == len(results),
            'message': f'{sent} of {len(results)} accepted by Meta.',
            'sent': sent,
            'failed': len(results) - sent,
            'results': results,
        })
