import { useEffect, useState } from 'react';
import { createTemplate, deleteTemplate, getTemplates, updateTemplate } from '../services/api';
import { askAdminPassword, showError, toastError, toastSuccess } from '../services/alerts';
import TemplateForm from './TemplateForm';
import { Button, Card, inputClass, KebabMenu } from './ui';

// A labelled value that cannot be edited.
function ReadOnlyField({ label, value, multiline = false }) {
  const shown = value || '—';
  return (
    <div className="mt-0 [&:not(:first-child)]:mt-4">
      <div className="mb-1.5 text-sm font-semibold">{label}</div>
      {multiline ? (
        <textarea readOnly rows={4} value={shown} className={inputClass} />
      ) : (
        <input readOnly value={shown} className={inputClass} />
      )}
    </div>
  );
}

export default function Templates() {
  const [templates, setTemplates] = useState([]);
  const [open, setOpen] = useState(false); // "add" form visible
  const [editingId, setEditingId] = useState(null);
  const [viewingId, setViewingId] = useState(null); // card shown as read-only details
  const [busyId, setBusyId] = useState(null);

  const load = async () => {
    try {
      setTemplates(await getTemplates());
    } catch (err) {
      toastError(err.message);
    }
  };

  useEffect(() => {
    load();
  }, []);

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
    setBusyId(t.id);
    try {
      await deleteTemplate(t.id, password);
      toastSuccess('Template deleted');
      await load();
    } catch (err) {
      showError(err.message, 'Could not delete');
    } finally {
      setBusyId(null);
    }
  };

  return (
    <Card className="max-w-3xl">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-xl font-bold">Templates</h2>
        <button
          type="button"
          onClick={() => {
            setOpen((o) => !o);
            setEditingId(null);
          }}
          aria-label={open ? 'Close template form' : 'Add template'}
          aria-expanded={open}
          className="flex h-10 w-10 items-center justify-center rounded-full bg-emerald-500 text-2xl font-semibold leading-none text-white shadow transition hover:bg-emerald-600"
        >
          <span className={`transition-transform ${open ? 'rotate-45' : ''}`}>+</span>
        </button>
      </div>

      {open && (
        <div className="mt-4">
          <TemplateForm
            submitLabel="Submit"
            onSubmit={async (name, description) => {
              await createTemplate(name, description);
              setOpen(false);
              toastSuccess('Template added');
              await load();
            }}
          />
        </div>
      )}

      {templates.length === 0 && !open && (
        <p className="mt-4 text-sm text-slate-500">No templates yet. Tap + to add one.</p>
      )}

      <ul className="mt-4 grid gap-3 sm:grid-cols-2">
        {templates.map((t) =>
          editingId === t.id ? (
            <li key={t.id} className="sm:col-span-2">
              <TemplateForm
                initial={t}
                submitLabel="Save changes"
                onCancel={() => setEditingId(null)}
                onSubmit={async (name, description) => {
                  await updateTemplate(t.id, name, description);
                  setEditingId(null);
                  toastSuccess('Template updated');
                  await load();
                }}
              />
            </li>
          ) : viewingId === t.id ? (
            <li key={t.id} className="sm:col-span-2">
              <div className="rounded-xl bg-slate-50 p-4 ring-1 ring-slate-200">
                <ReadOnlyField label="Name" value={t.name} />
                <ReadOnlyField label="Description" value={t.description} multiline />
                <div className="mt-4 grid gap-3 sm:grid-cols-3">
                  <ReadOnlyField label="Created" value={new Date(t.created_at).toLocaleString()} />
                  <ReadOnlyField label="Questions" value={String(t.question_count)} />
                  <ReadOnlyField label="Times sent" value={String(t.run_count)} />
                </div>
                <div className="mt-4 flex gap-2">
                  <Button variant="secondary" className="flex-1" onClick={() => setViewingId(null)}>
                    Close
                  </Button>
                </div>
              </div>
            </li>
          ) : (
            <li
              key={t.id}
              role="button"
              tabIndex={0}
              aria-label={`View details of ${t.name}`}
              onClick={() => setViewingId(t.id)}
              onKeyDown={(e) => {
                if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) {
                  e.preventDefault();
                  setViewingId(t.id);
                }
              }}
              className="flex cursor-pointer flex-col rounded-xl bg-white p-4 ring-1 ring-slate-200 transition hover:ring-2 hover:ring-emerald-400"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 break-words font-semibold">{t.name}</div>
                <div onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
                <KebabMenu
                  label={`Actions for ${t.name}`}
                  disabled={busyId === t.id}
                  items={[
                    {
                      label: 'Edit',
                      onClick: () => {
                        setEditingId(t.id);
                        setOpen(false);
                      },
                    },
                    { label: 'Delete', danger: true, onClick: () => handleDelete(t) },
                  ]}
                />
                </div>
              </div>
              <p className="mt-1 flex-1 whitespace-pre-wrap break-words text-sm text-slate-600">
                {t.description || <span className="italic text-slate-400">No description</span>}
              </p>
              <div className="mt-2 text-xs text-slate-400">
                {new Date(t.created_at).toLocaleDateString()} · {t.question_count} question
                {t.question_count === 1 ? '' : 's'}
              </div>
            </li>
          ),
        )}
      </ul>
    </Card>
  );
}
