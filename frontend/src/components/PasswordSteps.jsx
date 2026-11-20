import { useEffect, useState } from 'react';
import { showError } from '../services/alerts';
import { Button, inputClass, Spinner } from './ui';

// Counts down from `seconds` (restarts whenever `startKey` changes). Used for "Resend code".
export function useCountdown(seconds, startKey) {
  const [left, setLeft] = useState(0);
  useEffect(() => {
    if (!startKey) return undefined;
    setLeft(seconds);
    const timer = setInterval(() => setLeft((s) => (s <= 1 ? (clearInterval(timer), 0) : s - 1)), 1000);
    return () => clearInterval(timer);
  }, [seconds, startKey]);
  return left;
}

// The 6-digit code box + Verify + Resend. Shared by "forgot password" and "change password".
export function OtpStep({ sentTo, hint, onVerify, onResend, resendKey, resendSeconds = 60, extra }) {
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const left = useCountdown(resendSeconds, resendKey);

  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;
    if (!/^\d{6}$/.test(code)) {
      showError('Enter the 6-digit code from the email.', 'Check the code');
      return;
    }
    setBusy(true);
    try {
      await onVerify(code);
    } catch (err) {
      showError(err.message, 'Could not verify');
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} noValidate>
      <p className="text-sm text-slate-600">{hint || `Enter the 6-digit code we sent to ${sentTo}.`}</p>
      <label htmlFor="otp" className="mb-1.5 mt-4 block text-sm font-semibold">
        Code
      </label>
      <input
        id="otp"
        inputMode="numeric"
        autoComplete="one-time-code"
        maxLength={6}
        value={code}
        onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
        placeholder="123456"
        disabled={busy}
        autoFocus
        className={`${inputClass} text-center text-lg tracking-[0.4em]`}
      />
      <Button type="submit" className="mt-4 w-full" disabled={busy || code.length !== 6}>
        {busy ? (
          <>
            <Spinner /> Checking...
          </>
        ) : (
          'Verify code'
        )}
      </Button>
      <div className="mt-3 flex items-center justify-between text-sm">
        <button
          type="button"
          onClick={onResend}
          disabled={left > 0 || busy}
          className="font-semibold text-emerald-700 hover:underline disabled:cursor-not-allowed disabled:text-slate-400 disabled:no-underline"
        >
          {left > 0 ? `Resend code in ${left}s` : 'Resend code'}
        </button>
        {extra}
      </div>
    </form>
  );
}

// New password + confirm. `onSubmit(password, confirm)` should throw on failure.
export function NewPasswordStep({ submitLabel, onSubmit }) {
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;
    if (!password || !confirm) {
      showError('Fill in both password fields.', 'Missing details');
      return;
    }
    if (password !== confirm) {
      showError('The two passwords do not match.', 'Passwords differ');
      return;
    }
    setBusy(true);
    try {
      await onSubmit(password, confirm);
    } catch (err) {
      showError(err.message, 'Could not update the password');
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} noValidate>
      <label htmlFor="new-password" className="mb-1.5 block text-sm font-semibold">
        New password
      </label>
      <input
        id="new-password"
        type="password"
        autoComplete="new-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        disabled={busy}
        autoFocus
        className={inputClass}
      />
      <label htmlFor="confirm-password" className="mb-1.5 mt-4 block text-sm font-semibold">
        Confirm password
      </label>
      <input
        id="confirm-password"
        type="password"
        autoComplete="new-password"
        value={confirm}
        onChange={(e) => setConfirm(e.target.value)}
        disabled={busy}
        className={inputClass}
      />
      <p className="mt-1 text-xs text-slate-500">
        At least 8 characters, and not a common password or only numbers.
      </p>
      <Button type="submit" className="mt-4 w-full" disabled={busy}>
        {busy ? (
          <>
            <Spinner /> Saving...
          </>
        ) : (
          submitLabel
        )}
      </Button>
    </form>
  );
}
