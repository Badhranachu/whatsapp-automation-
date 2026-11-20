import axios from 'axios';

const TOKEN_KEY = 'wa_token';

// The login token lives in sessionStorage: a reload keeps you signed in, but closing the tab or the
// browser window ends the session and the next visit starts at the login page.
// (Older versions kept it in localStorage; that copy is removed so nobody stays signed in forever.)
try {
  localStorage.removeItem(TOKEN_KEY);
} catch {
  /* storage unavailable */
}

export function getToken() {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token) {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: user just has to log in again */
  }
}

const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
});

let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
}

client.interceptors.request.use((config) => {
  const token = getToken();
  if (token) config.headers.Authorization = `Token ${token}`;
  return config;
});

client.interceptors.response.use(
  (res) => res,
  (error) => {
    const isLogin = error.config?.url?.includes('/auth/login/');
    if (error.response?.status === 401 && !isLogin) {
      setToken(null);
      onUnauthorized();
    }
    return Promise.reject(error);
  },
);

function describeError(error) {
  const data = error.response?.data;
  if (error.response?.status === 429) return 'Too many attempts. Please wait a minute and try again.';
  if (data?.error) {
    if (typeof data.error === 'string') return data.error;
    // DRF field errors: { field: ["msg"] }
    return Object.values(data.error).flat().join(' ');
  }
  if (data?.message) return data.message;
  if (data?.detail) return data.detail;
  if (error.code === 'ECONNABORTED') return 'The request timed out. Please try again.';
  if (!error.response) return 'Cannot reach the server. Is the Django backend running?';
  return 'Unexpected error. Please try again.';
}

async function call(request) {
  try {
    const { data } = await request();
    return data;
  } catch (error) {
    throw new Error(describeError(error));
  }
}

export async function login(email, password) {
  const data = await call(() => client.post('/auth/login/', { email, password }));
  setToken(data.token);
  return data;
}

// --- Forgot password (signed out): email -> code -> new password ---
export const requestResetOtp = (email) => call(() => client.post('/auth/forgot-password/', { email }));
export const verifyResetOtp = (email, otp) => call(() => client.post('/auth/verify-otp/', { email, otp }));
export const resetPassword = (payload) => call(() => client.post('/auth/reset-password/', payload));

// --- Profile (signed in) ---
export const getProfile = () => call(() => client.get('/profile/'));
export const updateProfile = (payload) => call(() => client.patch('/profile/', payload));
export const uploadAvatar = (file) => {
  const form = new FormData();
  form.append('image', file);
  return call(() =>
    client.post('/profile/avatar/', form, { headers: { 'Content-Type': 'multipart/form-data' } }),
  );
};
export const removeAvatar = () => call(() => client.delete('/profile/avatar/'));
// The picture needs the login token, so it is fetched and shown through a temporary blob URL.
export async function getAvatarUrl() {
  try {
    const res = await client.get('/profile/avatar/', { responseType: 'blob' });
    return URL.createObjectURL(res.data);
  } catch {
    return null;
  }
}
export const sendPasswordOtp = () => call(() => client.post('/profile/password/send-otp/'));
export const verifyPasswordOtp = (otp) => call(() => client.post('/profile/password/verify-otp/', { otp }));
export async function changePassword(payload) {
  const data = await call(() => client.post('/profile/password/change/', payload));
  if (data.token) setToken(data.token); // the old login was replaced; this device keeps going
  return data;
}

export async function logout() {
  try {
    await client.post('/auth/logout/');
  } catch {
    /* token may already be invalid; clear locally regardless */
  }
  setToken(null);
}

export const getMe = () => call(() => client.get('/auth/me/'));
export const getStats = () => call(() => client.get('/stats/'));
export const getMessages = (params = {}) => call(() => client.get('/messages/', { params }));
// Without an image the backend sends the approved template; with one it sends
// the photo (and optional caption) as a free-form image message.
export function sendMessage(phoneNumber, image, caption) {
  if (!image) {
    return call(() => client.post('/send-message/', { phone_number: phoneNumber }));
  }
  const form = new FormData();
  form.append('phone_number', phoneNumber);
  form.append('image', image);
  if (caption) form.append('message', caption);
  // Override the JSON default so the browser sends a proper multipart body.
  return call(() =>
    client.post('/send-message/', form, { headers: { 'Content-Type': 'multipart/form-data' } }),
  );
}

export const getTemplates = () => call(() => client.get('/templates/'));
export const createTemplate = (name, description) =>
  call(() => client.post('/templates/', { name, description }));

export const updateTemplate = (id, name, description) =>
  call(() => client.patch(`/templates/${id}/`, { name, description }));
// Deleting a template needs the super admin's password (checked by the server).
export const deleteTemplate = (id, password) =>
  call(() => client.delete(`/templates/${id}/`, { data: { password } }));
export const updateQuestion = (id, text) => call(() => client.patch(`/questions/${id}/`, { text }));
// Closing messages only: ask the person to type one reply, saved on their run (+ optional thank-you).
export const setReplySettings = (id, wantsReply, replyThanks) =>
  call(() => client.patch(`/questions/${id}/`, { wants_reply: wantsReply, reply_thanks: replyThanks }));
export const updateOption = (id, title) => call(() => client.patch(`/options/${id}/`, { title }));

// Sends the template's first question (as reply buttons) to every number; returns per-number results.
export const sendTemplateFlow = (templateId, phoneNumbers) =>
  call(() => client.post(`/templates/${templateId}/send/`, { phone_numbers: phoneNumbers }));

// Saved template sends ("runs"), searchable by phone number or template name.
export const getRuns = (params = {}) => call(() => client.get('/flow-runs/', { params }));
export const getRun = (id) => call(() => client.get(`/flow-runs/${id}/`));
export const getTemplateStats = (id, params = {}) =>
  call(() => client.get(`/templates/${id}/stats/`, { params }));
// Downloads the CSV of a template's sends and saves it through the browser.
export const downloadTemplateCsv = (id, params = {}) =>
  call(async () => {
    const res = await client.get(`/templates/${id}/export/`, { params, responseType: 'blob' });
    const url = URL.createObjectURL(res.data);
    const a = document.createElement('a');
    a.href = url;
    a.download = `template-${id}-sends.csv`;
    a.click();
    URL.revokeObjectURL(url);
    return true;
  });

export const getFlow =(templateId) => call(() => client.get(`/templates/${templateId}/flow/`));
// `options` (optional list of titles) is saved together with the question, all or nothing.
export const addQuestion = (templateId, text, optionId, options, extra = {}) =>
  call(() =>
    client.post(`/templates/${templateId}/questions/`, {
      text,
      option_id: optionId ?? null,
      ...(options ? { options } : {}),
      ...extra,
    }),
  );
// Updates a flow from JSON that carries the saved ids: ids are updated in place, the rest added.
export const syncFlow = (templateId, flow) =>
  call(() => client.post(`/templates/${templateId}/sync-flow/`, flow));
// Builds the whole flow from a nested JSON object (all or nothing).
export const importFlow = (templateId, flow) =>
  call(() => client.post(`/templates/${templateId}/import-flow/`, flow));
export const addOption = (questionId, title) =>
  call(() => client.post(`/questions/${questionId}/options/`, { title }));
export const deleteQuestion = (questionId) => call(() => client.delete(`/questions/${questionId}/`));
export const deleteOption = (optionId) => call(() => client.delete(`/options/${optionId}/`));
// User management (super admins only).
export const getAuditLogs = (params = {}) => call(() => client.get('/audit-logs/', { params }));
export const getUsers = () => call(() => client.get('/users/'));
export const createUser = (payload) => call(() => client.post('/users/', payload));
export const deleteUser = (id, password) =>
  call(() => client.delete(`/users/${id}/`, { data: { password } }));
