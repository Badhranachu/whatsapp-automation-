// Tracks whether a form has unsaved data, and keeps a draft in localStorage so it
// survives a reload or a closed tab.
import { askDiscardOrContinue } from './alerts';

let dirty = false;
let onDiscard = null;

export function setDirty(value, discardCallback = null) {
  dirty = value;
  onDiscard = value ? discardCallback : null;
}

/**
 * Call before leaving a screen inside the app. Resolves to true when it is fine to
 * leave: either nothing is unsaved, or the user chose to discard it.
 */
export async function confirmLeave() {
  if (!dirty) return true;
  const choice = await askDiscardOrContinue({
    title: 'You have unsaved data',
    text: 'Do you want to discard it, or continue editing?',
    continueText: 'Continue editing',
    discardText: 'Discard data',
  });
  if (choice === 'continue') return false;
  const cb = onDiscard;
  dirty = false;
  onDiscard = null;
  if (cb) cb();
  return true;
}

export function loadDraft(key) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function saveDraft(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable: the draft just won't survive a reload */
  }
}

export function clearDraft(key) {
  try {
    localStorage.removeItem(key);
  } catch {
    /* ignore */
  }
}
