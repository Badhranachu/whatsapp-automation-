import { useEffect, useState } from 'react';
import { getFlow, getTemplates, sendTemplateFlow } from '../services/api';
import { normalizePhone } from '../services/phone';
import { showError, showSendResults, toastError } from '../services/alerts';
import { Button, Card, inputClass, Spinner } from './ui';

const MAX_RECIPIENTS = 50;

// WhatsApp-style preview of what the recipient will receive.
function Preview({ root }) {
  return (
    <div className="mt-2 max-w-xs rounded-xl bg-[#e7ffdb] p-3 shadow-sm ring-1 ring-emerald-200">
      <p className="break-words text-sm">{root.text}</p>
      {root.options.length > 0 && (
        <div className="mt-2 flex flex-col gap-1.5">
          {root.options.map((o) => (
            <div
              key={o.id}
              className="rounded-lg bg-white px-3 py-1.5 text-center text-sm font-semibold text-sky-700 shadow-sm"
            >
              {o.title}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function TemplateSend() {
  const [templates, setTemplates] = useState([]);
  const [templateId, setTemplateId] = useState('');
  const [root, setRoot] = useState(null); // first question of the chosen template
  const [numbers, setNumbers] = useState([]); // digits only, e.g. "919876543210"
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);

  useEffect(() => {
    getTemplates()
      .then(setTemplates)
      .catch((err) => toastError(err.message));
  }, []);

  // Load the chosen template's first question for the preview.
  useEffect(() => {
    if (!templateId) return undefined;
    let cancelled = false;
    getFlow(templateId)
      .then((flow) => {
        if (!cancelled) setRoot(flow.root);
      })
      .catch((err) => {
        if (!cancelled) toastError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [templateId]);

  const chooseTemplate = (id) => {
    setTemplateId(id);
    setRoot(null);
  };

  // Accepts one number or several separated by commas / new lines (e.g. pasted from a sheet).
  const addNumbers = (text) => {
    const tokens = text.split(/[,;\n]+/).map((t) => t.trim()).filter(Boolean);
    if (tokens.length === 0) return;
    const bad = [];
    const good = [];
    tokens.forEach((t) => {
      const n = normalizePhone(t);
      if (n) good.push(n);
      else bad.push(t);
    });
    const room = MAX_RECIPIENTS - numbers.length;
    const fresh = [...new Set(good)].filter((n) => !numbers.includes(n));
    if (fresh.length > room) {
      showError(`You can send to at most ${MAX_RECIPIENTS} numbers at a time.`, 'Too many numbers');
      return;
    }
    setNumbers((prev) => [...prev, ...fresh]);
    if (bad.length > 0) {
      showError(
        `These are not valid international numbers: ${bad.join(', ')}. Use the country code, e.g. +919876543210.`,
        'Some numbers were skipped',
      );
      setDraft(bad.join(', '));
    } else {
      setDraft('');
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      addNumbers(draft);
    }
  };

  const handlePaste = (e) => {
    const text = e.clipboardData.getData('text');
    if (/[,;\n]/.test(text)) {
      e.preventDefault();
      addNumbers(`${draft} ${text}`.trim());
    }
  };

  const selected = templates.find((t) => String(t.id) === String(templateId));
  const recipientCount = numbers.length + (draft.trim() ? 1 : 0);
  const sendLabel = recipientCount > 1 ? `Send to ${recipientCount} numbers` : 'Send';

  const handleSend = async () => {
    if (sending) return;
    // Anything still typed in the box counts too.
    const pending = draft.trim() ? normalizePhone(draft.trim()) : null;
    if (draft.trim() && !pending) {
      showError(
        'The number in the box is not valid. Use the country code, e.g. +919876543210.',
        'Invalid phone number',
      );
      return;
    }
    const all = pending && !numbers.includes(pending) ? [...numbers, pending] : numbers;
    if (!templateId) {
      showError('Choose a template first.', 'No template selected');
      return;
    }
    if (all.length === 0) {
      showError('Add at least one phone number.', 'No recipients');
      return;
    }
    setSending(true);
    try {
      const data = await sendTemplateFlow(templateId, all);
      await showSendResults(data.message, data.results);
      // Keep only the numbers that failed so they are easy to retry.
      setNumbers(data.results.filter((r) => !r.success).map((r) => r.phone_number));
      setDraft('');
    } catch (err) {
      showError(err.message, 'Not sent');
    } finally {
      setSending(false);
    }
  };

  return (
    <Card className="max-w-2xl">
      <h2 className="text-xl font-bold">Template Send</h2>
      <p className="mt-1 text-sm text-slate-500">
        Choose a template and add one or more numbers. Each person gets the template&apos;s first
        question with its options as buttons; tapping an option sends the next question. Works only
        for people who messaged your number in the last 24 hours.
      </p>

      <label htmlFor="ts-template" className="mb-1.5 mt-5 block text-sm font-semibold">
        Template
      </label>
      <select
        id="ts-template"
        value={templateId}
        onChange={(e) => chooseTemplate(e.target.value)}
        disabled={sending}
        className={inputClass}
      >
        <option value="">Select a template</option>
        {templates.map((t) => (
          <option key={t.id} value={t.id} disabled={t.question_count === 0}>
            {t.name}
            {t.question_count === 0 ? ' (no questions yet)' : ''}
          </option>
        ))}
      </select>

      {selected && root && (
        <div className="mt-3">
          <div className="text-xs font-bold uppercase text-slate-400">What they will receive</div>
          <Preview root={root} />
        </div>
      )}

      <label htmlFor="ts-phone" className="mb-1.5 mt-5 block text-sm font-semibold">
        Phone numbers ({numbers.length})
      </label>
      <div className="flex gap-2">
        <input
          id="ts-phone"
          type="tel"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          placeholder="+91 9876543210, then press Enter"
          disabled={sending}
          autoComplete="off"
          className={inputClass}
        />
        <Button className="shrink-0" disabled={sending || !draft.trim()} onClick={() => addNumbers(draft)}>
          Add
        </Button>
      </div>
      <p className="mt-1 text-xs text-slate-500">
        Press Enter or Add after each number. You can also paste several separated by commas or new
        lines (up to {MAX_RECIPIENTS}).
      </p>

      {numbers.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-2">
          {numbers.map((n) => (
            <li
              key={n}
              className="flex items-center gap-1 rounded-full bg-teal-50 py-1 pl-3 pr-1 text-sm font-medium text-teal-900 ring-1 ring-teal-200"
            >
              +{n}
              <button
                type="button"
                aria-label={`Remove +${n}`}
                disabled={sending}
                onClick={() => setNumbers((prev) => prev.filter((x) => x !== n))}
                className="flex h-6 w-6 items-center justify-center rounded-full text-base leading-none text-teal-700 hover:bg-teal-100 disabled:opacity-50"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-6 flex gap-2">
        <Button className="flex-1" disabled={sending} onClick={handleSend}>
          {sending ? (
            <>
              <Spinner /> Sending...
            </>
          ) : (
            sendLabel
          )}
        </Button>
        <Button
          variant="secondary"
          disabled={sending}
          onClick={() => {
            setNumbers([]);
            setDraft('');
          }}
        >
          Clear
        </Button>
      </div>
    </Card>
  );
}
