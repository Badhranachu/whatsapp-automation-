import { useEffect, useRef, useState } from 'react';
import {
  changePassword,
  getAvatarUrl,
  getProfile,
  removeAvatar,
  sendPasswordOtp,
  updateProfile,
  uploadAvatar,
  verifyPasswordOtp,
} from '../services/api';
import { confirmAction, showError, toastError, toastSuccess } from '../services/alerts';
import { setDirty } from '../services/unsaved';
import { NewPasswordStep, OtpStep } from './PasswordSteps';
import { Button, Card, inputClass, Spinner } from './ui';

const MAX_AVATAR = 2 * 1024 * 1024;

const maskEmail = (email) => {
  const [user = '', domain = ''] = String(email).split('@');
  return `${user.slice(0, 2)}${'*'.repeat(Math.max(1, user.length - 2))}@${domain}`;
};

function Avatar({ url, label }) {
  return url ? (
    <img src={url} alt="Your profile" className="h-24 w-24 rounded-full object-cover ring-2 ring-emerald-200" />
  ) : (
    <div
      aria-hidden="true"
      className="flex h-24 w-24 items-center justify-center rounded-full bg-emerald-100 text-3xl font-bold text-emerald-700"
    >
      {(label || '?').slice(0, 1).toUpperCase()}
    </div>
  );
}

function PasswordChange({ email }) {
  const [step, setStep] = useState('idle'); // idle | otp | password
  const [busy, setBusy] = useState(false);
  const [sentCount, setSentCount] = useState(0);
  const [resetToken, setResetToken] = useState('');

  const sendCode = async () => {
    setBusy(true);
    try {
      await sendPasswordOtp();
      setSentCount((n) => n + 1);
      setStep('otp');
    } catch (err) {
      showError(err.message, 'Could not send the code');
    } finally {
      setBusy(false);
    }
  };

  const cancel = () => {
    setStep('idle');
    setResetToken('');
  };

  return (
    <Card className="mt-4">
      <h3 className="text-base font-bold">Password</h3>
      {step === 'idle' && (
        <>
          <p className="mt-1 text-sm text-slate-500">
            To change it, we first email a 6-digit code to {maskEmail(email)}.
          </p>
          <Button className="mt-3" onClick={sendCode} disabled={busy}>
            {busy ? (
              <>
                <Spinner /> Sending...
              </>
            ) : (
              'Change password'
            )}
          </Button>
        </>
      )}
      {step === 'otp' && (
        <div className="mt-3 max-w-sm">
          <OtpStep
            sentTo={maskEmail(email)}
            resendKey={sentCount}
            onResend={sendCode}
            extra={
              <button type="button" onClick={cancel} className="text-slate-500 hover:underline">
                Cancel
              </button>
            }
            onVerify={async (code) => {
              const res = await verifyPasswordOtp(code);
              setResetToken(res.reset_token);
              setStep('password');
            }}
          />
        </div>
      )}
      {step === 'password' && (
        <div className="mt-3 max-w-sm">
          <NewPasswordStep
            submitLabel="Update password"
            onSubmit={async (password, confirm) => {
              await changePassword({ reset_token: resetToken, password, confirm_password: confirm });
              toastSuccess('Password changed. Other devices were signed out.');
              cancel();
            }}
          />
          <button type="button" onClick={cancel} className="mt-3 text-sm text-slate-500 hover:underline">
            Cancel
          </button>
        </div>
      )}
    </Card>
  );
}

export default function Profile() {
  const [profile, setProfile] = useState(null);
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [saving, setSaving] = useState(false);
  const [avatarUrl, setAvatarUrl] = useState(null);
  const [photoBusy, setPhotoBusy] = useState(false);
  const fileInput = useRef(null);

  const apply = async (p) => {
    setProfile(p);
    setName(p.name);
    setPhone(p.phone_number);
    const url = p.has_avatar ? await getAvatarUrl() : null;
    setAvatarUrl((old) => {
      if (old) URL.revokeObjectURL(old);
      return url;
    });
  };

  // After a photo change only the picture is refreshed, so unsaved name / phone edits stay put.
  const applyPhoto = async (p) => {
    setProfile((prev) => ({ ...prev, has_avatar: p.has_avatar, avatar_version: p.avatar_version }));
    const url = p.has_avatar ? await getAvatarUrl() : null;
    setAvatarUrl((old) => {
      if (old) URL.revokeObjectURL(old);
      return url;
    });
  };

  useEffect(() => {
    getProfile()
      .then(apply)
      .catch((err) => toastError(err.message));
    return () => setAvatarUrl((old) => (old && URL.revokeObjectURL(old), null));
  }, []);

  // Warn before leaving the page with unsaved name / phone edits.
  const dirty = Boolean(profile) && (name !== profile.name || phone !== profile.phone_number);
  useEffect(() => {
    setDirty(dirty, () => {
      setName(profile?.name ?? '');
      setPhone(profile?.phone_number ?? '');
    });
    return () => setDirty(false);
  }, [dirty, profile]);

  const save = async (e) => {
    e.preventDefault();
    if (saving || !dirty) return;
    setSaving(true);
    try {
      const res = await updateProfile({ name, phone_number: phone });
      await apply(res.profile);
      toastSuccess('Profile saved');
    } catch (err) {
      showError(err.message, 'Could not save');
    } finally {
      setSaving(false);
    }
  };

  const pickPhoto = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    if (!['image/png', 'image/jpeg'].includes(file.type)) {
      showError('Use a PNG or JPEG picture.', 'Wrong file type');
      return;
    }
    if (file.size > MAX_AVATAR) {
      showError('The picture must be 2 MB or smaller.', 'Picture too big');
      return;
    }
    setPhotoBusy(true);
    try {
      const res = await uploadAvatar(file);
      await applyPhoto(res.profile);
      toastSuccess('Photo updated');
    } catch (err) {
      showError(err.message, 'Could not upload');
    } finally {
      setPhotoBusy(false);
    }
  };

  const dropPhoto = async () => {
    if (!(await confirmAction({ title: 'Remove your photo?', confirmText: 'Remove', danger: true }))) return;
    setPhotoBusy(true);
    try {
      const res = await removeAvatar();
      await applyPhoto(res.profile);
      toastSuccess('Photo removed');
    } catch (err) {
      showError(err.message, 'Could not remove');
    } finally {
      setPhotoBusy(false);
    }
  };

  if (!profile) {
    return (
      <Card className="max-w-2xl">
        <p className="text-sm text-slate-500">Loading...</p>
      </Card>
    );
  }

  return (
    <div className="max-w-2xl">
      <Card>
        <h2 className="text-xl font-bold">Profile</h2>

        <div className="mt-4 flex items-center gap-4">
          <Avatar url={avatarUrl} label={profile.name || profile.email} />
          <div className="flex flex-wrap gap-2">
            <input
              ref={fileInput}
              type="file"
              accept="image/png,image/jpeg"
              onChange={pickPhoto}
              className="hidden"
              aria-label="Choose a profile picture"
            />
            <Button variant="secondary" disabled={photoBusy} onClick={() => fileInput.current?.click()}>
              {photoBusy ? 'Working...' : profile.has_avatar ? 'Change photo' : 'Add photo'}
            </Button>
            {profile.has_avatar && (
              <Button variant="danger" disabled={photoBusy} onClick={dropPhoto}>
                Remove
              </Button>
            )}
            <p className="w-full text-xs text-slate-500">PNG or JPEG, up to 2 MB.</p>
          </div>
        </div>

        <form onSubmit={save} noValidate className="mt-5">
          <label htmlFor="pf-name" className="mb-1.5 block text-sm font-semibold">
            Name
          </label>
          <input
            id="pf-name"
            value={name}
            maxLength={100}
            onChange={(e) => setName(e.target.value)}
            disabled={saving}
            placeholder="Your name"
            autoComplete="name"
            className={inputClass}
          />

          <label htmlFor="pf-phone" className="mb-1.5 mt-4 block text-sm font-semibold">
            Phone number
          </label>
          <input
            id="pf-phone"
            type="tel"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            disabled={saving}
            placeholder="9876543210"
            autoComplete="tel"
            className={inputClass}
          />

          <label htmlFor="pf-email" className="mb-1.5 mt-4 block text-sm font-semibold">
            Email
          </label>
          <input id="pf-email" value={profile.email} readOnly className={`${inputClass} bg-slate-50`} />

          <Button type="submit" className="mt-5" disabled={saving || !dirty}>
            {saving ? (
              <>
                <Spinner /> Saving...
              </>
            ) : (
              'Save changes'
            )}
          </Button>
        </form>
      </Card>

      <PasswordChange email={profile.email} />
    </div>
  );
}
