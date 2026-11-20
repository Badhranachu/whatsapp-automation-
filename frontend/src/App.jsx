import { useEffect, useRef, useState } from 'react';
import Login from './components/Login';
import Sidebar from './components/Sidebar';
import Dashboard from './components/Dashboard';
import SendForm from './components/SendForm';
import History from './components/History';
import Templates from './components/Templates';
import Questions from './components/Questions';
import TemplateSend from './components/TemplateSend';
import DiagramTemplates from './components/DiagramTemplates';
import UserManagement from './components/UserManagement';
import AuditLog from './components/AuditLog';
import Profile from './components/Profile';
import ForgotPassword from './components/ForgotPassword';
import {
  getMe,
  getToken,
  logout,
  sendMessage,
  setUnauthorizedHandler,
} from './services/api';
import { toastError } from './services/alerts';
import { confirmLeave } from './services/unsaved';

// Every sidebar page has its own address, so it can be bookmarked, reloaded and shared,
// and the browser Back / Forward buttons move between pages.
const TAB_PATHS = {
  dashboard: '/dashboard',
  template: '/send-message',
  templates: '/templates',
  questions: '/questions',
  templatesend: '/template-send',
  diagrams: '/diagrams',
  history: '/history',
  profile: '/profile',
  users: '/users',
  audit: '/audit-log',
};
const ADMIN_TABS = new Set(['users', 'audit']);
const FORGOT_PATH = '/forgot-password';

function tabFromPath(pathname) {
  const clean = pathname.replace(/\/+$/, '') || '/';
  return Object.keys(TAB_PATHS).find((id) => TAB_PATHS[id] === clean) ?? 'dashboard';
}

// "Install app" support: Chrome/Edge/Android fire this event when the PWA can be installed.
function useInstallPrompt() {
  const [event, setEvent] = useState(null);
  useEffect(() => {
    const onPrompt = (e) => {
      e.preventDefault();
      setEvent(e);
    };
    const onInstalled = () => setEvent(null);
    window.addEventListener('beforeinstallprompt', onPrompt);
    window.addEventListener('appinstalled', onInstalled);
    return () => {
      window.removeEventListener('beforeinstallprompt', onPrompt);
      window.removeEventListener('appinstalled', onInstalled);
    };
  }, []);
  if (!event) return null;
  return async () => {
    event.prompt();
    await event.userChoice;
    setEvent(null);
  };
}

function useOnline() {
  const [online, setOnline] = useState(navigator.onLine);
  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener('online', on);
    window.addEventListener('offline', off);
    return () => {
      window.removeEventListener('online', on);
      window.removeEventListener('offline', off);
    };
  }, []);
  return online;
}

export default function App() {
  const [email, setEmail] = useState(null);
  const [isSuperuser, setIsSuperuser] = useState(false);
  const [checking, setChecking] = useState(Boolean(getToken()));
  const [tab, setTab] = useState(() => tabFromPath(window.location.pathname));
  const tabRef = useRef(tab);
  const [forgot, setForgot] = useState(() => window.location.pathname === FORGOT_PATH);
  const [lastEmail, setLastEmail] = useState('');
  tabRef.current = tab;
  const install = useInstallPrompt();
  const online = useOnline();

  // Any 401 from the API sends the user back to the login page.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setEmail(null);
      toastError('Your session expired. Please sign in again.');
    });
  }, []);

  // Restore an existing session on page load.
  useEffect(() => {
    if (!getToken()) return;
    getMe()
      .then((me) => {
        setEmail(me.email);
        setIsSuperuser(Boolean(me.is_superuser));
      })
      .catch(() => setEmail(null))
      .finally(() => setChecking(false));
  }, []);

  // Keep the address bar in step with the page (also fixes "/" and unknown addresses).
  useEffect(() => {
    if (!email) return; // signed out: the login / forgot-password address stays as it is
    const path = TAB_PATHS[tab];
    if (window.location.pathname !== path) window.history.replaceState(null, '', path);
  }, [tab, email]);

  // Browser Back / Forward: change page, but ask first when a form has unsaved data.
  useEffect(() => {
    const onPop = async () => {
      setForgot(window.location.pathname === FORGOT_PATH);
      const next = tabFromPath(window.location.pathname);
      if (next === tabRef.current) return;
      if (await confirmLeave()) {
        setTab(next);
      } else {
        window.history.pushState(null, '', TAB_PATHS[tabRef.current]); // stay on this page
      }
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  // Moving to another page asks first when a form has unsaved data.
  const go = async (id) => {
    if (id === tab) return;
    if (await confirmLeave()) {
      window.history.pushState(null, '', TAB_PATHS[id]);
      setTab(id);
    }
  };

  // A non-admin who opens an admin address lands on the dashboard.
  useEffect(() => {
    if (email && !isSuperuser && ADMIN_TABS.has(tab)) {
      window.history.replaceState(null, '', TAB_PATHS.dashboard);
      setTab('dashboard');
    }
  }, [email, isSuperuser, tab]);

  const handleLogout = async () => {
    if (!(await confirmLeave())) return;
    await logout();
    setEmail(null);
    setIsSuperuser(false);
    window.history.replaceState(null, '', TAB_PATHS.dashboard);
    setTab('dashboard');
  };

  if (checking) {
    return <div className="flex justify-center py-16 text-sm text-slate-500">Loading...</div>;
  }
  if (!email) {
    const showLogin = () => {
      window.history.pushState(null, '', '/');
      setForgot(false);
    };
    if (forgot) {
      return (
        <ForgotPassword
          onBack={showLogin}
          onDone={(address) => {
            setLastEmail(address);
            showLogin(); // password updated: back to the login form
          }}
        />
      );
    }
    return (
      <Login
        initialEmail={lastEmail}
        onForgot={() => {
          window.history.pushState(null, '', FORGOT_PATH);
          setForgot(true);
        }}
        onLoggedIn={(data) => {
          setEmail(data.email);
          setIsSuperuser(Boolean(data.is_superuser));
        }}
      />
    );
  }

  return (
    <div className="flex min-h-dvh flex-col md:flex-row">
      <Sidebar active={tab} onSelect={go} email={email} isSuperuser={isSuperuser} onLogout={handleLogout} onInstall={install} />
      <main className="min-w-0 flex-1 p-3 pb-[max(1rem,env(safe-area-inset-bottom))] sm:p-6">
        {!online && (
          <div role="status" className="mb-3 rounded-lg bg-amber-100 px-3 py-2 text-sm font-medium text-amber-900">
            You are offline. Messages can&apos;t be sent until the connection is back.
          </div>
        )}
        {tab === 'dashboard' && <Dashboard onNavigate={go} />}
        {tab === 'template' && (
          <SendForm
            title="Send Message"
            description="Sends the approved template message. Attach a photo to send it as an image instead (works only if the person messaged your number in the last 24 hours)."
            buttonLabel="Send Message"
            allowImage
            send={(phone, opts) => sendMessage(phone, opts?.image, opts?.caption)}
          />
        )}
        {tab === 'templates' && <Templates />}
        {tab === 'questions' && <Questions />}
        {tab === 'templatesend' && <TemplateSend />}
        {tab === 'diagrams' && <DiagramTemplates />}
        {tab === 'history' && <History />}
        {tab === 'profile' && <Profile />}
        {tab === 'users' && isSuperuser && <UserManagement currentEmail={email} />}
        {tab === 'audit' && isSuperuser && <AuditLog />}
      </main>
    </div>
  );
}
