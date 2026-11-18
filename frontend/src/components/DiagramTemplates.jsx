import { useEffect, useState } from 'react';
import { getFlow, getRun, getRuns, getTemplates, getTemplateStats } from '../services/api';
import { toastError } from '../services/alerts';
import FlowTree from './FlowTree';
import { STATUS_LABELS } from './History';
import { Button, Card, inputClass } from './ui';

const POLL_MS = 6000;

const RUN_STATUS = {
  active: { label: 'Active', classes: 'bg-sky-100 text-sky-800' },
  completed: { label: 'Completed', classes: 'bg-emerald-100 text-emerald-800' },
  failed: { label: 'Failed', classes: 'bg-red-100 text-red-800' },
};

function StatusBadge({ status }) {
  const s = RUN_STATUS[status] || { label: status, classes: 'bg-slate-100 text-slate-700' };
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold ${s.classes}`}>
      {s.label}
    </span>
  );
}

const when = (iso) => new Date(iso).toLocaleString();

// Reload something now and then; keeps the pages live while people answer.
function usePolling(load, deps, ms = POLL_MS) {
  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      try {
        await load(() => cancelled);
      } catch (err) {
        if (!cancelled) toastError(err.message);
      }
    };
    run();
    const timer = setInterval(run, ms);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}

function SearchBar({ query, onQuery, status, onStatus, placeholder }) {
  return (
    <div className="flex flex-col gap-2 sm:flex-row">
      <input
        type="search"
        value={query}
        onChange={(e) => onQuery(e.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
        className={inputClass}
      />
      <select
        value={status}
        onChange={(e) => onStatus(e.target.value)}
        aria-label="Filter by status"
        className={`${inputClass} sm:w-44`}
      >
        <option value="">All statuses</option>
        <option value="active">Active</option>
        <option value="completed">Completed</option>
        <option value="failed">Failed</option>
      </select>
    </div>
  );
}

function RunRow({ run, onOpen, showTemplate = true }) {
  return (
    <li>
      <button
        type="button"
        onClick={() => onOpen(run.id)}
        className="w-full rounded-xl bg-white p-3 text-left ring-1 ring-slate-200 transition hover:ring-2 hover:ring-emerald-400"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="font-semibold">+{run.phone_number}</span>
          <StatusBadge status={run.status} />
        </div>
        {showTemplate && <div className="mt-0.5 text-sm text-teal-800">{run.template.name}</div>}
        <div className="mt-1 line-clamp-2 break-words text-sm text-slate-600">
          {run.status === 'failed' ? '⚠ Could not be sent: ' : 'At: '}
          {run.current_text || '—'}
        </div>
        <div className="mt-1 text-xs text-slate-400">
          {run.steps ?? 0} step{run.steps === 1 ? '' : 's'} · updated {when(run.updated_at)}
        </div>
      </button>
    </li>
  );
}

// ---------- list: search templates and users ----------

function ListView({ onOpenTemplate, onOpenRun }) {
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('');
  const [templates, setTemplates] = useState([]);
  const [runs, setRuns] = useState([]);
  const [debounced, setDebounced] = useState('');

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 300);
    return () => clearTimeout(t);
  }, [query]);

  usePolling(
    async (isCancelled) => {
      const [t, r] = await Promise.all([getTemplates(), getRuns({ q: debounced, status, limit: 100 })]);
      if (!isCancelled()) {
        setTemplates(t);
        setRuns(r);
      }
    },
    [debounced, status],
  );

  const matchingTemplates = templates.filter((t) =>
    t.name.toLowerCase().includes(debounced.toLowerCase()),
  );

  return (
    <div className="flex max-w-5xl flex-col gap-4">
      <Card>
        <h2 className="text-xl font-bold">Diagram Templates</h2>
        <p className="mt-1 text-sm text-slate-500">
          Search templates and people. Open a template to see how everyone moves through it, or open a
          person to see the exact route they took.
        </p>
        <div className="mt-4">
          <SearchBar
            query={query}
            onQuery={setQuery}
            status={status}
            onStatus={setStatus}
            placeholder="Search template name or phone number"
          />
        </div>
      </Card>

      <Card>
        <h3 className="text-base font-bold">Templates ({matchingTemplates.length})</h3>
        {matchingTemplates.length === 0 && <p className="mt-2 text-sm text-slate-500">No templates match.</p>}
        <ul className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {matchingTemplates.map((t) => (
            <li key={t.id}>
              <button
                type="button"
                onClick={() => onOpenTemplate(t.id)}
                className="h-full w-full rounded-xl bg-white p-4 text-left ring-1 ring-slate-200 transition hover:ring-2 hover:ring-emerald-400"
              >
                <div className="break-words font-semibold">{t.name}</div>
                <div className="mt-1 text-xs font-semibold text-emerald-700">
                  {t.question_count} question{t.question_count === 1 ? '' : 's'} · {t.run_count} send
                  {t.run_count === 1 ? '' : 's'} · Open →
                </div>
              </button>
            </li>
          ))}
        </ul>
      </Card>

      <Card>
        <h3 className="text-base font-bold">People ({runs.length})</h3>
        {runs.length === 0 && (
          <p className="mt-2 text-sm text-slate-500">
            Nothing here yet. Sends from the Template Send page show up here.
          </p>
        )}
        <ul className="mt-3 grid gap-3 md:grid-cols-2">
          {runs.map((r) => (
            <RunRow key={r.id} run={r} onOpen={onOpenRun} />
          ))}
        </ul>
      </Card>
    </div>
  );
}

// ---------- one template: whole diagram with live counts ----------

function TemplateView({ templateId, onBack, onOpenRun }) {
  const [flow, setFlow] = useState(null);
  const [stats, setStats] = useState(null);
  const [runs, setRuns] = useState([]);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('');
  const [debounced, setDebounced] = useState('');

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 300);
    return () => clearTimeout(t);
  }, [query]);

  usePolling(
    async (isCancelled) => {
      const [f, s, r] = await Promise.all([
        getFlow(templateId),
        getTemplateStats(templateId),
        getRuns({ template: templateId, q: debounced, status, limit: 200 }),
      ]);
      if (!isCancelled()) {
        setFlow(f);
        setStats(s);
        setRuns(r);
      }
    },
    [templateId, debounced, status],
  );

  if (!flow) {
    return (
      <Card className="max-w-3xl">
        <Button variant="ghost" className="!px-0" onClick={onBack}>
          ← Back
        </Button>
        <p className="text-sm text-slate-500">Loading...</p>
      </Card>
    );
  }

  const numbers = [
    ['Sends', stats?.runs],
    ['Active', stats?.active],
    ['Completed', stats?.completed],
    ['Failed', stats?.failed],
  ];

  return (
    <div className="flex max-w-7xl flex-col gap-4">
      <Card>
        <Button variant="ghost" className="!px-0" onClick={onBack}>
          ← All
        </Button>
        <h2 className="mt-1 text-xl font-bold">{flow.template.name}</h2>
        <p className="text-sm text-slate-500">{flow.template.description}</p>
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          {numbers.map(([label, value]) => (
            <div key={label} className="rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200">
              <div className="text-2xl font-bold text-teal-700">{value ?? '–'}</div>
              <div className="text-xs text-slate-500">{label}</div>
            </div>
          ))}
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-5">
        <div className="order-2 min-w-0 lg:order-1 lg:col-span-2">
          <Card>
            <h3 className="text-base font-bold">People ({runs.length})</h3>
            <div className="mt-3">
              <SearchBar
                query={query}
                onQuery={setQuery}
                status={status}
                onStatus={setStatus}
                placeholder="Search phone number"
              />
            </div>
            {runs.length === 0 && <p className="mt-3 text-sm text-slate-500">No one has been sent this yet.</p>}
            <ul className="mt-3 flex flex-col gap-2">
              {runs.map((r) => (
                <RunRow key={r.id} run={r} onOpen={onOpenRun} showTemplate={false} />
              ))}
            </ul>
          </Card>
        </div>

        <div className="order-1 min-w-0 lg:order-2 lg:col-span-3">
          <Card>
            <h3 className="text-base font-bold">Flow diagram</h3>
            <p className="mt-1 text-xs text-slate-500">
              Under each question: how many people are there now and how many reached it. On each
              option: how many tapped it.
            </p>
            {flow.root ? (
              <div className="mt-4">
                <FlowTree
                  root={flow.root}
                  currentLabel=""
                  questionNote={(q) => {
                    const here = stats?.users_here?.[q.id] ?? 0;
                    const reached = stats?.reached?.[q.id] ?? 0;
                    return reached || here ? `${here} here · ${reached} reached` : null;
                  }}
                  optionNote={(o) => {
                    const n = stats?.option_taps?.[o.id];
                    return n ? `${n}×` : null;
                  }}
                />
              </div>
            ) : (
              <p className="mt-3 text-sm text-slate-500">This template has no questions yet.</p>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

// ---------- one person: their route, in order ----------

const STEP_INFO = {
  question_sent: { icon: '❓', label: 'Question sent' },
  option_tapped: { icon: '👆', label: 'Tapped option' },
  send_failed: { icon: '⚠️', label: 'Could not send' },
};

function RunView({ runId, onBack }) {
  const [data, setData] = useState(null);

  usePolling(
    async (isCancelled) => {
      const d = await getRun(runId);
      if (!isCancelled()) setData(d);
    },
    [runId],
    5000,
  );

  if (!data) {
    return (
      <Card className="max-w-3xl">
        <Button variant="ghost" className="!px-0" onClick={onBack}>
          ← Back
        </Button>
        <p className="text-sm text-slate-500">Loading...</p>
      </Card>
    );
  }

  const { run, steps, flow, path } = data;
  const finished = run.status !== 'active';

  return (
    <div className="flex max-w-7xl flex-col gap-4">
      <Card>
        <Button variant="ghost" className="!px-0" onClick={onBack}>
          ← Back
        </Button>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <h2 className="text-xl font-bold">+{run.phone_number}</h2>
          <StatusBadge status={run.status} />
        </div>
        <p className="text-sm text-slate-600">
          Template: <span className="font-semibold">{run.template.name}</span>
        </p>
        <p className="text-xs text-slate-400">
          Started {when(run.started_at)} · last activity {when(run.updated_at)}
        </p>
      </Card>

      <div className="grid gap-4 lg:grid-cols-5">
        <div className="order-2 min-w-0 lg:order-1 lg:col-span-2">
          <Card>
            <h3 className="text-base font-bold">Route taken ({steps.length} steps)</h3>
            <ol className="mt-3 flex flex-col gap-2">
              {steps.map((s) => {
                const info = STEP_INFO[s.kind] || { icon: '•', label: s.kind };
                return (
                  <li
                    key={s.order}
                    className={`rounded-lg border-l-4 p-3 ${
                      s.kind === 'send_failed'
                        ? 'border-red-400 bg-red-50'
                        : s.kind === 'option_tapped'
                          ? 'border-teal-600 bg-teal-50'
                          : 'border-emerald-400 bg-slate-50'
                    }`}
                  >
                    <div className="flex flex-wrap items-center gap-2 text-xs font-bold uppercase text-slate-500">
                      <span>{s.order}.</span>
                      <span aria-hidden="true">{info.icon}</span>
                      {info.label}
                    </div>
                    <div className="mt-0.5 break-words font-medium">{s.text || '—'}</div>
                    {s.detail && <div className="mt-0.5 break-words text-sm text-red-700">{s.detail}</div>}
                    {s.delivery_status && (
                      <div className="mt-0.5 text-sm font-semibold text-slate-600">
                        {STATUS_LABELS[s.delivery_status] || s.delivery_status}
                      </div>
                    )}
                    <div className="text-xs text-slate-400">{when(s.created_at)}</div>
                  </li>
                );
              })}
            </ol>
          </Card>
        </div>

        <div className="order-1 min-w-0 lg:order-2 lg:col-span-3">
          <Card>
            <h3 className="text-base font-bold">Flow diagram</h3>
            {flow?.root ? (
              <>
                <p className="mt-1 text-xs text-slate-500">
                  The green route is the path this person took.
                  {finished ? ' The flow has finished for them.' : ' They are waiting at the marked question.'}
                </p>
                <div className="mt-4">
                  <FlowTree
                    root={flow.root}
                    currentId={run.current_question_id}
                    currentLabel={finished ? 'Finished here' : 'You are here'}
                    pathQuestionIds={new Set(path.question_ids)}
                    pathOptionIds={new Set(path.option_ids)}
                  />
                </div>
              </>
            ) : (
              <p className="mt-2 text-sm text-slate-500">
                This template was deleted, so only the recorded steps are shown.
              </p>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

// ---------- page ----------

export default function DiagramTemplates() {
  const [view, setView] = useState({ type: 'list' });

  if (view.type === 'template') {
    return (
      <TemplateView
        templateId={view.id}
        onBack={() => setView({ type: 'list' })}
        onOpenRun={(id) => setView({ type: 'run', id, from: view })}
      />
    );
  }
  if (view.type === 'run') {
    return <RunView runId={view.id} onBack={() => setView(view.from ?? { type: 'list' })} />;
  }
  return (
    <ListView
      onOpenTemplate={(id) => setView({ type: 'template', id })}
      onOpenRun={(id) => setView({ type: 'run', id, from: { type: 'list' } })}
    />
  );
}
