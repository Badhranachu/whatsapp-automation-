import { useState } from 'react';
import { login } from '../services/api';
import { showError } from '../services/alerts';
import { Button, inputClass, Spinner } from './ui';

export default function Login({ onLoggedIn, onForgot, initialEmail = '' }) {
  const [email, setEmail] = useState(initialEmail);
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (loading) return;
    if (!email.trim() || !password) {
      showError('Enter your email and password.', 'Missing details');
      return;
    }
    setLoading(true);
    try {
      const data = await login(email.trim(), password);
      onLoggedIn(data);
    } catch (err) {
      showError(err.message, 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-dvh items-center justify-center bg-gradient-to-br from-teal-900 to-emerald-700 p-4">
      <form
        onSubmit={handleSubmit}
        noValidate
        className="w-full max-w-sm rounded-2xl bg-white p-8 shadow-xl"
      >
        <div className="text-center text-4xl">💬</div>
        <h1 className="mt-2 text-center text-2xl font-bold text-teal-800">WhatsApp Messenger</h1>
        <p className="mb-4 mt-1 text-center text-sm text-slate-500">Sign in to continue</p>

        <label htmlFor="email" className="mb-1.5 mt-4 block text-sm font-semibold">
          Email
        </label>
        <input
          id="email"
          type="email"
          autoComplete="username"
          placeholder="you@example.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          disabled={loading}
          className={inputClass}
        />

        <label htmlFor="password" className="mb-1.5 mt-4 block text-sm font-semibold">
          Password
        </label>
        <input
          id="password"
          type="password"
          autoComplete="current-password"
          placeholder="••••••••"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          disabled={loading}
          className={inputClass}
        />

        {/* The link only shows when the page passes onForgot (currently turned off in App.jsx). */}
        {onForgot && (
          <div className="mt-2 text-right">
            <button
              type="button"
              onClick={onForgot}
              disabled={loading}
              className="text-sm font-semibold text-emerald-700 hover:underline"
            >
              Forgot password?
            </button>
          </div>
        )}

        <Button type="submit" className="mt-3 w-full" disabled={loading}>
          {loading ? (
            <>
              <Spinner /> Signing in...
            </>
          ) : (
            'Sign in'
          )}
        </Button>
      </form>
    </div>
  );
}
