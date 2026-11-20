"""Read-only API over saved template sends ("runs") for the Diagram Templates page."""

import csv
from collections import Counter, defaultdict
from datetime import datetime, time

from django.db.models import Count, Q
from django.http import HttpResponse
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from .flows import build_flow
from .models import FlowRun, FlowStep, MessageLog, MessageTemplate

DEFAULT_LIMIT = 200


def _template_ref(run):
    if run.template_id:
        return {'id': run.template_id, 'name': run.template.name}
    return {'id': None, 'name': run.template_name}  # template was deleted


def run_summary(run):
    return {
        'id': run.id,
        'template': _template_ref(run),
        'phone_number': run.phone_number,
        'status': run.status,
        'current_question_id': run.current_question_id,
        'current_text': run.current_text,
        'started_at': run.started_at.isoformat(),
        'updated_at': run.updated_at.isoformat(),
        'steps': getattr(run, 'step_count', None),
    }


def filter_runs(rows, params):
    q = params.get('q', '').strip()
    if q:
        cond = Q(template_name__icontains=q) | Q(template__name__icontains=q)
        digits = ''.join(ch for ch in q if ch.isdigit())
        if digits:
            cond |= Q(phone_number__contains=digits)
        rows = rows.filter(cond)
    template = params.get('template', '')
    if template.isdigit():
        rows = rows.filter(template_id=int(template))
    status = params.get('status', '')
    if status in (FlowRun.ACTIVE, FlowRun.COMPLETED, FlowRun.FAILED):
        rows = rows.filter(status=status)
    start, end = _date_range(params)
    if start:
        rows = rows.filter(started_at__gte=start)
    if end:
        rows = rows.filter(started_at__lte=end)
    return rows


class FlowRunListView(APIView):
    """Saved template sends. Filters: ?q= (phone number or template name), ?template=, ?status="""

    def get(self, request):
        rows = FlowRun.objects.select_related('template').annotate(step_count=Count('steps'))
        rows = filter_runs(rows, request.query_params)
        try:
            limit = min(int(request.query_params.get('limit', DEFAULT_LIMIT)), 500)
        except ValueError:
            limit = DEFAULT_LIMIT
        return Response([run_summary(r) for r in rows[:limit]])


class FlowRunDetailView(APIView):
    """One person's journey: every step in order, plus the template diagram with their path."""

    def get(self, request, run_id):
        run = get_object_or_404(FlowRun.objects.select_related('template'), pk=run_id)
        steps = list(run.steps.all())

        wa_ids = [s.wa_message_id for s in steps if s.wa_message_id]
        delivery = {
            m.wa_message_id: m.status
            for m in MessageLog.objects.filter(direction=MessageLog.OUT, wa_message_id__in=wa_ids)
        }

        flow = None
        if run.template_id:
            root, stats = build_flow(run.template)
            flow = {
                'template': {'id': run.template_id, 'name': run.template.name},
                'root': root,
                'stats': stats,
            }

        return Response({
            'run': run_summary(run),
            'steps': [
                {
                    'order': s.order,
                    'kind': s.kind,
                    'text': s.text,
                    'detail': s.detail,
                    'delivery_status': delivery.get(s.wa_message_id, ''),
                    'question_id': s.question_id,
                    'option_id': s.option_id,
                    'created_at': s.created_at.isoformat(),
                }
                for s in steps
            ],
            'flow': flow,
            'path': {
                # ids that still exist in the template; used to highlight the route taken
                'question_ids': [s.question_id for s in steps if s.question_id],
                'option_ids': [s.option_id for s in steps if s.kind == FlowStep.OPTION_TAPPED and s.option_id],
            },
        })


def _date_range(params):
    """(start, end) datetimes from ?from=YYYY-MM-DD&to=YYYY-MM-DD (inclusive); None when unset/invalid."""
    out = []
    for key, edge in (('from', time.min), ('to', time.max)):
        try:
            day = datetime.strptime(params.get(key, ''), '%Y-%m-%d').date()
            out.append(timezone.make_aware(datetime.combine(day, edge)))
        except ValueError:
            out.append(None)
    return out


def _runs_in_range(template, params):
    runs = FlowRun.objects.filter(template=template)
    start, end = _date_range(params)
    if start:
        runs = runs.filter(started_at__gte=start)
    if end:
        runs = runs.filter(started_at__lte=end)
    return runs


def _flow_nodes(root):
    """Flatten the question tree: [question nodes] plus option id -> (question id, title)."""
    questions, options = [], {}

    def walk(node):
        questions.append(node)
        for o in node['options']:
            options[o['id']] = (node['id'], o['title'])
            if o['next']:
                walk(o['next'])

    if root:
        walk(root)
    return questions, options


class TemplateStatsView(APIView):
    """Per-template numbers for the diagram. Optional ?from= and ?to= (YYYY-MM-DD) limit it to
    sends started in that period.

    Besides the headline counts it returns a funnel per question (reached, answered, drop-off,
    average reply time), how the taps on each question split between its options, sends per
    day and the most common routes people took.
    """

    def get(self, request, template_id):
        template = get_object_or_404(MessageTemplate, pk=template_id)
        runs = _runs_in_range(template, request.query_params)
        steps = list(
            FlowStep.objects.filter(run__in=runs)
            .order_by('run_id', 'order')
            .values('run_id', 'kind', 'question_id', 'option_id', 'text', 'created_at')
        )
        root, _ = build_flow(template)
        questions, option_index = _flow_nodes(root)

        here = Counter(
            runs.filter(status=FlowRun.ACTIVE, current_question__isnull=False)
            .values_list('current_question_id', flat=True)
        )
        taps = Counter(s['option_id'] for s in steps if s['kind'] == FlowStep.OPTION_TAPPED and s['option_id'])
        reached_sets = defaultdict(set)
        answered_sets = defaultdict(set)
        reply_seconds = defaultdict(list)
        routes = Counter()
        by_run = defaultdict(list)
        for s in steps:
            by_run[s['run_id']].append(s)
        for run_id, run_steps in by_run.items():
            sent_at = {}
            route = []
            for s in run_steps:
                if s['kind'] == FlowStep.QUESTION_SENT and s['question_id']:
                    reached_sets[s['question_id']].add(run_id)
                    sent_at[s['question_id']] = s['created_at']
                elif s['kind'] == FlowStep.OPTION_TAPPED and s['option_id']:
                    qid, title = option_index.get(s['option_id'], (None, ''))
                    if qid:
                        answered_sets[qid].add(run_id)
                        if qid in sent_at:
                            reply_seconds[qid].append((s['created_at'] - sent_at[qid]).total_seconds())
                    route.append(s['text'] or title)
            if route:
                routes[' → '.join(route)] += 1

        reply_steps = list(
            FlowStep.objects.filter(run__in=runs, kind=FlowStep.REPLY_RECEIVED)
            .select_related('run', 'question')
            .order_by('-created_at')
        )
        reply_counts = Counter(s.question_id for s in reply_steps)

        funnel = []
        for q in questions:
            reached = len(reached_sets[q['id']])
            answered = len(answered_sets[q['id']])
            q_taps = sum(taps.get(o['id'], 0) for o in q['options'])
            secs = reply_seconds[q['id']]
            answerable = bool(q['options'])  # end notes have nothing to answer
            funnel.append({
                'id': q['id'],
                'text': q['text'],
                'depth': q['depth'],
                'is_end_note': not answerable,
                'wants_reply': q['wants_reply'],
                'replied': reply_counts.get(q['id'], 0),
                'reached': reached,
                'answered': answered,
                'drop_off': max(reached - answered, 0) if answerable else 0,
                'drop_off_pct': round(100 * (reached - answered) / reached, 1) if reached and answerable else 0,
                'avg_reply_seconds': round(sum(secs) / len(secs)) if secs else None,
                'options': [
                    {
                        'id': o['id'],
                        'title': o['title'],
                        'taps': taps.get(o['id'], 0),
                        'share_pct': round(100 * taps.get(o['id'], 0) / q_taps, 1) if q_taps else 0,
                    }
                    for o in q['options']
                ],
            })

        per_day = defaultdict(lambda: {'sends': 0, 'completed': 0, 'failed': 0})
        for started, status in runs.values_list('started_at', 'status'):
            day = timezone.localtime(started).date().isoformat()
            per_day[day]['sends'] += 1
            if status in ('completed', 'failed'):
                per_day[day][status] += 1

        return Response({
            'runs': runs.count(),
            'active': runs.filter(status=FlowRun.ACTIVE).count(),
            'completed': runs.filter(status=FlowRun.COMPLETED).count(),
            'failed': runs.filter(status=FlowRun.FAILED).count(),
            'users_here': {str(k): v for k, v in here.items()},
            'reached': {str(k): len(v) for k, v in reached_sets.items()},
            'option_taps': {str(k): v for k, v in taps.items()},
            'funnel': funnel,
            'timeline': [{'date': d, **v} for d, v in sorted(per_day.items())],
            'top_routes': [{'route': r, 'count': c} for r, c in routes.most_common(5)],
            'replies': [
                {
                    'run_id': s.run_id,
                    'phone_number': s.run.phone_number,
                    'question': s.question.text if s.question else '',
                    'text': s.text,
                    'created_at': s.created_at.isoformat(),
                }
                for s in reply_steps[:200]
            ],
            'reply_total': len(reply_steps),
        })


def _safe_cell(value):
    """Stop spreadsheet apps from running user-supplied text as a formula."""
    text = str(value)
    return "'" + text if text[:1] in ('=', '-', '@') else text


class TemplateExportView(APIView):
    """CSV of every send of a template (same ?from= / ?to= filter as the stats)."""

    def get(self, request, template_id):
        template = get_object_or_404(MessageTemplate, pk=template_id)
        runs = _runs_in_range(template, request.query_params).prefetch_related('steps')
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="template-{template.id}-sends.csv"'
        out = csv.writer(response)
        out.writerow(['phone_number', 'status', 'started_at', 'updated_at', 'current_question', 'answers', 'typed_reply'])
        for r in runs:
            answers = ' | '.join(s.text for s in r.steps.all() if s.kind == FlowStep.OPTION_TAPPED)
            typed = ' | '.join(s.text for s in r.steps.all() if s.kind == FlowStep.REPLY_RECEIVED)
            out.writerow([
                f'+{r.phone_number}', r.status, r.started_at.isoformat(), r.updated_at.isoformat(),
                _safe_cell(r.current_text), _safe_cell(answers), _safe_cell(typed),
            ])
        return response
