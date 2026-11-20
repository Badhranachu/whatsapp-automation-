// Country code added to numbers typed without one (10 digits). Empty disables it.
const DEFAULT_COUNTRY_CODE = String(import.meta.env.VITE_DEFAULT_COUNTRY_CODE ?? '91').replace(/\D/g, '');
const NATIONAL_LENGTH = 10;

export const PHONE_ERROR = 'Enter a valid phone number, e.g. 9876543210 or +919876543210.';

/** Digits-only international number (e.g. "919876543210"), or null when it is not valid. */
export function normalizePhone(value) {
  let digits = String(value).replace(/[\s\-().]/g, '');
  if (digits.startsWith('+')) digits = digits.slice(1);
  else if (digits.startsWith('00')) digits = digits.slice(2);
  else if (DEFAULT_COUNTRY_CODE && /^\d+$/.test(digits)) {
    if (digits.length === NATIONAL_LENGTH + 1 && digits.startsWith('0')) digits = digits.slice(1);
    if (digits.length === NATIONAL_LENGTH) digits = DEFAULT_COUNTRY_CODE + digits;
  }
  return /^[1-9]\d{7,14}$/.test(digits) ? digits : null;
}

export const isValidPhone = (value) => normalizePhone(value) !== null;
