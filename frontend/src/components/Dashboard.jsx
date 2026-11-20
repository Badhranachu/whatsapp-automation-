import { useEffect, useState } from 'react';
import { getMessages, getStats } from '../services/api';
import { toastError } from '../services/alerts';
import { MessageItem } from './History';
import { Button, Card } from './ui';

export default function Dashboard({ onNavigate }) {
  const [stats, setStats] = useState(null);
  const [recent, setRecent] = useState([]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [s, r] = await Promise.all([getStats(), getMessages({ limit: 5 })]);
        if (!cancelled) {
          setStats(s);
          setRecent(r);
        }
      } catch (err) {
        if (!cancelled) toastError(err.message);
      }
    };
    load();
    const timer = setInterval(load, 10000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  const cards = [
    { label: 'Messages sent', value: stats?.sent_total },
    { label: 'Delivered', value: stats?.delivered },
    { label: 'Failed', value: stats?.failed },
    { label: 'Replies received', value: stats?.received },
  ];

  return (
    <Card className="max-w-3xl">
      <h2 className="text-xl font-bold">Dashboard</h2>
      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {cards.map((c) => (
          <div key={c.label} className="rounded-xl bg-slate-50 p-4 ring-1 ring-slate-200">
            <div className="text-3xl font-bold text-teal-700">{c.value ?? '–'}</div>
            <div className="text-sm text-slate-500">{c.label}</div>
          </div>
        ))}
      </div>

      <div className="mt-5 flex flex-wrap gap-2">
        <Button onClick={() => onNavigate('template')}>Send Message</Button>
        <Button variant="secondary" onClick={() => onNavigate('questions')}>
          Build Questions
        </Button>
      </div>

      <h3 className="mb-2 mt-7 text-base font-bold">Recent activity</h3>
      {recent.length === 0 && <p className="text-sm text-slate-500">Nothing yet.</p>}
      <ul className="flex flex-col gap-2">
        {recent.map((m) => (
          <MessageItem key={m.id} m={m} />
        ))}
      </ul>
      {recent.length > 0 && (
        <Button variant="ghost" className="mt-2 !px-0" onClick={() => onNavigate('history')}>
          View full history →
        </Button>
      )}
    </Card>
  );
}
