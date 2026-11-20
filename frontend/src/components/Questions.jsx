import { useCallback, useEffect, useRef, useState } from 'react';
import {
  addOption,
  addQuestion,
  deleteTemplate,
  deleteOption,
  deleteQuestion,
  getFlow,
  getTemplates,
  importFlow,
  setReplySettings,
  syncFlow,
  updateOption,
  updateQuestion,
} from '../services/api';
import {
  askAdminPassword,
  askDiscardOrContinue,
  confirmAction,
  showError,
  toastError,
  toastSuccess,
} from '../services/alerts';
import { clearDraft, confirmLeave, loadDraft, saveDraft, setDirty } from '../services/unsaved';
import FlowTree from './FlowTree';
import { Button, Card, inputClass, KebabMenu } from './ui';

const MAX_OPTIONS = 3;
const MAX_TITLE = 20;
const draftKey = (templateId) => `wa_flow_draft_${templateId}`;
const clampCount = (n) => Math.min(MAX_OPTIONS, Math.max(1, Number.isFinite(n) ? n : 1));

// ---------- helpers ----------

/** Path from the first question down to `id`: [{ question, via }], via = option taken to get here. */
function findPath(node, id, via = null) {
  if (!node) return null;
  const here = [{ question: node, via }];
  if (node.id === id) return here;
  for (const o of node.options) {
    if (o.next) {
      const sub = findPath(o.next, id, o);
      if (sub) return [...here, ...sub];
    }
  }
  return null;
}

// ---------- forms ----------

// One text field + button. Used to add (clears itself) or to edit (pass `initial` and `onCancel`).
function InlineForm({ placeholder, buttonLabel, maxLength, onSubmit, busy, initial = '', onCancel }) {
  const [value, setValue] = useState(initial);
  const submit = async (e) => {
    e.preventDefault();
    if (!value.trim() || busy) return;
    const ok = await onSubmit(value.trim());
    if (ok && !onCancel) setValue('');
  };
  return (
    <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row">
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={placeholder}
        maxLength={maxLength}
        disabled={busy}
        className={inputClass}
        aria-label={placeholder}
        autoFocus={Boolean(onCancel)}
      />
      <Button type="submit" disabled={busy || !value.trim()} className="shrink-0">
        {buttonLabel}
      </Button>
      {onCancel && (
        <Button variant="secondary" onClick={onCancel} disabled={busy} className="shrink-0">
          Cancel
        </Button>
      )}
    </form>
  );
}

// Question form: asks the question text and how many options, then shows that many option
// fields live. Used for the first question and for sub questions under an option.
// Whatever is typed is kept as a draft, so a reload or closed tab can be resumed or discarded.
function QuestionForm({
  draftKey: key,
  heading,
  questionPlaceholder = 'Type the question',
  submitLabel,
  busy,
  onCreate,
  onCancel,
}) {
  const [text, setText] = useState('');
  const [count, setCount] = useState(2);
  const [options, setOptions] = useState(['', '', '']);
  const [ready, setReady] = useState(false); // false while the "continue or discard?" prompt is open
  const asked = useRef(false);

  const visible = options.slice(0, count);
  const dirty = text.trim() !== '' || visible.some((o) => o.trim() !== '');

  // On first show: offer to restore a draft left behind by a reload / closed tab.
  useEffect(() => {
    if (asked.current) return;
    asked.current = true;
    const draft = loadDraft(key);
    const hasData =
      draft && (String(draft.text ?? '').trim() || (draft.options ?? []).some((o) => String(o ?? '').trim()));
    if (!hasData) {
      setReady(true);
      return;
    }
    askDiscardOrContinue({
      title: 'Unsaved data found',
      text: 'You have unfinished data from before. Do you want to continue with it or discard it?',
      continueText: 'Continue',
      discardText: 'Discard',
    }).then((choice) => {
      if (choice === 'continue') {
        setText(String(draft.text ?? ''));
        setCount(clampCount(Number(draft.count)));
        setOptions(Array.from({ length: MAX_OPTIONS }, (_, i) => String(draft.options?.[i] ?? '')));
      } else {
        clearDraft(key);
      }
      setReady(true);
    });
  }, [key]);

  // Keep the draft in sync with what is typed.
  useEffect(() => {
    if (!ready) return;
    if (dirty) saveDraft(key, { text, count, options });
    else clearDraft(key);
  }, [ready, dirty, key, text, count, options]);

  // Tell the rest of the app there is unsaved data (guards sidebar / back / logout)
  // and let the browser warn on reload or close.
  useEffect(() => {
    if (!dirty) return undefined;
    setDirty(true, () => clearDraft(key));
    const warn = (e) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', warn);
    return () => {
      window.removeEventListener('beforeunload', warn);
      setDirty(false);
    };
  }, [dirty, key]);

  const setOptionAt = (i, value) => setOptions((prev) => prev.map((o, idx) => (idx === i ? value : o)));

  const submit = async (e) => {
    e.preventDefault();
    if (busy || !ready) return;
    if (!text.trim()) {
      showError('Type the question first.', 'Missing question');
      return;
    }
    const titles = visible.map((o) => o.trim());
    if (titles.some((t) => !t)) {
      showError(`Fill in all ${count} option${count === 1 ? '' : 's'}.`, 'Missing options');
      return;
    }
    if (new Set(titles.map((t) => t.toLowerCase())).size !== titles.length) {
      showError('Each option must be different.', 'Duplicate options');
      return;
    }
    const ok = await onCreate(text.trim(), titles);
    if (ok) clearDraft(key);
  };

  return (
    <form onSubmit={submit} noValidate>
      <h3 className="mb-3 text-base font-bold">{heading}</h3>

      <label htmlFor="q-text" className="mb-1.5 block text-sm font-semibold">
        Question
      </label>
      <input
        id="q-text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        maxLength={1024}
        placeholder={questionPlaceholder}
        disabled={busy || !ready}
        className={inputClass}
      />

      <label htmlFor="q-count" className="mb-1.5 mt-4 block text-sm font-semibold">
        How many options? (1–{MAX_OPTIONS})
      </label>
      <div className="flex items-center gap-2">
        <Button
          variant="secondary"
          className="!px-3.5"
          aria-label="Fewer options"
          disabled={busy || !ready || count <= 1}
          onClick={() => setCount((c) => clampCount(c - 1))}
        >
          −
        </Button>
        <input
          id="q-count"
          type="number"
          min={1}
          max={MAX_OPTIONS}
          value={count}
          onChange={(e) => setCount(clampCount(parseInt(e.target.value, 10)))}
          disabled={busy || !ready}
          className={`${inputClass} !w-20 text-center`}
        />
        <Button
          variant="secondary"
          className="!px-3.5"
          aria-label="More options"
          disabled={busy || !ready || count >= MAX_OPTIONS}
          onClick={() => setCount((c) => clampCount(c + 1))}
        >
          +
        </Button>
      </div>

      <div className="mt-4 flex flex-col gap-3">
        {visible.map((value, i) => (
          <div key={i}>
            <label htmlFor={`q-opt-${i}`} className="mb-1.5 block text-sm font-semibold">
              Option {i + 1}
            </label>
            <input
              id={`q-opt-${i}`}
              value={value}
              onChange={(e) => setOptionAt(i, e.target.value)}
              maxLength={MAX_TITLE}
              placeholder={`Text for option ${i + 1}`}
              disabled={busy || !ready}
              className={inputClass}
            />
            <div className="mt-0.5 text-right text-xs text-slate-400">
              {value.length}/{MAX_TITLE}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-4 flex gap-2">
        <Button type="submit" className="flex-1" disabled={busy || !ready}>
          {submitLabel}
        </Button>
        {onCancel && (
          <Button variant="secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
        )}
      </div>
    </form>
  );
}

// Dummy flow shown as a guide. It covers every case:
//  - a question with 3, 2 and 1 option(s)
//  - an option that ends right away with our own closing message ("next" with only "text")
//  - sub questions nested several levels deep (Yes > Daily > Reports > ...)
//  - the longest allowed option title (20 characters) and a closing message with a line break
//  Every option must have a "next": a follow-up question or a closing message.
const EXAMPLE_FLOW = {
  "text": "Do you use our app?",
  "options": [
    {
      "title": "Yes",
      "next": {
        "text": "How often do you use it?",
        "options": [
          {
            "title": "Daily",
            "next": {
              "text": "Which feature do you like most?",
              "options": [
                {
                  "title": "Sending",
                  "next": {
                    "text": "Thanks! Glad you like sending."
                  }
                },
                {
                  "title": "Reports",
                  "next": {
                    "text": "How can we improve reports?",
                    "options": [
                      {
                        "title": "Faster",
                        "next": {
                          "text": "Noted. Speed is our next focus."
                        }
                      },
                      {
                        "title": "Exactly twenty chars",
                        "next": {
                          "text": "Thanks for the detail!"
                        }
                      }
                    ]
                  }
                },
                {
                  "title": "Not sure",
                  "next": {
                    "text": "No worries. Type any suggestion and send it as one message.",
                    "wants_reply": true,
                    "reply_thanks": "Thanks, we saved your suggestion!"
                  }
                }
              ]
            }
          },
          {
            "title": "Weekly",
            "next": {
              "text": "Thanks! We will keep improving it."
            }
          },
          {
            "title": "Rarely",
            "next": {
              "text": "What stops you from using it more?",
              "options": [
                {
                  "title": "Too complex",
                  "next": {
                    "text": "Sorry about that.\nWe will make it simpler."
                  }
                },
                {
                  "title": "No time",
                  "next": {
                    "text": "Understood. Thanks for telling us!"
                  }
                }
              ]
            }
          }
        ]
      }
    },
    {
      "title": "No",
      "next": {
        "text": "No problem. Thanks for your time!"
      }
    },
    {
      "title": "Maybe later",
      "next": {
        "text": "Would you like a reminder next week?",
        "options": [
          {
            "title": "Yes, remind me",
            "next": {
              "text": "Done! We will remind you next week."
            }
          }
        ]
      }
    }
  ]
};

// Paste JSON to create the whole question flow at once instead of adding it step by step.
function JsonImport({ templateId, onImported }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);

  // One tap copies the example JSON; if the browser blocks the clipboard, fill the box instead.
  const copyExample = async () => {
    const example = JSON.stringify(EXAMPLE_FLOW, null, 2);
    try {
      await navigator.clipboard.writeText(example);
      toastSuccess('Example copied');
    } catch {
      setText(example);
    }
  };

  const submit = async () => {
    let parsed;
    try {
      parsed = JSON.parse(text);
    } catch (err) {
      showError(`That is not valid JSON: ${err.message}`, 'Invalid JSON');
      return;
    }
    setBusy(true);
    try {
      await importFlow(templateId, parsed);
      toastSuccess('Flow imported');
      await onImported();
    } catch (err) {
      showError(err.message, 'Could not import');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mb-5 border-b border-slate-100 pb-4">
      <Button variant="ghost" className="!px-0" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        {open ? '− Hide JSON import' : '+ Import flow from JSON'}
      </Button>
      {open && (
        <div className="mt-2">
          <p className="text-xs text-slate-500">
            Paste a nested JSON flow. <code>text</code> is the question. Each option has a{' '}
            <code>title</code> (max {MAX_TITLE} characters, up to {MAX_OPTIONS} options) and an
            <code>next</code>: another question, or just <code>{'{"text": "..."}'}</code>{' '}
            with no options for a closing message. Every option needs a <code>next</code>, so each answer
            ends with a question or your own closing message. Add <code>"wants_reply": true</code> (and
            optionally <code>"reply_thanks"</code>) to a closing message to save the person's next typed
            message. Everything is created together or not
            at all.
          </p>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={12}
            spellCheck={false}
            disabled={busy}
            aria-label="Flow JSON"
            placeholder={JSON.stringify(EXAMPLE_FLOW, null, 2)}
            className={`${inputClass} mt-2 font-mono text-xs`}
          />
          <div className="mt-2 flex flex-wrap gap-2">
            <Button className="flex-1" onClick={submit} disabled={busy || !text.trim()}>
              {busy ? 'Importing...' : 'Import flow'}
            </Button>
            <Button variant="secondary" disabled={busy} onClick={copyExample}>
              Copy example
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

// "Wants a typed reply" switch + optional thank-you text for a closing message.
function ReplyFields({ wants, onWants, thanks, onThanks, disabled }) {
  return (
    <div className="mt-3">
      <label className="flex items-center gap-2 text-sm font-semibold">
        <input
          type="checkbox"
          checked={wants}
          onChange={(e) => onWants(e.target.checked)}
          disabled={disabled}
          className="h-4 w-4 accent-emerald-600"
        />
        Wants a typed reply
      </label>
      <p className="mt-0.5 text-xs text-slate-500">
        The next message the person types is saved with their answers.
      </p>
      {wants && (
        <>
          <label htmlFor="reply-thanks" className="mb-1 mt-2 block text-xs font-semibold">
            Thank-you message (optional)
          </label>
          <input
            id="reply-thanks"
            value={thanks}
            onChange={(e) => onThanks(e.target.value)}
            maxLength={1024}
            disabled={disabled}
            placeholder="Thanks, we saved your suggestion!"
            className={inputClass}
          />
        </>
      )}
    </div>
  );
}

// Creates a closing message, optionally asking for one typed reply.
function EndNoteForm({ busy, onCancel, onSubmit }) {
  const [text, setText] = useState('');
  const [wants, setWants] = useState(false);
  const [thanks, setThanks] = useState('');
  const submit = async (e) => {
    e.preventDefault();
    if (!text.trim() || busy) return;
    await onSubmit(text.trim(), wants, thanks.trim());
  };
  return (
    <form onSubmit={submit} noValidate>
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Type the end note"
        maxLength={1024}
        disabled={busy}
        aria-label="End note text"
        className={inputClass}
        autoFocus
      />
      <ReplyFields wants={wants} onWants={setWants} thanks={thanks} onThanks={setThanks} disabled={busy} />
      <div className="mt-3 flex gap-2">
        <Button type="submit" className="flex-1" disabled={busy || !text.trim()}>
          Save end note
        </Button>
        <Button variant="secondary" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

// Typed-reply settings of the selected closing message.
function ReplySettings({ question, busy, onSave }) {
  const [wants, setWants] = useState(Boolean(question.wants_reply));
  const [thanks, setThanks] = useState(question.reply_thanks || '');
  const changed =
    wants !== Boolean(question.wants_reply) || (wants && thanks.trim() !== (question.reply_thanks || ''));
  return (
    <div className="mt-5 rounded-lg bg-amber-50 p-3 ring-1 ring-amber-200">
      <div className="text-sm font-bold">Closing message</div>
      <ReplyFields wants={wants} onWants={setWants} thanks={thanks} onThanks={setThanks} disabled={busy} />
      <Button className="mt-3" disabled={busy || !changed} onClick={() => onSave(wants, thanks.trim())}>
        Save
      </Button>
    </div>
  );
}

// The saved flow as JSON (ids kept), so it can be copied, edited and saved back.
function flowToJson(node) {
  const out = { id: node.id, text: node.text };
  if (node.wants_reply) {
    out.wants_reply = true;
    if (node.reply_thanks) out.reply_thanks = node.reply_thanks;
  }
  if (node.options.length > 0) {
    out.options = node.options.map((o) => ({
      id: o.id,
      title: o.title,
      ...(o.next ? { next: flowToJson(o.next) } : {}),
    }));
  }
  return out;
}

// Shows the current flow as JSON. Edit, then save: items with an "id" are updated in place,
// items without one are added as new, and items left out are NOT deleted.
function CurrentJson({ templateId, root, onSaved }) {
  const current = JSON.stringify(flowToJson(root), null, 2);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(current);
  const [busy, setBusy] = useState(false);

  // Follow the saved flow while not editing (it changes after every save elsewhere).
  useEffect(() => {
    if (!editing) setText(current);
  }, [current, editing]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(editing ? text : current);
      toastSuccess('JSON copied');
    } catch {
      showError('Your browser blocked copying. Select the text and copy it by hand.', 'Could not copy');
    }
  };

  const save = async () => {
    let parsed;
    try {
      parsed = JSON.parse(text);
    } catch (err) {
      showError(`That is not valid JSON: ${err.message}`, 'Invalid JSON');
      return;
    }
    setBusy(true);
    try {
      const res = await syncFlow(templateId, parsed);
      const c = res.changes;
      const added = c.created_questions + c.created_options;
      const updated = c.updated_questions + c.updated_options;
      toastSuccess(added || updated ? `Saved: ${updated} updated, ${added} added` : 'No changes');
      setEditing(false);
      await onSaved();
    } catch (err) {
      showError(err.message, 'Could not save');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="mt-4">
      <div className="flex items-center justify-between gap-2">
        <Button variant="ghost" className="!px-0" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          {open ? '− Hide flow JSON' : '+ Show flow JSON'}
        </Button>
      </div>
      {open && (
        <div className="mt-2">
          <p className="text-xs text-slate-500">
            This is the whole flow. Keep an <code>id</code> to update that question or option in place; leave
            it out to add a new one. Anything you remove here is <strong>not</strong> deleted. Every new
            option needs a <code>next</code>.
          </p>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            readOnly={!editing}
            rows={14}
            spellCheck={false}
            disabled={busy}
            aria-label="Flow JSON"
            className={`${inputClass} mt-2 font-mono text-xs ${editing ? '' : 'bg-slate-50'}`}
          />
          <div className="mt-2 flex flex-wrap gap-2">
            {editing ? (
              <>
                <Button className="flex-1" onClick={save} disabled={busy || !text.trim()}>
                  {busy ? 'Saving...' : 'Save changes'}
                </Button>
                <Button
                  variant="secondary"
                  disabled={busy}
                  onClick={() => {
                    setEditing(false);
                    setText(current);
                  }}
                >
                  Cancel
                </Button>
              </>
            ) : (
              <Button className="flex-1" onClick={() => setEditing(true)}>
                Edit
              </Button>
            )}
            <Button variant="secondary" disabled={busy} onClick={copy}>
              Copy
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}

// ---------- editor ----------

function FlowEditor({ templateId, onBack }) {
  const [flow, setFlow] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [adding, setAdding] = useState(null); // { id: optionId, mode: 'question' | 'note' }
  const [editingQuestion, setEditingQuestion] = useState(false);
  const [editingOptionId, setEditingOptionId] = useState(null);
  const [showDiagram, setShowDiagram] = useState(false); // the flow diagram is hidden until asked for
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const data = await getFlow(templateId);
    setFlow(data);
    setSelectedId((prev) => {
      const stillThere = prev && findPath(data.root, prev);
      return stillThere ? prev : data.root?.id ?? null;
    });
  }, [templateId]);

  useEffect(() => {
    load().catch((err) => showError(err.message, 'Could not load the flow'));
  }, [load]);

  const select = async (id) => {
    if (!(await confirmLeave())) return; // unsaved data in an open form
    setSelectedId(id);
    setAdding(null);
    setEditingQuestion(false);
    setEditingOptionId(null);
  };

  // Open / close the sub question form of one option (asks first if it has unsaved data).
  const toggleAdding = async (optionId, mode = 'question') => {
    if (!(await confirmLeave())) return;
    setAdding((cur) => (cur?.id === optionId && cur.mode === mode ? null : { id: optionId, mode }));
  };

  // Run a change, then refresh. Returns true on success so forms can clear themselves.
  const run = async (fn, successMessage) => {
    setBusy(true);
    try {
      await fn();
      await load();
      if (successMessage) toastSuccess(successMessage);
      return true;
    } catch (err) {
      showError(err.message);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const goBack = async () => {
    if (await confirmLeave()) onBack();
  };

  if (!flow) {
    return (
      <Card className="max-w-5xl">
        <Button variant="ghost" className="!px-0" onClick={goBack}>
          ← Back
        </Button>
        <p className="text-sm text-slate-500">Loading...</p>
      </Card>
    );
  }

  const path = flow.root && selectedId ? findPath(flow.root, selectedId) : null;
  const selected = path?.[path.length - 1]?.question;

  return (
    <div className="flex max-w-7xl flex-col gap-4">
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Button variant="ghost" className="!px-0" onClick={goBack}>
            ← All templates
          </Button>
        </div>
        <h2 className="mt-1 text-xl font-bold">{flow.template.name}</h2>
        {flow.template.description && (
          <p className="text-sm text-slate-500">{flow.template.description}</p>
        )}
        <div className="mt-3 flex flex-wrap gap-2 text-xs font-semibold">
          <span className="rounded-full bg-slate-100 px-3 py-1">{flow.stats.questions} questions</span>
          <span className="rounded-full bg-slate-100 px-3 py-1">{flow.stats.options} options</span>
          <span className="rounded-full bg-slate-100 px-3 py-1">{flow.stats.depth} levels deep</span>
          <button
            type="button"
            onClick={() => setShowDiagram((v) => !v)}
            aria-expanded={showDiagram}
            className="rounded-full bg-emerald-100 px-3 py-1 text-emerald-800 transition hover:bg-emerald-200"
          >
            {showDiagram ? 'Hide diagram' : 'Show diagram'}
          </button>
        </div>
      </Card>

      <div className={`grid gap-4 ${showDiagram ? 'lg:grid-cols-5' : 'max-w-3xl'}`}>
        <div className={`order-2 min-w-0 lg:order-1 ${showDiagram ? 'lg:col-span-2' : ''}`}>
      {/* Editor */}
      <Card>
        {!flow.root ? (
          <>
            <JsonImport templateId={templateId} onImported={load} />
            <QuestionForm
              draftKey={draftKey(templateId)}
              heading="Add the first question"
              questionPlaceholder="Type the first question"
              submitLabel="Add question"
              busy={busy}
              onCreate={(text, titles) => run(() => addQuestion(templateId, text, null, titles), 'Question added')}
            />
          </>
        ) : selected ? (
          <>
            {path.length > 1 && (
              // Back up one level: to the question whose option led here.
              <Button
                variant="ghost"
                className="mb-2 !px-0 !py-1"
                onClick={() => select(path[path.length - 2].question.id)}
              >
                ← Back to previous question
              </Button>
            )}
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="text-xs font-bold uppercase text-slate-400">
                  Selected question · Level {path.length}
                </div>
                {editingQuestion ? (
                  <div className="mt-2">
                    <InlineForm
                      placeholder="Question text"
                      buttonLabel="Save"
                      maxLength={1024}
                      initial={selected.text}
                      busy={busy}
                      onCancel={() => setEditingQuestion(false)}
                      onSubmit={async (text) => {
                        const ok = await run(() => updateQuestion(selected.id, text), 'Question updated');
                        if (ok) setEditingQuestion(false);
                        return ok;
                      }}
                    />
                  </div>
                ) : (
                  <div className="mt-1 break-words text-lg font-semibold">{selected.text}</div>
                )}
              </div>
              {!editingQuestion && (
                <KebabMenu
                  label="Question actions"
                  disabled={busy}
                  items={[
                    { label: 'Edit', onClick: () => setEditingQuestion(true) },
                    {
                      label: 'Delete',
                      danger: true,
                      onClick: async () => {
                        const ok = await confirmAction({
                          title: 'Delete this question?',
                          text: 'Its options and every follow-up question below it will be deleted too.',
                          confirmText: 'Delete',
                          danger: true,
                        });
                        if (ok) run(() => deleteQuestion(selected.id), 'Question deleted');
                      },
                    },
                  ]}
                />
              )}
            </div>

            {selected.options.length === 0 && selected.depth > 1 && (
              <ReplySettings
                key={`${selected.id}-${selected.wants_reply}-${selected.reply_thanks}`}
                question={selected}
                busy={busy}
                onSave={(wants, thanks) => run(() => setReplySettings(selected.id, wants, thanks), 'Saved')}
              />
            )}

            <h4 className="mb-2 mt-5 text-sm font-bold">
              Options ({selected.options.length}/{MAX_OPTIONS})
            </h4>
            {selected.options.length === 0 && (
              <p className="text-sm text-slate-500">No options yet. Add one below.</p>
            )}
            <ul className="flex flex-col gap-2">
              {selected.options.map((o) => (
                <li key={o.id} className="rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200">
                  {editingOptionId === o.id ? (
                    <InlineForm
                      placeholder={`Option text (max ${MAX_TITLE} characters)`}
                      buttonLabel="Save"
                      maxLength={MAX_TITLE}
                      initial={o.title}
                      busy={busy}
                      onCancel={() => setEditingOptionId(null)}
                      onSubmit={async (title) => {
                        const ok = await run(() => updateOption(o.id, title), 'Option updated');
                        if (ok) setEditingOptionId(null);
                        return ok;
                      }}
                    />
                  ) : (
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="break-words font-semibold text-teal-800">{o.title}</span>
                      <div className="flex shrink-0 flex-wrap items-center gap-2">
                        {o.next ? (
                          <Button variant="ghost" className="!py-1.5" onClick={() => select(o.next.id)}>
                            Go to next →
                          </Button>
                        ) : (
                          <>
                            <Button
                              variant="ghost"
                              className="!py-1.5"
                              onClick={() => toggleAdding(o.id, 'question')}
                            >
                              {adding?.id === o.id && adding.mode === 'question' ? 'Cancel' : '+ Add sub question'}
                            </Button>
                            <Button
                              variant="ghost"
                              className="!py-1.5"
                              onClick={() => toggleAdding(o.id, 'note')}
                            >
                              {adding?.id === o.id && adding.mode === 'note' ? 'Cancel' : 'End note'}
                            </Button>
                          </>
                        )}
                        <KebabMenu
                          label={`Actions for option ${o.title}`}
                          disabled={busy}
                          items={[
                            { label: 'Edit', onClick: () => setEditingOptionId(o.id) },
                            {
                              label: 'Delete',
                              danger: true,
                              onClick: async () => {
                                const ok = await confirmAction({
                                  title: `Delete option "${o.title}"?`,
                                  text: o.next
                                    ? 'The follow-up questions below this option will be deleted too.'
                                    : 'This cannot be undone.',
                                  confirmText: 'Delete',
                                  danger: true,
                                });
                                if (ok) run(() => deleteOption(o.id), 'Option deleted');
                              },
                            },
                          ]}
                        />
                      </div>
                    </div>
                  )}
                  {o.next && editingOptionId !== o.id && (
                    <div className="mt-1 text-sm text-slate-500">→ {o.next.text}</div>
                  )}
                  {!o.next && adding?.id === o.id && adding.mode === 'question' && (
                    <div className="mt-3 rounded-lg bg-white p-4 ring-1 ring-emerald-200">
                      <QuestionForm
                        draftKey={`${draftKey(templateId)}_option_${o.id}`}
                        heading={`Sub question for "${o.title}"`}
                        questionPlaceholder="Type the sub question"
                        submitLabel="Add sub question"
                        busy={busy}
                        onCancel={() => toggleAdding(o.id, 'question')}
                        onCreate={async (text, titles) => {
                          const ok = await run(
                            () => addQuestion(templateId, text, o.id, titles),
                            'Sub question added',
                          );
                          if (ok) setAdding(null);
                          return ok;
                        }}
                      />
                    </div>
                  )}
                  {!o.next && adding?.id === o.id && adding.mode === 'note' && (
                    <div className="mt-3 rounded-lg bg-white p-4 ring-1 ring-amber-200">
                      <h3 className="text-base font-bold">End note for "{o.title}"</h3>
                      <p className="mb-3 mt-1 text-xs text-slate-500">
                        A final message with no options. It is sent as plain text and ends the flow for
                        this answer.
                      </p>
                      <EndNoteForm
                        busy={busy}
                        onCancel={() => toggleAdding(o.id, 'note')}
                        onSubmit={async (text, wants, thanks) => {
                          const extra = wants ? { wants_reply: true, reply_thanks: thanks } : {};
                          const ok = await run(
                            () => addQuestion(templateId, text, o.id, undefined, extra),
                            'End note added',
                          );
                          if (ok) setAdding(null);
                          return ok;
                        }}
                      />
                    </div>
                  )}
                </li>
              ))}
            </ul>

            {selected.options.length < MAX_OPTIONS ? (
              <div className="mt-4">
                <InlineForm
                  placeholder={`New option (max ${MAX_TITLE} characters)`}
                  buttonLabel="Add option"
                  maxLength={MAX_TITLE}
                  busy={busy}
                  onSubmit={(title) => run(() => addOption(selected.id, title), 'Option added')}
                />
              </div>
            ) : (
              <p className="mt-3 text-xs text-slate-500">
                WhatsApp reply buttons allow at most {MAX_OPTIONS} options per question.
              </p>
            )}
          </>
        ) : (
          <p className="text-sm text-slate-500">Select a question to edit it.</p>
        )}
      </Card>
      {flow.root && <CurrentJson templateId={templateId} root={flow.root} onSaved={load} />}
        </div>
        {showDiagram && (
        <div className="order-1 min-w-0 lg:sticky lg:top-4 lg:order-2 lg:col-span-3 lg:max-h-[calc(100vh-2rem)] lg:self-start lg:overflow-auto">
      {/* Diagram */}
      <Card>
        <h3 className="text-base font-bold">Flow diagram</h3>
        {path && (
          <p className="mt-1 text-sm text-slate-600">
            <span className="font-semibold text-emerald-700">You are here:</span> Level {path.length} of{' '}
            {flow.stats.depth} ·{' '}
            {path.map((step, i) => (
              <span key={step.question.id}>
                {i > 0 && <span className="text-slate-400"> › </span>}
                {step.via && <span className="font-semibold text-teal-700">[{step.via.title}] </span>}
                {i === 0 ? 'Start' : `Q${i + 1}`}
              </span>
            ))}
          </p>
        )}
        {flow.root ? (
          <div className="mt-4">
            <FlowTree root={flow.root} currentId={selectedId} onSelect={select} title={flow.template.name} />
          </div>
        ) : (
          <p className="mt-3 text-sm text-slate-500">
            This template has no questions yet. Add the first one below.
          </p>
        )}
      </Card>

        </div>
        )}
      </div>
    </div>
  );
}

// ---------- template list ----------

export default function Questions() {
  const [templates, setTemplates] = useState([]);
  const [openId, setOpenId] = useState(null);
  const [deletingId, setDeletingId] = useState(null);

  const handleDelete = async (t) => {
    const extra =
      t.question_count > 0
        ? ` Its ${t.question_count} question${t.question_count === 1 ? '' : 's'} (with all options) will be deleted too.`
        : '';
    const password = await askAdminPassword({
      title: `Delete "${t.name}"?`,
      text: `This cannot be undone.${extra} Enter the super admin password to confirm.`,
    });
    if (!password) return;
    setDeletingId(t.id);
    try {
      await deleteTemplate(t.id, password);
      toastSuccess('Template deleted');
      setTemplates(await getTemplates());
    } catch (err) {
      showError(err.message, 'Could not delete');
    } finally {
      setDeletingId(null);
    }
  };

  useEffect(() => {
    getTemplates()
      .then(setTemplates)
      .catch((err) => toastError(err.message));
  }, [openId]);

  if (openId !== null) {
    return (
      <FlowEditor
        key={openId} // a different template starts with a clean editor
        templateId={openId}
        onBack={() => setOpenId(null)}
      />
    );
  }

  return (
    <Card className="max-w-3xl">
      <h2 className="text-xl font-bold">Questions</h2>
      <p className="mt-1 text-sm text-slate-500">
        Open a template to build its questions, options and follow-up questions.
      </p>
      {templates.length === 0 && (
        <p className="mt-4 text-sm text-slate-500">
          No templates yet. Create one in the Templates tab first.
        </p>
      )}
      <ul className="mt-4 grid gap-3 sm:grid-cols-2">
        {templates.map((t) => (
          <li
            key={t.id}
            className="flex items-start rounded-xl bg-white ring-1 ring-slate-200 transition hover:ring-2 hover:ring-emerald-400"
          >
            <button type="button" onClick={() => setOpenId(t.id)} className="min-w-0 flex-1 rounded-xl p-4 text-left">
              <div className="break-words font-semibold">{t.name}</div>
              {t.description && (
                <p className="mt-1 line-clamp-2 break-words text-sm text-slate-600">{t.description}</p>
              )}
              <div className="mt-2 text-xs font-semibold text-emerald-700">
                {t.question_count} question{t.question_count === 1 ? '' : 's'} · Open →
              </div>
            </button>
            <div className="p-2">
              <KebabMenu
                label={`Actions for ${t.name}`}
                disabled={deletingId === t.id}
                items={[{ label: 'Delete', danger: true, onClick: () => handleDelete(t) }]}
              />
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}
