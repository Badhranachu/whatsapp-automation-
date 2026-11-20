import { useState } from 'react';
import { requestResetOtp, resetPassword, verifyResetOtp } from '../services/api';
import { showError, toastSuccess } from '../services/alerts';
import { NewPasswordStep, OtpStep } from './PasswordSteps';
import { Button, inputClass, Spinner } from './ui';

const STEP_TITLES = {
  email: 'Forgot your password?',
  otp: 'Check your email',
  password: 'Set a new password',
};

// Email -> 6-digit code -> new password -> back to the login form.
export default function ForgotPassword({ onBack, onDone }) {
  const [step, setStep] = useState('email');
  const [email, setEmail] = useState('');
  const [sending, setSending] = useState(false);
  const [sentCount, setSentCount] = useState(0); // restarts the resend countdown
  const [resetToken, setResetToken] = useState('');

  const sendCode = async () => {
    const address = email.trim();
    if (!address) {
      showError('Enter your email address.', 'Missing email');
      return;
    }
    setSending(true);
    try {
      await requestResetOtp(address);
      setSentCount((n) => n + 1);
      setStep('otp');
    } catch (err) {
      showError(err.message, 'Could not send the code');
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="flex min-h-dvh items-center justify-center bg-gradient-to-br from-teal-900 to-emerald-700 p-4">
      <div className="w-full max-w-sm rounded-2xl bg-white p-8 shadow-xl">
        <div className="text-center text-4xl">🔑</div>
        <h1 className="mt-2 text-center text-2xl font-bold text-teal-800">{STEP_TITLES[step]}</h1>

        <div className="mt-5">
          {step === 'email' && (
            <form
              noValidate
              onSubmit={(e) => {
                e.preventDefault();
                if (!sending) sendCode();
              }}
            >
              <p className="text-sm text-slate-500">
                Enter your admin email. We will email you a 6-digit code to reset your password.
              </p>
              <label htmlFor="fp-email" className="mb-1.5 mt-4 block text-sm font-semibold">
                Email
              </label>
              <input
                id="fp-email"
                type="email"
                autoComplete="username"
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={sending}
                autoFocus
                className={inputClass}
              />
              <Button type="submit" className="mt-4 w-full" disabled={sending}>
                {sending ? (
                  <>
                    <Spinner /> Sending...
                  </>
                ) : (
                  'Send OTP'
                )}
              </Button>
            </form>
          )}

          {step === 'otp' && (
            <OtpStep
              hint={`If ${email.trim()} belongs to an admin account, a 6-digit code has been sent to it. It works for 10 minutes.`}
              resendKey={sentCount}
              onResend={sendCode}
              extra={
                <button type="button" onClick={() => setStep('email')} className="text-slate-500 hover:underline">
                  Change email
                </button>
              }
              onVerify={async (code) => {
                const res = await verifyResetOtp(email.trim(), code);
                setResetToken(res.reset_token);
                setStep('password');
              }}
            />
          )}

          {step === 'password' && (
            <NewPasswordStep
              submitLabel="Update password"
              onSubmit={async (password, confirm) => {
                await resetPassword({
                  email: email.trim(),
                  reset_token: resetToken,
                  password,
                  confirm_password: confirm,
                });
                toastSuccess('Password updated. Please sign in.');
                onDone(email.trim());
              }}
            />
          )}
        </div>

        <button
          type="button"
          onClick={onBack}
          className="mt-5 block w-full text-center text-sm font-semibold text-emerald-700 hover:underline"
        >
          ← Back to sign in
        </button>
      </div>
    </div>
  );
}
