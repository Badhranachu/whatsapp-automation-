import { useEffect, useState } from 'react';
import { getMessages, getTemplates } from '../services/api';
import { toastError } from '../services/alerts';
import { Card, inputClass } from './ui';

const POLL_MS = 5000;

const TYPE_LABELS = {
  template: 'Template',
  options: 'Options',
  image: 'Image',
  text: 'Text',
  button_reply: 'Button reply',
  flow: 'Flow question',
};

export const STATUS_LABELS = {
  accepted: '⏳ Accepted by Meta',
  sent: '✓ Sent',
  delivered: '✓✓ Delivered',
  read: '✓✓ Read',
  failed: '✗ Failed',
};

const STATUS_COLORS = {
  failed: 'text-red-700',
  delivered: 'text-emerald-800',
  read: 'text-emerald-800',
};

export function MessageItem({ m }) {
  const incoming = m.direction === 'in';
  return (
    <li
      className={`rounded-lg border-l-4 px-3 py-2.5 ${
        incoming ? 'border-teal-600 bg-teal-50' : 'border-emerald-400 bg-slate-50'
      }`}
    >
      <div className="flex flex-wrap items-center gap-x-2 text-sm">
        <span className="font-bold">{incoming ? '⬇ Received' : '⬆ Sent'}</span>
        <span className="text-slate-500">{TYPE_LABELS[m.message_type] || m.message_type}</span>
        <span className="text-slate-500">+{m.phone_number}</span>
        {m.template && (
          <span className="rounded-full bg-teal-100 px-2 py-0.5 text-xs font-semibold text-teal-800">
            {m.template.name}
          </span>
        )}
      </div>
      <div className="my-1 break-words">{m.content || '—'}</div>
      {!incoming && m.status && (
        <div className={`break-words text-sm font-semibold ${STATUS_COLORS[m.status] || 'text-slate-600'}`}>
          {STATUS_LABELS[m.status] || m.status}
          {m.status_detail ? `: ${m.status_detail}` : ''}
        </div>
      )}
      <div className="text-xs text-slate-500">{new Date(m.created_at).toLocaleString()}</div>
    </li>
  );
}

export default function History() {
  const [rows, setRows] = useState([]);
  const [direction, setDirection] = useState('');
  const [query, setQuery] = useState('');
  const [templateId, setTemplateId] = useState('');
  const [templates, setTemplates] = useState([]);

  useEffect(() => {
    getTemplates()
      .then(setTemplates)
      .catch((err) => toastError(err.message));
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const data = await getMessages({ direction, q: query, template: templateId, limit: 200 });
        if (!cancelled) setRows(data);
      } catch (err) {
        if (!cancelled) toastError(err.message);
      }
    };
    load();
    const timer = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [direction, query, templateId]);

  return (
    <Card className="max-w-3xl">
      <h2 className="text-xl font-bold">Message History</h2>
      <div className="my-3 flex flex-col gap-2 sm:flex-row">
        <select
          value={direction}
          onChange={(e) => setDirection(e.target.value)}
          aria-label="Filter"
          className={`${inputClass} sm:w-48`}
        >
          <option value="">All messages</option>
          <option value="out">Sent</option>
          <option value="in">Received</option>
        </select>
        <select
          value={templateId}
          onChange={(e) => setTemplateId(e.target.value)}
          aria-label="Filter by template"
          className={`${inputClass} sm:w-56`}
        >
          <option value="">All templates</option>
          {templates.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
        <input
          type="search"
          placeholder="Search by phone number"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search by phone number"
          className={inputClass}
        />
      </div>
      {rows.length === 0 && <p className="text-sm text-slate-500">No messages found.</p>}
      <ul className="mt-3 flex flex-col gap-2">
        {rows.map((m) => (
          <MessageItem key={m.id} m={m} />
        ))}
      </ul>
    </Card>
  );
}
