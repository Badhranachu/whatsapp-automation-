import { useCallback, useEffect, useState } from 'react';
import { createUser, deleteUser, getUsers } from '../services/api';
import { askAdminPassword, showError, toastSuccess } from '../services/alerts';
import { isValidPhone, PHONE_ERROR } from '../services/phone';
import { Button, Card, inputClass, Spinner } from './ui';

const EMPTY = { email: '', phone_number: '', password: '', confirm_password: '' };

export default function UserManagement({ currentEmail }) {
  const [users, setUsers] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      setUsers(await getUsers());
    } catch (err) {
      showError(err.message);
      setUsers([]);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const invalid = (text) => showError(text, 'Check the form');

  const submit = async (e) => {
    e.preventDefault();
    if (saving) return;
    const email = form.email.trim();
    if (!/^\S+@\S+\.\S+$/.test(email)) return invalid('Enter a valid email address.');
    if (!isValidPhone(form.phone_number)) return invalid(PHONE_ERROR);
    if (!form.password) return invalid('Enter a password.');
    if (form.password !== form.confirm_password) return invalid('The two passwords do not match.');
    setSaving(true);
    try {
      await createUser({ ...form, email });
      setForm(EMPTY);
      toastSuccess('Super admin added');
      await load();
    } catch (err) {
      showError(err.message, 'Could not add user');
    } finally {
      setSaving(false);
    }
    return undefined;
  };

  const remove = async (user) => {
    const password = await askAdminPassword({
      title: `Delete ${user.email}?`,
      text: 'They will no longer be able to log in. Enter your own password to confirm.',
    });
    if (!password) return;
    try {
      await deleteUser(user.id, password);
      toastSuccess('User deleted');
      await load();
    } catch (err) {
      showError(err.message, 'Could not delete user');
    }
  };

  const field = (id, label, key, props = {}) => (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-semibold">
        {label}
      </label>
      <input
        id={id}
        value={form[key]}
        onChange={set(key)}
        disabled={saving}
        className={inputClass}
        {...props}
      />
    </div>
  );

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4">
      <Card>
        <h2 className="text-xl font-bold">Add super admin</h2>
        <p className="mt-1 text-sm text-slate-500">
          New super admins can log in with this email and password and have the same access as you.
        </p>
        <form onSubmit={submit} noValidate className="mt-4 grid gap-4 sm:grid-cols-2">
          {field('um-email', 'Email', 'email', { type: 'email', autoComplete: 'off', placeholder: 'name@example.com' })}
          {field('um-phone', 'Phone number', 'phone_number', { type: 'tel', autoComplete: 'off', placeholder: '+919876543210' })}
          {field('um-pass', 'Password', 'password', { type: 'password', autoComplete: 'new-password' })}
          {field('um-confirm', 'Confirm password', 'confirm_password', { type: 'password', autoComplete: 'new-password' })}
          <div className="sm:col-span-2">
            <Button type="submit" disabled={saving}>
              {saving ? (
                <>
                  <Spinner /> Adding...
                </>
              ) : (
                'Add super admin'
              )}
            </Button>
          </div>
        </form>
      </Card>

      <Card>
        <h2 className="text-xl font-bold">Super admins</h2>
        {users === null ? (
          <p className="mt-3 text-sm text-slate-500">Loading...</p>
        ) : (
          <ul className="mt-3 divide-y divide-slate-100">
            {users.map((u) => (
              <li key={u.id} className="flex items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold">
                    {u.email}
                    {u.email === currentEmail && (
                      <span className="ml-2 rounded bg-emerald-100 px-1.5 py-0.5 text-xs text-emerald-800">You</span>
                    )}
                  </div>
                  <div className="text-xs text-slate-500">
                    {u.phone_number ? `+${u.phone_number}` : 'No phone number'} · added{' '}
                    {new Date(u.date_joined).toLocaleDateString()}
                  </div>
                </div>
                {u.email !== currentEmail && (
                  <Button variant="danger" onClick={() => remove(u)}>
                    Delete
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
