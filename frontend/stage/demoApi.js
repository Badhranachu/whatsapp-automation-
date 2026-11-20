// Stand-in for src/services/api.js used ONLY by the public /stage demo (see vite.stage.config.js).
// It keeps everything in memory: no network calls, no login, nothing is saved, nothing is sent.
// Edits work during the visit so the screens behave like the real app, and reset on reload.
// It exports the same names as the real module, so the real screens run unchanged.

const DAY = 86400000;
const MINUTE = 60000;
const NOW = Date.now();
const iso = (ms) => new Date(ms).toISOString();
const clone = (v) => JSON.parse(JSON.stringify(v));
const wait = (ms = 140) => new Promise((resolve) => setTimeout(resolve, ms));
const fail = (message) => {
  throw new Error(message);
};
const ok = async (value) => {
  await wait();
  return clone(value);
};

const MAX_OPTIONS = 3;
const MAX_TITLE = 20;
const MAX_TEXT = 1024;
const MAX_QUESTIONS = 200;

// ---------- tiny seeded random, so the demo looks the same on every visit ----------
function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const rand = rng(20261121);
const between = (lo, hi) => lo + Math.floor(rand() * (hi - lo + 1));

// ---------- the in-memory "database" ----------
const ME = { id: 1, email: 'demo.admin@example.com' };
const store = {
  seq: { template: 1, question: 1, option: 1, run: 1, step: 1, message: 1, audit: 1, user: 4 },
  templates: [],
  questions: [], // { id, template_id, text, parent_option_id, wants_reply, reply_thanks }
  options: [], // { id, question_id, title }
  runs: [],
  steps: [],
  messages: [],
  audit: [],
  users: [
    { id: 1, email: ME.email, phone_number: '919800000001', is_active: true, date_joined: iso(NOW - 40 * DAY) },
    { id: 2, email: 'priya.nair@example.com', phone_number: '919800000002', is_active: true, date_joined: iso(NOW - 21 * DAY) },
    { id: 3, email: 'arun.menon@example.com', phone_number: '919800000003', is_active: true, date_joined: iso(NOW - 9 * DAY) },
  ],
  profile: { name: 'Demo Admin', phone_number: '919800000001', avatarUrl: null, avatarVersion: null },
};

const nextId = (key) => store.seq[key]++;

function addTemplate(name, description, daysAgo) {
  const t = { id: nextId('template'), name, description, created_at: iso(NOW - daysAgo * DAY) };
  store.templates.push(t);
  return t;
}

// tree = { text, wants_reply?, reply_thanks?, options?: [{ title, next }] }
function seedTree(templateId, tree, parentOptionId = null) {
  const q = {
    id: nextId('question'),
    template_id: templateId,
    text: tree.text,
    parent_option_id: parentOptionId,
    wants_reply: Boolean(tree.wants_reply),
    reply_thanks: tree.reply_thanks || '',
  };
  store.questions.push(q);
  (tree.options || []).forEach((o) => {
    const opt = { id: nextId('option'), question_id: q.id, title: o.title };
    store.options.push(opt);
    if (o.next) seedTree(templateId, o.next, opt.id);
  });
  return q;
}

const end = (text, extra = {}) => ({ text, ...extra });

const FEEDBACK = {
  text: 'How was your experience with us?',
  options: [
    {
      title: 'Great',
      next: {
        text: 'What did you like most?',
        options: [
          { title: 'Service', next: end('Thank you! We are glad you enjoyed our service.') },
          { title: 'Quality', next: end('Thank you! Quality is our top priority.') },
          { title: 'Price', next: end('Thank you! We work hard to keep prices fair.') },
        ],
      },
    },
    {
      title: 'Okay',
      next: {
        text: 'What could we improve?',
        options: [
          { title: 'Speed', next: end('Thanks! We will work on faster delivery.') },
          {
            title: 'Support',
            next: end('Tell us how we can support you better. Type your message below.', {
              wants_reply: true,
              reply_thanks: 'Thanks, we saved your suggestion!',
            }),
          },
          { title: 'Price', next: end('Thanks for the feedback on pricing.') },
        ],
      },
    },
    {
      title: 'Poor',
      next: {
        text: 'What went wrong?',
        options: [
          { title: 'Late delivery', next: end('Sorry about the delay. Our team will look into it.') },
          {
            title: 'Product issue',
            next: end('Sorry to hear that. Please describe the problem in one message.', {
              wants_reply: true,
              reply_thanks: 'Thank you. Our team will contact you soon.',
            }),
          },
          { title: 'Rude staff', next: end('We apologise. This will be reviewed.') },
        ],
      },
    },
  ],
};

const RSVP = {
  text: 'Will you attend our event on 5 December?',
  options: [
    {
      title: 'Yes',
      next: {
        text: 'How many guests will join you?',
        options: [
          { title: 'Just me', next: end('Great! Your seat is reserved.') },
          { title: '2 people', next: end('Great! Two seats are reserved.') },
          { title: '3 or more', next: end('Great! We will confirm the group seating.') },
        ],
      },
    },
    {
      title: 'Maybe',
      next: {
        text: 'What would help you decide?',
        options: [
          { title: 'Agenda', next: end('The full agenda is on our website.') },
          { title: 'Venue details', next: end('The venue is at the Convention Centre, Kochi.') },
          { title: 'A reminder', next: end('We will remind you two days before.') },
        ],
      },
    },
    { title: 'No', next: end('No problem. We hope to see you next time!') },
  ],
};

const POLL = {
  text: 'Which feature should we build first?',
  options: ['Dark mode', 'Reports', 'Mobile app'].map((title) => ({
    title,
    next: {
      text: `How soon do you need ${title.toLowerCase()}?`,
      options: ['This month', 'This quarter', 'Someday'].map((when) => ({
        title: when,
        next: end('Thanks! We will keep you posted.'),
      })),
    },
  })),
};

const tFeedback = addTemplate('Customer Feedback Survey', 'Quick satisfaction survey sent after every delivery.', 18);
const tRsvp = addTemplate('Event RSVP', 'Invitation and guest count for the December event.', 11);
const tPoll = addTemplate('Product Launch Poll', 'Which feature should we build next?', 6);
addTemplate('New draft (empty)', '', 1);
seedTree(tFeedback.id, FEEDBACK);
seedTree(tRsvp.id, RSVP);
seedTree(tPoll.id, POLL);

// ---------- flow helpers (same shapes as the real API) ----------
const questionsOf = (templateId) => store.questions.filter((q) => q.template_id === templateId);
const optionsOfQuestion = (qid) => store.options.filter((o) => o.question_id === qid);
const childOf = (optionId) => store.questions.find((q) => q.parent_option_id === optionId);
const questionById = (id) => store.questions.find((q) => q.id === Number(id));
const optionById = (id) => store.options.find((o) => o.id === Number(id));

function buildFlow(templateId) {
  const qs = questionsOf(templateId);
  let maxDepth = 0;
  const node = (q, depth) => {
    maxDepth = Math.max(maxDepth, depth);
    return {
      id: q.id,
      text: q.text,
      depth,
      wants_reply: q.wants_reply,
      reply_thanks: q.reply_thanks,
      options: optionsOfQuestion(q.id).map((o) => {
        const child = childOf(o.id);
        return { id: o.id, title: o.title, next: child ? node(child, depth + 1) : null };
      }),
    };
  };
  const rootQ = qs.find((q) => q.parent_option_id === null);
  const root = rootQ ? node(rootQ, 1) : null;
  const optionCount = qs.reduce((n, q) => n + optionsOfQuestion(q.id).length, 0);
  return { root, stats: { questions: qs.length, options: optionCount, depth: maxDepth } };
}

function deleteQuestionDeep(qid) {
  optionsOfQuestion(qid).forEach((o) => deleteOptionDeep(o.id));
  store.questions = store.questions.filter((q) => q.id !== qid);
}
function deleteOptionDeep(oid) {
  const child = childOf(oid);
  if (child) deleteQuestionDeep(child.id);
  store.options = store.options.filter((o) => o.id !== oid);
}

// ---------- seed people who answered the surveys (runs, steps, messages) ----------
const REPLIES = [
  'Delivery was quick but packaging can be better.',
  'Please add more payment options.',
  'Support team was helpful, thank you!',
  'The product stopped working after two days.',
  'Would love a weekend delivery slot.',
  'Everything was fine. Keep it up!',
];

function logMessage(direction, phone, type, content, status, at, templateId, runId) {
  store.messages.push({
    id: nextId('message'),
    direction,
    phone_number: phone,
    message_type: type,
    content,
    wa_message_id: `wamid.demo${store.seq.message}`,
    status,
    status_detail: '',
    template_id: templateId ?? null,
    run_id: runId ?? null,
    created_at: iso(at),
  });
}

function addStep(run, kind, fields, at) {
  const step = {
    id: nextId('step'),
    run_id: run.id,
    order: store.steps.filter((s) => s.run_id === run.id).length + 1,
    kind,
    question_id: fields.question_id ?? null,
    option_id: fields.option_id ?? null,
    text: fields.text || '',
    detail: fields.detail || '',
    delivery_status: fields.delivery_status || '',
    created_at: iso(at),
  };
  store.steps.push(step);
  run.updated_at = iso(at);
  return step;
}

function startRun(templateId, phone, startedAt) {
  const t = store.templates.find((x) => x.id === templateId);
  const run = {
    id: nextId('run'),
    template_id: templateId,
    template_name: t.name,
    phone_number: phone,
    status: 'active',
    current_question_id: null,
    current_text: '',
    started_at: iso(startedAt),
    updated_at: iso(startedAt),
  };
  store.runs.push(run);
  return run;
}

function sendQuestionInRun(run, q, at, status = 'read') {
  const hasOptions = optionsOfQuestion(q.id).length > 0;
  addStep(run, 'question_sent', { question_id: q.id, text: q.text, delivery_status: status }, at);
  logMessage('out', run.phone_number, 'flow', q.text, status, at, run.template_id, run.id);
  run.current_question_id = q.id;
  run.current_text = q.text;
  run.status = hasOptions ? 'active' : 'completed';
}

function simulateRuns(templateId, count) {
  const rootQ = questionsOf(templateId).find((q) => q.parent_option_id === null);
  for (let i = 0; i < count; i += 1) {
    const phone = `9190${String(1000000 + between(0, 8999999))}`;
    let at = NOW - between(0, 13) * DAY - between(0, 23) * 60 * MINUTE - between(0, 59) * MINUTE;
    const run = startRun(templateId, phone, at);
    if (rand() < 0.04) {
      addStep(run, 'send_failed', { question_id: rootQ.id, text: rootQ.text, detail: 'Message could not be delivered (24-hour window closed).' }, at);
      run.status = 'failed';
      run.current_question_id = rootQ.id;
      run.current_text = rootQ.text;
      continue;
    }
    let q = rootQ;
    sendQuestionInRun(run, q, at, rand() < 0.7 ? 'read' : 'delivered');
    for (let guard = 0; guard < 10; guard += 1) {
      const opts = optionsOfQuestion(q.id);
      if (opts.length === 0) {
        if (q.wants_reply && rand() < 0.85) {
          at += between(20, 400) * 1000;
          addStep(run, 'reply_received', { question_id: q.id, text: REPLIES[between(0, REPLIES.length - 1)] }, at);
          logMessage('in', phone, 'text', store.steps[store.steps.length - 1].text, '', at, templateId, run.id);
        }
        break;
      }
      if (rand() < (guard === 0 ? 0.12 : 0.15)) break; // dropped off here
      const r = rand();
      const opt = opts[r < 0.5 ? 0 : r < 0.8 ? Math.min(1, opts.length - 1) : opts.length - 1];
      at += between(8, 220) * 1000;
      addStep(run, 'option_tapped', { question_id: q.id, option_id: opt.id, text: opt.title }, at);
      logMessage('in', phone, 'button_reply', opt.title, '', at, templateId, run.id);
      const next = childOf(opt.id);
      if (!next) {
        run.status = 'completed';
        break;
      }
      at += 2000;
      sendQuestionInRun(run, next, at, rand() < 0.7 ? 'read' : 'delivered');
      q = next;
    }
  }
}
simulateRuns(tFeedback.id, 52);
simulateRuns(tRsvp.id, 34);
simulateRuns(tPoll.id, 28);

// a few one-off messages sent from the Send Message page
['9190011223', '9190022334', '9190033445'].forEach((n, i) => {
  logMessage('out', `91${n}1`, 'template', 'hello_world', ['read', 'delivered', 'failed'][i], NOW - (i + 1) * 3 * 60 * MINUTE, null, null);
});
logMessage('out', '919004455667', 'image', 'Festival offer poster', 'read', NOW - 5 * 60 * MINUTE, null, null);
store.messages.sort((a, b) => (a.created_at < b.created_at ? 1 : -1));

// ---------- audit trail (dummy history of admin activity) ----------
function audit(action, entityType, label, changes = {}, actor = ME.email, at = Date.now()) {
  store.audit.push({
    id: nextId('audit'),
    actor_email: actor,
    actor_role: 'super_admin',
    action,
    entity_type: entityType,
    entity_id: String(between(1, 60)),
    entity_label: label,
    changes,
    ip_address: '203.0.113.' + between(10, 90),
    created_at: iso(at),
  });
}
[
  ['login', 'session', ME.email, {}, ME.email],
  ['create', 'template', 'Customer Feedback Survey', { name: 'Customer Feedback Survey' }, ME.email],
  ['import', 'flow', 'Customer Feedback Survey', { created_questions: 13, created_options: 12 }, ME.email],
  ['update', 'question', 'How was your experience with us?', { text: { from: 'How was your experience?', to: 'How was your experience with us?' } }, 'priya.nair@example.com'],
  ['send', 'template_send', 'Customer Feedback Survey', { numbers: 12, sent: 12, failed: 0 }, ME.email],
  ['create', 'template', 'Event RSVP', { name: 'Event RSVP' }, 'priya.nair@example.com'],
  ['update', 'option', 'Maybe', { title: { from: 'Not sure', to: 'Maybe' } }, 'priya.nair@example.com'],
  ['login', 'session', 'priya.nair@example.com', {}, 'priya.nair@example.com'],
  ['create', 'user', 'arun.menon@example.com', { email: 'arun.menon@example.com', role: 'super_admin' }, ME.email],
  ['update', 'template', 'Product Launch Poll', { description: { from: '', to: 'Which feature should we build next?' } }, 'arun.menon@example.com'],
  ['send', 'message', 'wamid.demo1', { type: 'template' }, 'arun.menon@example.com'],
  ['update', 'flow', 'Customer Feedback Survey', { updated_questions: 2, updated_options: 1, created_questions: 1, created_options: 1 }, ME.email],
  ['delete', 'option', 'Maybe later', { question: 'Will you attend our event?' }, 'priya.nair@example.com'],
  ['login_failed', 'session', 'unknown@example.com', {}, ''],
].forEach((row, i, all) => {
  const [action, entity, label, changes, actor] = row;
  const entry = (audit(action, entity, label, changes, actor, NOW - (all.length - i) * 9 * 60 * MINUTE), store.audit[store.audit.length - 1]);
  if (!actor) {
    entry.actor_role = 'anonymous';
  }
});
store.audit.sort((a, b) => (a.created_at < b.created_at ? 1 : -1));

// ---------- the exported API (same names and shapes as src/services/api.js) ----------
export function getToken() {
  return 'demo';
}
export function setToken() {}
export function setUnauthorizedHandler() {}
export const login = async () => fail('Sign-in is not available in the demo.');
export const logout = async () => {};
export const getMe = () => ok({ email: ME.email, is_superuser: true });

// Forgot password (signed out) is switched off in the real app and does not exist here.
export const requestResetOtp = async () => fail('Not available in the demo.');
export const verifyResetOtp = async () => fail('Not available in the demo.');
export const resetPassword = async () => fail('Not available in the demo.');

// --- profile ---
const describeProfile = () => ({
  email: ME.email,
  name: store.profile.name,
  phone_number: store.profile.phone_number,
  is_superuser: true,
  has_avatar: Boolean(store.profile.avatarUrl),
  avatar_version: store.profile.avatarVersion,
});
export const getProfile = () => ok(describeProfile());
export async function updateProfile(payload) {
  if ('name' in payload) {
    const name = String(payload.name || '').split(/\s+/).filter(Boolean).join(' ');
    if (name.length > 100) fail('Name must be 100 characters or fewer.');
    store.profile.name = name;
  }
  if ('phone_number' in payload) {
    const raw = String(payload.phone_number || '').replace(/[\s\-().]/g, '');
    if (raw && !/^\+?\d{8,15}$/.test(raw)) fail('Enter a valid phone number, e.g. 9876543210 or +919876543210.');
    store.profile.phone_number = raw.replace(/^\+/, '').length === 10 ? `91${raw}` : raw.replace(/^\+/, '');
  }
  return ok({ success: true, profile: describeProfile() });
}
export async function uploadAvatar(file) {
  if (store.profile.avatarUrl) URL.revokeObjectURL(store.profile.avatarUrl);
  store.profile.avatarUrl = URL.createObjectURL(file);
  store.profile.avatarVersion = iso(Date.now());
  return ok({ success: true, profile: describeProfile() });
}
export async function removeAvatar() {
  if (store.profile.avatarUrl) URL.revokeObjectURL(store.profile.avatarUrl);
  store.profile.avatarUrl = null;
  store.profile.avatarVersion = null;
  return ok({ success: true, profile: describeProfile() });
}
export async function getAvatarUrl() {
  await wait(60);
  return store.profile.avatarUrl;
}
export const sendPasswordOtp = () => ok({ success: true, sent: true, resend_seconds: 60 });
export async function verifyPasswordOtp(otp) {
  if (!/^\d{6}$/.test(String(otp))) fail('Enter the 6-digit code.');
  return ok({ success: true, reset_token: 'demo-token' });
}
export const changePassword = () => ok({ success: true, message: 'Password changed. (Demo: nothing was changed.)' });

// --- dashboard / history ---
export async function getStats() {
  const out = store.messages.filter((m) => m.direction === 'out');
  return ok({
    sent_total: out.length,
    delivered: out.filter((m) => ['delivered', 'read'].includes(m.status)).length,
    failed: out.filter((m) => m.status === 'failed').length,
    received: store.messages.filter((m) => m.direction === 'in').length,
  });
}

const templateRef = (m) => {
  if (m.template_id) {
    const t = store.templates.find((x) => x.id === m.template_id);
    return { id: m.template_id, name: t ? t.name : 'Deleted template' };
  }
  if (m.run_id) {
    const run = store.runs.find((r) => r.id === m.run_id);
    return run ? { id: null, name: run.template_name } : null;
  }
  return null;
};
export async function getMessages(params = {}) {
  let rows = store.messages;
  if (params.template) rows = rows.filter((m) => m.template_id === Number(params.template));
  if (params.direction === 'in' || params.direction === 'out') rows = rows.filter((m) => m.direction === params.direction);
  const q = String(params.q || '').trim().replace(/^\+/, '').replace(/\s/g, '');
  if (q) rows = rows.filter((m) => m.phone_number.includes(q));
  const limit = Math.min(Number(params.limit) || 100, 500);
  return ok(rows.slice(0, limit).map((m) => ({ ...m, template: templateRef(m) })));
}

export function sendMessage(phoneNumber, image, caption) {
  const digits = String(phoneNumber).replace(/[\s\-().+]/g, '');
  if (!/^\d{8,15}$/.test(digits)) return Promise.reject(new Error('Enter a valid phone number, e.g. 9876543210.'));
  const phone = digits.length === 10 ? `91${digits}` : digits;
  logMessage(
    'out', phone, image ? 'image' : 'template', image ? caption || image.name : 'hello_world', 'accepted', Date.now(), null, null,
  );
  store.messages.sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
  audit('send', 'message', phone, { type: image ? 'image' : 'template' });
  return ok({
    success: true,
    message: 'Demo only: nothing was actually sent.',
    message_id: store.messages.find((m) => m.phone_number === phone).wa_message_id,
  });
}

// --- templates ---
const describeTemplate = (t) => ({
  id: t.id,
  name: t.name,
  description: t.description,
  question_count: questionsOf(t.id).length,
  run_count: store.runs.filter((r) => r.template_id === t.id).length,
  created_at: t.created_at,
});
export const getTemplates = () => ok([...store.templates].sort((a, b) => (a.created_at < b.created_at ? 1 : -1)).map(describeTemplate));
export async function createTemplate(name, description) {
  const clean = String(name || '').trim();
  if (!clean) fail('Name is required.');
  if (clean.length > 100) fail('Name must be 100 characters or fewer.');
  const t = addTemplate(clean, String(description || '').trim(), 0);
  audit('create', 'template', clean, { name: clean, description: t.description });
  return ok(describeTemplate(t));
}
export async function updateTemplate(id, name, description) {
  const t = store.templates.find((x) => x.id === Number(id)) || fail('Template not found.');
  const clean = String(name || '').trim();
  if (!clean) fail('Name is required.');
  const changes = {};
  if (t.name !== clean) changes.name = { from: t.name, to: clean };
  if (t.description !== String(description || '').trim()) changes.description = { from: t.description, to: String(description || '').trim() };
  t.name = clean;
  t.description = String(description || '').trim();
  audit('update', 'template', clean, changes);
  return ok(describeTemplate(t));
}
export async function deleteTemplate(id) {
  const t = store.templates.find((x) => x.id === Number(id)) || fail('Template not found.');
  questionsOf(t.id)
    .filter((q) => q.parent_option_id === null)
    .forEach((q) => deleteQuestionDeep(q.id));
  store.runs.forEach((r) => {
    if (r.template_id === t.id) r.template_id = null; // sends are kept, like the real app
  });
  store.messages.forEach((m) => {
    if (m.template_id === t.id) m.template_id = null;
  });
  store.templates = store.templates.filter((x) => x.id !== t.id);
  audit('delete', 'template', t.name, { name: t.name });
  return ok({});
}

// --- questions and options ---
const cleanTitles = (raw) => {
  if (raw == null) return [];
  if (!Array.isArray(raw)) fail('Options must be a list.');
  if (raw.length > MAX_OPTIONS) fail(`A question can have at most ${MAX_OPTIONS} options (WhatsApp button limit).`);
  const seen = new Set();
  return raw.map((item) => {
    const title = String(item).trim();
    if (!title) fail('Every option needs text.');
    if (title.length > MAX_TITLE) fail(`Option text must be ${MAX_TITLE} characters or fewer (WhatsApp button limit).`);
    if (seen.has(title.toLowerCase())) fail('Options must be different from each other.');
    seen.add(title.toLowerCase());
    return title;
  });
};
const replyFields = (raw, hasOptions, path = 'Question') => {
  const wants = raw.wants_reply ?? false;
  if (typeof wants !== 'boolean') fail(`${path}: "wants_reply" must be true or false.`);
  const thanks = String(raw.reply_thanks || '').trim();
  if (hasOptions && (wants || thanks)) fail(`${path}: only a closing message (no options) can collect a typed reply.`);
  return [wants, wants ? thanks : ''];
};

export async function addQuestion(templateId, text, optionId, options, extra = {}) {
  const tid = Number(templateId);
  const clean = String(text || '').trim();
  if (!clean) fail('Question text is required.');
  if (clean.length > MAX_TEXT) fail(`Question must be ${MAX_TEXT} characters or fewer.`);
  const titles = cleanTitles(options);
  const [wants, thanks] = replyFields(extra, titles.length > 0);
  let parent = null;
  if (optionId == null || optionId === '') {
    if (questionsOf(tid).some((q) => q.parent_option_id === null)) fail('This template already has a first question.');
  } else {
    parent = optionById(optionId);
    if (!parent || questionById(parent.question_id)?.template_id !== tid) fail('Option not found in this template.');
    if (childOf(parent.id)) fail('This option already leads to a question.');
  }
  const q = {
    id: nextId('question'), template_id: tid, text: clean, parent_option_id: parent ? parent.id : null,
    wants_reply: wants, reply_thanks: thanks,
  };
  store.questions.push(q);
  titles.forEach((title) => store.options.push({ id: nextId('option'), question_id: q.id, title }));
  audit('create', 'question', clean, { options: titles });
  return ok({ id: q.id, text: q.text });
}
export async function addOption(questionId, title) {
  const q = questionById(questionId) || fail('Question not found.');
  const clean = String(title || '').trim();
  if (optionsOfQuestion(q.id).length >= MAX_OPTIONS && clean) fail(`A question can have at most ${MAX_OPTIONS} options (WhatsApp button limit).`);
  if (!clean) fail('Option text is required.');
  if (clean.length > MAX_TITLE) fail(`Option text must be ${MAX_TITLE} characters or fewer (WhatsApp button limit).`);
  if (optionsOfQuestion(q.id).some((o) => o.title.toLowerCase() === clean.toLowerCase())) fail('This question already has an option with that text.');
  const o = { id: nextId('option'), question_id: q.id, title: clean };
  store.options.push(o);
  audit('create', 'option', clean, { question: q.text });
  return ok({ id: o.id, title: o.title });
}
export async function updateQuestion(id, text) {
  const q = questionById(id) || fail('Question not found.');
  const clean = String(text || '').trim();
  if (!clean) fail('Question text is required.');
  if (clean.length > MAX_TEXT) fail(`Question must be ${MAX_TEXT} characters or fewer.`);
  audit('update', 'question', clean, { text: { from: q.text, to: clean } });
  q.text = clean;
  return ok({ id: q.id, text: q.text, wants_reply: q.wants_reply, reply_thanks: q.reply_thanks });
}
export async function setReplySettings(id, wantsReply, replyThanks) {
  const q = questionById(id) || fail('Question not found.');
  const [wants, thanks] = replyFields({ wants_reply: wantsReply, reply_thanks: replyThanks }, optionsOfQuestion(q.id).length > 0);
  audit('update', 'question', q.text, { wants_reply: { from: q.wants_reply, to: wants } });
  q.wants_reply = wants;
  q.reply_thanks = thanks;
  return ok({ id: q.id, text: q.text, wants_reply: wants, reply_thanks: thanks });
}
export async function updateOption(id, title) {
  const o = optionById(id) || fail('Option not found.');
  const clean = String(title || '').trim();
  if (!clean) fail('Option text is required.');
  if (clean.length > MAX_TITLE) fail(`Option text must be ${MAX_TITLE} characters or fewer (WhatsApp button limit).`);
  if (optionsOfQuestion(o.question_id).some((x) => x.id !== o.id && x.title.toLowerCase() === clean.toLowerCase())) {
    fail('This question already has an option with that text.');
  }
  audit('update', 'option', clean, { title: { from: o.title, to: clean } });
  o.title = clean;
  return ok({ id: o.id, title: o.title });
}
export async function deleteQuestion(id) {
  const q = questionById(id) || fail('Question not found.');
  audit('delete', 'question', q.text, { options: optionsOfQuestion(q.id).map((o) => o.title) });
  deleteQuestionDeep(q.id);
  return ok({});
}
export async function deleteOption(id) {
  const o = optionById(id) || fail('Option not found.');
  audit('delete', 'option', o.title, {});
  deleteOptionDeep(o.id);
  return ok({});
}

export async function getFlow(templateId) {
  const t = store.templates.find((x) => x.id === Number(templateId)) || fail('Template not found.');
  const { root, stats } = buildFlow(t.id);
  return ok({ template: { id: t.id, name: t.name, description: t.description }, root, stats });
}

// JSON import: builds a whole flow (all or nothing), only on an empty template.
export async function importFlow(templateId, flow) {
  const tid = Number(templateId);
  if (questionsOf(tid).length > 0) fail('This template already has questions. Delete them first to import a new flow.');
  const snapshot = { q: [...store.questions], o: [...store.options], seq: { ...store.seq } };
  let count = 0;
  const build = (node, parent, path) => {
    if (!node || typeof node !== 'object' || Array.isArray(node)) fail(`${path}: expected an object with "text".`);
    count += 1;
    if (count > MAX_QUESTIONS) fail(`A flow can have at most ${MAX_QUESTIONS} questions.`);
    const text = String(node.text || '').trim();
    if (!text) fail(`${path}: "text" is required.`);
    if (text.length > MAX_TEXT) fail(`${path}: text must be ${MAX_TEXT} characters or fewer.`);
    const opts = node.options || [];
    if (!Array.isArray(opts)) fail(`${path}: "options" must be a list.`);
    if (opts.length > MAX_OPTIONS) fail(`${path}: at most ${MAX_OPTIONS} options (WhatsApp button limit).`);
    const [wants, thanks] = replyFields(node, opts.length > 0, path);
    const q = {
      id: nextId('question'), template_id: tid, text, parent_option_id: parent, wants_reply: wants, reply_thanks: thanks,
    };
    store.questions.push(q);
    const seen = new Set();
    opts.forEach((raw, i) => {
      const here = `${path} > option ${i + 1}`;
      if (!raw || typeof raw !== 'object' || Array.isArray(raw)) fail(`${here}: expected an object with "title" and "next".`);
      const title = String(raw.title || '').trim();
      if (!title) fail(`${here}: "title" is required.`);
      if (title.length > MAX_TITLE) fail(`${here}: title must be ${MAX_TITLE} characters or fewer.`);
      if (seen.has(title.toLowerCase())) fail(`${here}: duplicate option "${title}".`);
      seen.add(title.toLowerCase());
      const opt = { id: nextId('option'), question_id: q.id, title };
      store.options.push(opt);
      if (raw.next == null) fail(`${here} "${title}": needs a "next" (a follow-up question or a closing message).`);
      build(raw.next, opt.id, `${here} "${title}"`);
    });
  };
  try {
    build(flow, null, 'First question');
  } catch (err) {
    store.questions = snapshot.q;
    store.options = snapshot.o;
    store.seq = snapshot.seq;
    throw err;
  }
  const result = buildFlow(tid);
  audit('import', 'flow', store.templates.find((t) => t.id === tid)?.name || '', result.stats);
  return ok(result);
}

// JSON save with ids: items with an id are updated in place, items without one are added.
export async function syncFlow(templateId, flow) {
  const tid = Number(templateId);
  const snapshot = clone({ q: store.questions, o: store.options, seq: store.seq });
  const stats = { created_questions: 0, updated_questions: 0, created_options: 0, updated_options: 0 };
  const sync = (node, option, path) => {
    if (!node || typeof node !== 'object' || Array.isArray(node)) fail(`${path}: expected an object with "text".`);
    const text = String(node.text || '').trim();
    if (!text) fail(`${path}: "text" is required.`);
    if (text.length > MAX_TEXT) fail(`${path}: text must be ${MAX_TEXT} characters or fewer.`);
    const rawOptions = node.options || [];
    if (!Array.isArray(rawOptions)) fail(`${path}: "options" must be a list.`);
    const existing = option ? childOf(option.id) : questionsOf(tid).find((q) => q.parent_option_id === null);
    const wanted = node.id ?? null;
    let question;
    if (existing) {
      if (wanted !== null && wanted !== existing.id) fail(`${path}: question id ${wanted} is not the question saved here (${existing.id}).`);
      let changed = false;
      if (existing.text !== text) {
        existing.text = text;
        changed = true;
      }
      if ('wants_reply' in node || 'reply_thanks' in node) {
        const [wants, thanks] = replyFields(node, rawOptions.length > 0 || optionsOfQuestion(existing.id).length > 0, path);
        if (existing.wants_reply !== wants || existing.reply_thanks !== thanks) {
          existing.wants_reply = wants;
          existing.reply_thanks = thanks;
          changed = true;
        }
      }
      if (changed) stats.updated_questions += 1;
      question = existing;
    } else {
      if (wanted !== null) fail(`${path}: question id ${wanted} does not exist here. Remove "id" to add a new question.`);
      const [wants, thanks] = replyFields(node, rawOptions.length > 0, path);
      question = {
        id: nextId('question'), template_id: tid, text, parent_option_id: option ? option.id : null, wants_reply: wants, reply_thanks: thanks,
      };
      store.questions.push(question);
      stats.created_questions += 1;
    }
    const saved = optionsOfQuestion(question.id);
    const titles = new Map(saved.map((o) => [o.id, o.title]));
    const parsed = rawOptions.map((raw, i) => {
      const here = `${path} > option ${i + 1}`;
      if (!raw || typeof raw !== 'object' || Array.isArray(raw)) fail(`${here}: expected an object with "title".`);
      const title = String(raw.title || '').trim();
      if (!title) fail(`${here}: "title" is required.`);
      if (title.length > MAX_TITLE) fail(`${here}: title must be ${MAX_TITLE} characters or fewer.`);
      const oid = raw.id ?? null;
      if (oid !== null && !titles.has(oid)) fail(`${here}: option id ${oid} does not belong to this question.`);
      titles.set(oid ?? `new${i}`, title);
      return { here, oid, title, next: raw.next };
    });
    if (titles.size > MAX_OPTIONS) fail(`${path}: at most ${MAX_OPTIONS} options (WhatsApp button limit).`);
    const folded = [...titles.values()].map((t) => t.toLowerCase());
    if (new Set(folded).size !== folded.length) fail(`${path}: options must be different from each other.`);
    parsed.forEach(({ here, oid, title, next }) => {
      let opt;
      if (oid === null) {
        if (next == null) fail(`${here} "${title}": needs a "next" (a follow-up question or a closing message).`);
        opt = { id: nextId('option'), question_id: question.id, title };
        store.options.push(opt);
        stats.created_options += 1;
      } else {
        opt = optionById(oid);
        if (opt.title !== title) {
          opt.title = title;
          stats.updated_options += 1;
        }
      }
      if (next != null) sync(next, opt, `${here} "${title}"`);
    });
  };
  try {
    sync(flow, null, 'First question');
  } catch (err) {
    store.questions = snapshot.q;
    store.options = snapshot.o;
    store.seq = snapshot.seq;
    throw err;
  }
  const { root, stats: flowStats } = buildFlow(tid);
  audit('update', 'flow', store.templates.find((t) => t.id === tid)?.name || '', stats);
  return ok({ root, stats: flowStats, changes: stats });
}

// --- sending a template (pretend) ---
export async function sendTemplateFlow(templateId, phoneNumbers) {
  const t = store.templates.find((x) => x.id === Number(templateId)) || fail('Template not found.');
  const rootQ = questionsOf(t.id).find((q) => q.parent_option_id === null);
  if (!rootQ) fail('This template has no questions yet. Add them in the Questions tab first.');
  const numbers = [...new Set((phoneNumbers || []).map((n) => String(n).replace(/\D/g, '')))];
  if (numbers.length === 0) fail('Add at least one phone number.');
  const results = numbers.map((phone) => {
    const run = startRun(t.id, phone, Date.now());
    sendQuestionInRun(run, rootQ, Date.now(), 'accepted');
    return { phone_number: phone, success: true, message_id: `wamid.demo${store.seq.message}`, run_id: run.id };
  });
  store.messages.sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
  audit('send', 'template_send', t.name, { numbers, sent: numbers.length, failed: 0 });
  return ok({
    success: true,
    message: `${numbers.length} of ${numbers.length} accepted. Demo only: nothing was actually sent.`,
    sent: numbers.length,
    failed: 0,
    results,
  });
}

// --- runs (diagram history) ---
const runSummary = (r) => ({
  id: r.id,
  template: r.template_id
    ? { id: r.template_id, name: store.templates.find((t) => t.id === r.template_id)?.name || r.template_name }
    : { id: null, name: r.template_name },
  phone_number: r.phone_number,
  status: r.status,
  current_question_id: r.current_question_id,
  current_text: r.current_text,
  started_at: r.started_at,
  updated_at: r.updated_at,
  steps: store.steps.filter((s) => s.run_id === r.id).length,
});

const dayStart = (s) => (/^\d{4}-\d{2}-\d{2}$/.test(s || '') ? new Date(`${s}T00:00:00`).getTime() : null);
const dayEnd = (s) => (/^\d{4}-\d{2}-\d{2}$/.test(s || '') ? new Date(`${s}T23:59:59.999`).getTime() : null);

function filterRuns(params = {}) {
  let rows = [...store.runs].sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1));
  const q = String(params.q || '').trim();
  if (q) {
    const digits = q.replace(/\D/g, '');
    rows = rows.filter(
      (r) => r.template_name.toLowerCase().includes(q.toLowerCase()) || (digits && r.phone_number.includes(digits)),
    );
  }
  if (params.template) rows = rows.filter((r) => r.template_id === Number(params.template));
  if (['active', 'completed', 'failed'].includes(params.status)) rows = rows.filter((r) => r.status === params.status);
  const from = dayStart(params.from);
  const to = dayEnd(params.to);
  if (from) rows = rows.filter((r) => new Date(r.started_at).getTime() >= from);
  if (to) rows = rows.filter((r) => new Date(r.started_at).getTime() <= to);
  return rows;
}
export const getRuns = (params = {}) => ok(filterRuns(params).slice(0, Math.min(Number(params.limit) || 200, 500)).map(runSummary));

export async function getRun(id) {
  const run = store.runs.find((r) => r.id === Number(id)) || fail('Not found.');
  const steps = store.steps.filter((s) => s.run_id === run.id).sort((a, b) => a.order - b.order);
  const flow = run.template_id ? { template: { id: run.template_id, name: run.template_name }, ...buildFlow(run.template_id) } : null;
  return ok({
    run: runSummary(run),
    steps: steps.map((s) => ({
      order: s.order, kind: s.kind, text: s.text, detail: s.detail, delivery_status: s.delivery_status,
      question_id: s.question_id, option_id: s.option_id, created_at: s.created_at,
    })),
    flow,
    path: {
      question_ids: steps.filter((s) => s.question_id).map((s) => s.question_id),
      option_ids: steps.filter((s) => s.kind === 'option_tapped' && s.option_id).map((s) => s.option_id),
    },
  });
}

export async function getTemplateStats(id, params = {}) {
  const tid = Number(id);
  const runs = filterRuns({ ...params, template: tid });
  const runIds = new Set(runs.map((r) => r.id));
  const steps = store.steps
    .filter((s) => runIds.has(s.run_id))
    .sort((a, b) => a.run_id - b.run_id || a.order - b.order);
  const { root } = buildFlow(tid);

  const questions = [];
  const optionIndex = new Map();
  const walk = (node) => {
    questions.push(node);
    node.options.forEach((o) => {
      optionIndex.set(o.id, [node.id, o.title]);
      if (o.next) walk(o.next);
    });
  };
  if (root) walk(root);

  const here = {};
  runs.filter((r) => r.status === 'active' && r.current_question_id).forEach((r) => {
    here[r.current_question_id] = (here[r.current_question_id] || 0) + 1;
  });
  const taps = {};
  steps.filter((s) => s.kind === 'option_tapped' && s.option_id).forEach((s) => {
    taps[s.option_id] = (taps[s.option_id] || 0) + 1;
  });

  const reached = new Map();
  const answered = new Map();
  const replySeconds = new Map();
  const routes = {};
  const add = (map, key, runId) => {
    if (!map.has(key)) map.set(key, new Set());
    map.get(key).add(runId);
  };
  const byRun = new Map();
  steps.forEach((s) => {
    if (!byRun.has(s.run_id)) byRun.set(s.run_id, []);
    byRun.get(s.run_id).push(s);
  });
  byRun.forEach((list, runId) => {
    const sentAt = {};
    const route = [];
    list.forEach((s) => {
      if (s.kind === 'question_sent' && s.question_id) {
        add(reached, s.question_id, runId);
        sentAt[s.question_id] = new Date(s.created_at).getTime();
      } else if (s.kind === 'option_tapped' && s.option_id) {
        const [qid, title] = optionIndex.get(s.option_id) || [null, ''];
        if (qid) {
          add(answered, qid, runId);
          if (sentAt[qid]) {
            if (!replySeconds.has(qid)) replySeconds.set(qid, []);
            replySeconds.get(qid).push((new Date(s.created_at).getTime() - sentAt[qid]) / 1000);
          }
        }
        route.push(s.text || title);
      }
    });
    if (route.length) routes[route.join(' → ')] = (routes[route.join(' → ')] || 0) + 1;
  });

  const replySteps = steps.filter((s) => s.kind === 'reply_received').sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
  const replyCounts = {};
  replySteps.forEach((s) => {
    replyCounts[s.question_id] = (replyCounts[s.question_id] || 0) + 1;
  });

  const funnel = questions.map((q) => {
    const r = reached.get(q.id)?.size || 0;
    const a = answered.get(q.id)?.size || 0;
    const qTaps = q.options.reduce((n, o) => n + (taps[o.id] || 0), 0);
    const secs = replySeconds.get(q.id) || [];
    const answerable = q.options.length > 0;
    return {
      id: q.id,
      text: q.text,
      depth: q.depth,
      is_end_note: !answerable,
      wants_reply: q.wants_reply,
      replied: replyCounts[q.id] || 0,
      reached: r,
      answered: a,
      drop_off: answerable ? Math.max(r - a, 0) : 0,
      drop_off_pct: r && answerable ? Math.round((1000 * (r - a)) / r) / 10 : 0,
      avg_reply_seconds: secs.length ? Math.round(secs.reduce((x, y) => x + y, 0) / secs.length) : null,
      options: q.options.map((o) => ({
        id: o.id,
        title: o.title,
        taps: taps[o.id] || 0,
        share_pct: qTaps ? Math.round((1000 * (taps[o.id] || 0)) / qTaps) / 10 : 0,
      })),
    };
  });

  const perDay = {};
  runs.forEach((r) => {
    const day = r.started_at.slice(0, 10);
    perDay[day] = perDay[day] || { sends: 0, completed: 0, failed: 0 };
    perDay[day].sends += 1;
    if (r.status === 'completed' || r.status === 'failed') perDay[day][r.status] += 1;
  });

  return ok({
    runs: runs.length,
    active: runs.filter((r) => r.status === 'active').length,
    completed: runs.filter((r) => r.status === 'completed').length,
    failed: runs.filter((r) => r.status === 'failed').length,
    users_here: here,
    reached: Object.fromEntries([...reached].map(([k, v]) => [k, v.size])),
    option_taps: taps,
    funnel,
    timeline: Object.keys(perDay).sort().map((date) => ({ date, ...perDay[date] })),
    top_routes: Object.entries(routes).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([route, count]) => ({ route, count })),
    replies: replySteps.slice(0, 200).map((s) => ({
      run_id: s.run_id,
      phone_number: store.runs.find((r) => r.id === s.run_id)?.phone_number || '',
      question: questionById(s.question_id)?.text || '',
      text: s.text,
      created_at: s.created_at,
    })),
    reply_total: replySteps.length,
  });
}

export async function downloadTemplateCsv(id, params = {}) {
  const runs = filterRuns({ ...params, template: Number(id) });
  const cell = (v) => `"${String(v).replace(/"/g, '""')}"`;
  const lines = [['phone_number', 'status', 'started_at', 'updated_at', 'current_question', 'answers', 'typed_reply'].join(',')];
  runs.forEach((r) => {
    const mine = store.steps.filter((s) => s.run_id === r.id);
    lines.push([
      `+${r.phone_number}`, r.status, r.started_at, r.updated_at, r.current_text,
      mine.filter((s) => s.kind === 'option_tapped').map((s) => s.text).join(' | '),
      mine.filter((s) => s.kind === 'reply_received').map((s) => s.text).join(' | '),
    ].map(cell).join(','));
  });
  const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/csv' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = `template-${id}-sends.csv`;
  a.click();
  URL.revokeObjectURL(url);
  return true;
}

// --- audit log and users ---
export async function getAuditLogs(params = {}) {
  let rows = [...store.audit].sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
  const q = String(params.q || '').trim().toLowerCase();
  if (q) rows = rows.filter((r) => r.actor_email.toLowerCase().includes(q) || r.entity_label.toLowerCase().includes(q));
  if (params.action) rows = rows.filter((r) => r.action === params.action);
  if (params.entity) rows = rows.filter((r) => r.entity_type === params.entity);
  return ok(rows.slice(0, Math.min(Number(params.limit) || 100, 500)));
}
export const getUsers = () => ok(store.users);
export async function createUser(payload) {
  const email = String(payload.email || '').trim().toLowerCase();
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) fail('Enter a valid email address.');
  if (store.users.some((u) => u.email === email)) fail('A user with this email already exists.');
  if ((payload.password || '').length < 8) fail('This password is too short. It must contain at least 8 characters.');
  if (payload.password !== payload.confirm_password) fail('Passwords do not match.');
  const raw = String(payload.phone_number || '').replace(/\D/g, '');
  const user = {
    id: nextId('user'), email, phone_number: raw.length === 10 ? `91${raw}` : raw, is_active: true, date_joined: iso(Date.now()),
  };
  store.users.push(user);
  audit('create', 'user', email, { email, role: 'super_admin' });
  return ok({ success: true, user });
}
export async function deleteUser(id) {
  const user = store.users.find((u) => u.id === Number(id)) || fail('User not found.');
  if (user.email === ME.email) fail('You cannot delete your own account.');
  store.users = store.users.filter((u) => u.id !== user.id);
  audit('delete', 'user', user.email, { email: user.email });
  return ok({});
}
