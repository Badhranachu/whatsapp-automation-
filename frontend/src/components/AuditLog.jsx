import { useEffect, useState } from 'react';
import { getAuditLogs } from '../services/api';
import { toastError } from '../services/alerts';
import { Card, inputClass } from './ui';

const ACTION_STYLE = {
  create: 'bg-emerald-100 text-emerald-800',
  update: 'bg-amber-100 text-amber-800',
  delete: 'bg-red-100 text-red-800',
  import: 'bg-violet-100 text-violet-800',
  send: 'bg-sky-100 text-sky-800',
  login: 'bg-slate-100 text-slate-700',
  logout: 'bg-slate-100 text-slate-700',
  login_failed: 'bg-red-100 text-red-800',
};
const ROLE_LABEL = { super_admin: 'Super admin', staff: 'Staff', anonymous: 'Not signed in' };
const ACTIONS = ['create', 'update', 'delete', 'import', 'send', 'login', 'logout', 'login_failed'];
const ENTITIES = ['template', 'question', 'option', 'flow', 'template_send', 'message', 'user', 'session'];

const pretty = (v) => (typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v ?? '—'));

// What changed: "field: old → new" for edits, plain key/value details for everything else.
function Changes({ changes }) {
  const entries = Object.entries(changes || {});
  if (entries.length === 0) return <span className="text-slate-400">—</span>;
  return (
    <ul className="space-y-0.5 text-xs text-slate-600">
      {entries.map(([k, v]) => (
        <li key={k} className="break-words">
          <span className="font-semibold">{k}:</span>{' '}
          {v && typeof v === 'object' && 'from' in v && 'to' in v ? (
            <>
              <span className="text-red-700 line-through">{pretty(v.from)}</span> →{' '}
              <span className="text-emerald-700">{pretty(v.to)}</span>
            </>
          ) : (
            pretty(v)
          )}
        </li>
      ))}
    </ul>
  );
}

export default function AuditLog() {
  const [rows, setRows] = useState([]);
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');
  const [action, setAction] = useState('');
  const [entity, setEntity] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 300);
    return () => clearTimeout(t);
  }, [query]);

  useEffect(() => {
    let cancelled = false;
    getAuditLogs({ q: debounced, action, entity, limit: 200 })
      .then((data) => {
        if (!cancelled) setRows(data);
      })
      .catch((err) => toastError(err.message))
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [debounced, action, entity]);

  return (
    <Card className="max-w-6xl">
      <h2 className="text-xl font-bold">Audit Log</h2>
      <p className="mt-1 text-sm text-slate-500">
        Every create, edit, delete, import, send and login, with who did it and their role. Only super
        admins can see this page.
      </p>
      <div className="mt-4 flex flex-col gap-2 sm:flex-row">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by person or item"
          aria-label="Search by person or item"
          className={inputClass}
        />
        <select value={action} onChange={(e) => setAction(e.target.value)} aria-label="Filter by action" className={`${inputClass} sm:w-44`}>
          <option value="">All actions</option>
          {ACTIONS.map((a) => (
            <option key={a} value={a}>{a.replace('_', ' ')}</option>
          ))}
        </select>
        <select value={entity} onChange={(e) => setEntity(e.target.value)} aria-label="Filter by item type" className={`${inputClass} sm:w-44`}>
          <option value="">All items</option>
          {ENTITIES.map((a) => (
            <option key={a} value={a}>{a.replace('_', ' ')}</option>
          ))}
        </select>
      </div>

      {!loading && rows.length === 0 && <p className="mt-4 text-sm text-slate-500">No activity found.</p>}

      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead className="text-xs uppercase text-slate-400">
            <tr>
              <th className="py-2 pr-3">When</th>
              <th className="py-2 pr-3">Who</th>
              <th className="py-2 pr-3">Action</th>
              <th className="py-2 pr-3">Item</th>
              <th className="py-2">Details</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-t border-slate-100 align-top">
                <td className="whitespace-nowrap py-2 pr-3 text-xs text-slate-500">
                  {new Date(r.created_at).toLocaleString()}
                </td>
                <td className="py-2 pr-3">
                  <div className="break-all font-medium">{r.actor_email || '—'}</div>
                  <div className="text-xs text-slate-400">
                    {ROLE_LABEL[r.actor_role] || r.actor_role}
                    {r.ip_address ? ` · ${r.ip_address}` : ''}
                  </div>
                </td>
                <td className="py-2 pr-3">
                  <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold ${ACTION_STYLE[r.action] || 'bg-slate-100 text-slate-700'}`}>
                    {r.action.replace('_', ' ')}
                  </span>
                </td>
                <td className="py-2 pr-3">
                  <div className="text-xs font-bold uppercase text-slate-400">
                    {r.entity_type.replace('_', ' ')}
                    {r.entity_id ? ` #${r.entity_id}` : ''}
                  </div>
                  <div className="break-words">{r.entity_label}</div>
                </td>
                <td className="py-2">
                  <Changes changes={r.changes} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
