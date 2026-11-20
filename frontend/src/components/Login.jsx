import { useState } from 'react';
import { login, resendLoginOtp, verifyLoginOtp } from '../services/api';
import { showError, toastSuccess } from '../services/alerts';
import { OtpStep } from './PasswordSteps';
import { Button, inputClass, Spinner } from './ui';

export default function Login({ onLoggedIn, onForgot, initialEmail = '' }) {
  const [email, setEmail] = useState(initialEmail);
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  // After the password is accepted the server emails a code: { challenge, email_hint, resend_seconds }
  const [pending, setPending] = useState(null);
  const [sentCount, setSentCount] = useState(1); // restarts the resend countdown

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
      if (data.otp_required) {
        setPending(data);
        setSentCount((n) => n + 1);
      } else {
        onLoggedIn(data);
      }
    } catch (err) {
      showError(err.message, 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  const resend = async () => {
    try {
      const res = await resendLoginOtp(pending.challenge);
      if (res.sent) {
        setSentCount((n) => n + 1);
        toastSuccess('A new code was sent');
      } else {
        showError('A code was sent a moment ago. Please wait a minute before asking for another.', 'Please wait');
      }
    } catch (err) {
      showError(err.message, 'Could not send the code');
    }
  };

  const startAgain = () => setPending(null);

  // Second step. With an MPIN set nothing is emailed, but the screen looks like an ordinary code screen and the box
  // takes the MPIN entry (India time + MPIN + 3 digits). Without an MPIN a real 6-digit code is emailed.
  if (pending) {
    const mpinMode = (pending.methods || []).includes('mpin');
    return (
      <div className="flex min-h-dvh items-center justify-center bg-gradient-to-br from-teal-900 to-emerald-700 p-4">
        <div className="w-full max-w-sm rounded-2xl bg-white p-8 shadow-xl">
          <div className="text-center text-4xl">📧</div>
          <h1 className="mt-2 text-center text-2xl font-bold text-teal-800">Check your email</h1>
          <div className="mt-4">
            <OtpStep
              allowLong={mpinMode}
              hint={`Your password is correct. Enter the 6-digit code we emailed to ${pending.email_hint} to finish signing in. It works for 10 minutes.`}
              resendKey={sentCount}
              resendSeconds={pending.resend_seconds || 60}
              onResend={mpinMode ? () => toastSuccess('A new code was sent') : resend}
              extra={
                <button type="button" onClick={startAgain} className="text-slate-500 hover:underline">
                  Start again
                </button>
              }
              onVerify={async (code) => {
                const data = await verifyLoginOtp(pending.challenge, code);
                onLoggedIn(data);
              }}
            />
          </div>
        </div>
      </div>
    );
  }

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
