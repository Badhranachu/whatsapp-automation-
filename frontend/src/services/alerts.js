// All user-facing notifications go through SweetAlert2 from here.
import Swal from 'sweetalert2';

const GREEN = '#10b981';
const RED = '#ef4444';
const GREY = '#64748b';

const Toast = Swal.mixin({
  toast: true,
  position: 'top-end',
  showConfirmButton: false,
  timer: 3000,
  timerProgressBar: true,
});

export function toastSuccess(title) {
  return Toast.fire({ icon: 'success', title });
}

// Background refreshes can fail repeatedly; don't stack the same toast every poll.
let lastToast = { title: '', at: 0 };
export function toastError(title) {
  const now = Date.now();
  if (title === lastToast.title && now - lastToast.at < 15000) return undefined;
  lastToast = { title, at: now };
  return Toast.fire({ icon: 'error', title, timer: 5000 });
}

export function showSuccess(title, text) {
  return Swal.fire({ icon: 'success', title, text, confirmButtonColor: GREEN });
}

export function showError(text, title = 'Something went wrong') {
  return Swal.fire({ icon: 'error', title, text, confirmButtonColor: GREEN });
}

/** Yes/No confirmation. Resolves to true when confirmed. */
export async function confirmAction({ title, text, confirmText = 'Yes', danger = false }) {
  const result = await Swal.fire({
    icon: 'warning',
    title,
    text,
    showCancelButton: true,
    confirmButtonText: confirmText,
    cancelButtonText: 'Cancel',
    confirmButtonColor: danger ? RED : GREEN,
    cancelButtonColor: GREY,
    focusCancel: danger,
  });
  return result.isConfirmed;
}

/** Unsaved-data prompt. Resolves to 'continue' or 'discard'. */
export async function askDiscardOrContinue({ title, text, continueText, discardText }) {
  const result = await Swal.fire({
    icon: 'question',
    title,
    text,
    showDenyButton: true,
    confirmButtonText: continueText,
    denyButtonText: discardText,
    confirmButtonColor: GREEN,
    denyButtonColor: RED,
    allowOutsideClick: false,
    allowEscapeKey: false,
  });
  return result.isConfirmed ? 'continue' : 'discard';
}

const escapeHtml = (value) =>
  String(value).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

/** Per-number result of a bulk send. results: [{ phone_number, success, error? }] */
export function showSendResults(message, results) {
  const sent = results.filter((r) => r.success).length;
  const icon = sent === results.length ? 'success' : sent === 0 ? 'error' : 'warning';
  const rows = results
    .map((r) =>
      r.success
        ? `<li>✅ +${escapeHtml(r.phone_number)} — accepted</li>`
        : `<li>❌ +${escapeHtml(r.phone_number)} — ${escapeHtml(r.error || 'failed')}</li>`,
    )
    .join('');
  return Swal.fire({
    icon,
    title: message,
    html: `<ul style="text-align:left;list-style:none;padding:0;max-height:260px;overflow:auto;font-size:14px">${rows}</ul>
           <p style="font-size:12px;color:#64748b;margin-top:10px">Accepted means Meta took it. Check History for delivery status.</p>`,
    confirmButtonColor: GREEN,
  });
}

/** Asks for the super admin password. Resolves to the typed password, or null if cancelled. */
export async function askAdminPassword({ title, text }) {
  const result = await Swal.fire({
    icon: 'warning',
    title,
    text,
    input: 'password',
    inputLabel: 'Super admin password',
    inputPlaceholder: 'Enter your password',
    inputAttributes: { autocomplete: 'current-password' },
    inputValidator: (value) => (value ? undefined : 'Enter the password to continue.'),
    showCancelButton: true,
    confirmButtonText: 'Delete',
    confirmButtonColor: RED,
    cancelButtonColor: GREY,
    focusCancel: false,
  });
  return result.isConfirmed ? result.value : null;
}
