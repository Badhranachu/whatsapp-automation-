// Mirrors the backend rule: international number, 8-15 digits, no leading 0.
export function isValidPhone(value) {
  const digits = value.replace(/[\s\-().]/g, '').replace(/^\+/, '');
  return /^[1-9]\d{7,14}$/.test(digits);
}

export const PHONE_ERROR = 'Enter a valid international phone number, e.g. +919876543210.';

/** Digits-only international number (e.g. "919876543210"), or null when it is not valid. */
export function normalizePhone(value) {
  let digits = value.replace(/[\s\-().]/g, '');
  if (digits.startsWith('+')) digits = digits.slice(1);
  else if (digits.startsWith('00')) digits = digits.slice(2);
  return /^[1-9]\d{7,14}$/.test(digits) ? digits : null;
}
