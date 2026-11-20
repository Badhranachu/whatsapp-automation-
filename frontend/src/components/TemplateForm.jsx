import { useState } from 'react';
import { showError } from '../services/alerts';
import { Button, inputClass, Spinner } from './ui';

// Name + description + submit. Used both for creating and for editing a template.
export default function TemplateForm({ initial, submitLabel, onSubmit, onCancel }) {
  const [name, setName] = useState(initial?.name ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (saving) return;
    if (!name.trim()) {
      showError('Please enter a template name.', 'Missing name');
      return;
    }
    setSaving(true);
    try {
      await onSubmit(name.trim(), description.trim());
    } catch (err) {
      showError(err.message, 'Could not save');
      setSaving(false);
    }
  };

  const id = initial ? `tpl-${initial.id}` : 'tpl-new';
  return (
    <form onSubmit={handleSubmit} noValidate className="rounded-xl bg-slate-50 p-4 ring-1 ring-slate-200">
      <label htmlFor={`${id}-name`} className="mb-1.5 block text-sm font-semibold">
        Name
      </label>
      <input
        id={`${id}-name`}
        type="text"
        maxLength={100}
        value={name}
        onChange={(e) => setName(e.target.value)}
        disabled={saving}
        className={inputClass}
        placeholder="e.g. Welcome message"
        autoFocus
      />
      <label htmlFor={`${id}-desc`} className="mb-1.5 mt-4 block text-sm font-semibold">
        Description <span className="font-normal text-slate-400">(optional)</span>
      </label>
      <textarea
        id={`${id}-desc`}
        rows={4}
        maxLength={1024}
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        disabled={saving}
        className={inputClass}
        placeholder="What is this template for?"
      />
      <div className="mt-4 flex gap-2">
        <Button type="submit" className="flex-1" disabled={saving}>
          {saving ? (
            <>
              <Spinner /> Saving...
            </>
          ) : (
            submitLabel
          )}
        </Button>
        {onCancel && (
          <Button variant="secondary" onClick={onCancel} disabled={saving}>
            Cancel
          </Button>
        )}
      </div>
    </form>
  );
}
