import { Button, Card, inputClass } from './ui';

const fmtSeconds = (s) => {
  if (s == null) return '—';
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.round(s / 60)} min`;
  return `${(s / 3600).toFixed(1)} h`;
};

// A horizontal bar whose width is value / max.
function Bar({ value, max, className }) {
  const pct = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0;
  return (
    <div className="h-2.5 w-full rounded-full bg-slate-100">
      <div className={`h-2.5 rounded-full ${className}`} style={{ width: `${value > 0 ? pct : 0}%` }} />
    </div>
  );
}

// Drop-off severity colours the bar: low (green) → high (red).
const dropClass = (pct) => (pct >= 50 ? 'bg-red-500' : pct >= 25 ? 'bg-amber-500' : 'bg-emerald-500');

function Funnel({ funnel }) {
  const top = Math.max(...funnel.map((f) => f.reached), 0);
  return (
    <ol className="mt-3 flex flex-col gap-3">
      {funnel.map((f, i) => (
        <li key={f.id} className="rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div className="min-w-0 break-words text-sm font-semibold">
              <span className="text-slate-400">Q{i + 1}</span> {f.text}
              {f.is_end_note && <span className="ml-2 text-xs font-normal text-amber-700">end note</span>}
              {f.wants_reply && <span className="ml-2 text-xs font-normal text-teal-700">✍ {f.replied} typed repl{f.replied === 1 ? 'y' : 'ies'}</span>}
            </div>
            <div className="text-xs text-slate-500">
              {f.reached} reached
              {!f.is_end_note && ` · ${f.answered} answered · avg reply ${fmtSeconds(f.avg_reply_seconds)}`}
            </div>
          </div>
          <div className="mt-2">
            <Bar value={f.reached} max={top} className="bg-teal-500" />
          </div>
          {!f.is_end_note && f.reached > 0 && (
            <div className="mt-1 text-xs">
              <span className={f.drop_off_pct >= 50 ? 'font-bold text-red-700' : 'text-slate-600'}>
                {f.drop_off} dropped off ({f.drop_off_pct}%)
              </span>
              <span className="ml-1 inline-block align-middle">
                <span className={`inline-block h-2 w-2 rounded-full ${dropClass(f.drop_off_pct)}`} />
              </span>
            </div>
          )}
          {f.options.length > 0 && (
            <ul className="mt-2 flex flex-col gap-1.5">
              {f.options.map((o) => (
                <li key={o.id} className="grid grid-cols-[minmax(0,8rem)_1fr_auto] items-center gap-2 text-xs">
                  <span className="truncate font-semibold text-teal-800" title={o.title}>
                    {o.title}
                  </span>
                  <Bar value={o.share_pct} max={100} className="bg-sky-500" />
                  <span className="text-slate-500">
                    {o.taps}× · {o.share_pct}%
                  </span>
                </li>
              ))}
            </ul>
          )}
        </li>
      ))}
    </ol>
  );
}

function Timeline({ timeline }) {
  const max = Math.max(...timeline.map((d) => d.sends), 0);
  return (
    <div
      className="mt-3 flex h-32 items-end gap-1 overflow-x-auto"
      role="img"
      aria-label="Sends per day"
    >
      {timeline.map((d) => (
        <div key={d.date} className="flex h-full min-w-[1.75rem] flex-1 flex-col justify-end text-center">
          <div className="text-[10px] text-slate-500">{d.sends}</div>
          <div
            className="w-full rounded-t bg-teal-500"
            style={{ height: `${max ? (d.sends / max) * 80 : 0}%` }}
            title={`${d.date}: ${d.sends} sent, ${d.completed} completed, ${d.failed} failed`}
          >
            {d.failed > 0 && (
              <div className="rounded-t bg-red-500" style={{ height: `${(d.failed / d.sends) * 100}%` }} />
            )}
          </div>
          <div className="mt-1 text-[10px] text-slate-400">{d.date.slice(5)}</div>
        </div>
      ))}
    </div>
  );
}

// Data-driven view of one template: funnel and drop-off per question, option popularity,
// sends over time and the most common routes, for an optional date range.
export default function TemplateInsights({ stats, range, onRange, onExport }) {
  if (!stats) return null;
  const hasData = stats.runs > 0;
  const completion = stats.runs ? Math.round((stats.completed / stats.runs) * 100) : 0;

  return (
    <Card>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h3 className="text-base font-bold">Insights</h3>
          <p className="text-xs text-slate-500">
            {stats.runs} send{stats.runs === 1 ? '' : 's'} · {completion}% completed
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs font-semibold">
            From
            <input
              type="date"
              value={range.from}
              max={range.to || undefined}
              onChange={(e) => onRange({ ...range, from: e.target.value })}
              className={`${inputClass} mt-1`}
            />
          </label>
          <label className="text-xs font-semibold">
            To
            <input
              type="date"
              value={range.to}
              min={range.from || undefined}
              onChange={(e) => onRange({ ...range, to: e.target.value })}
              className={`${inputClass} mt-1`}
            />
          </label>
          {(range.from || range.to) && (
            <Button variant="secondary" onClick={() => onRange({ from: '', to: '' })}>
              Clear
            </Button>
          )}
          <Button variant="secondary" onClick={onExport} disabled={!hasData}>
            Export CSV
          </Button>
        </div>
      </div>

      {!hasData ? (
        <p className="mt-3 text-sm text-slate-500">No sends in this period yet.</p>
      ) : (
        <div className="mt-4 grid gap-6 lg:grid-cols-2">
          <div className="min-w-0">
            <h4 className="text-sm font-bold">Funnel and option popularity</h4>
            <Funnel funnel={stats.funnel} />
          </div>
          <div className="min-w-0">
            <h4 className="text-sm font-bold">Sends per day</h4>
            <Timeline timeline={stats.timeline} />
            <h4 className="mt-6 text-sm font-bold">Most common routes</h4>
            {stats.top_routes.length === 0 ? (
              <p className="mt-2 text-sm text-slate-500">Nobody has answered yet.</p>
            ) : (
              <ol className="mt-2 flex flex-col gap-1.5 text-sm">
                {stats.top_routes.map((r) => (
                  <li key={r.route} className="flex justify-between gap-3 rounded-lg bg-slate-50 px-3 py-2 ring-1 ring-slate-200">
                    <span className="min-w-0 break-words">{r.route}</span>
                    <span className="shrink-0 font-semibold text-teal-700">{r.count}×</span>
                  </li>
                ))}
              </ol>
            )}
          </div>
        </div>
      )}

      {hasData && (stats.reply_total > 0 || stats.funnel.some((f) => f.wants_reply)) && (
        <div className="mt-6">
          <h4 className="text-sm font-bold">Typed replies ({stats.reply_total})</h4>
          {stats.replies.length === 0 ? (
            <p className="mt-2 text-sm text-slate-500">Nobody has typed a reply yet.</p>
          ) : (
            <ul className="mt-2 flex flex-col gap-2">
              {stats.replies.map((r, i) => (
                <li key={`${r.run_id}-${i}`} className="rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200">
                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
                    <span className="font-semibold text-slate-700">+{r.phone_number}</span>
                    <span>{new Date(r.created_at).toLocaleString()}</span>
                  </div>
                  <p className="mt-1 whitespace-pre-wrap break-words text-sm">{r.text}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}
