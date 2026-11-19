import { useEffect, useState } from 'react';
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
import {
  getMe,
  getToken,
  logout,
  sendMessage,
  sendOptions,
  setUnauthorizedHandler,
} from './services/api';
import { toastError } from './services/alerts';
import { confirmLeave } from './services/unsaved';

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
  const [tab, setTab] = useState('dashboard');
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

  // Moving to another page asks first when a form has unsaved data.
  const go = async (id) => {
    if (id === tab) return;
    if (await confirmLeave()) setTab(id);
  };

  const handleLogout = async () => {
    if (!(await confirmLeave())) return;
    await logout();
    setEmail(null);
    setIsSuperuser(false);
    setTab('dashboard');
  };

  if (checking) {
    return <div className="flex justify-center py-16 text-sm text-slate-500">Loading...</div>;
  }
  if (!email) {
    return (
      <Login
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
        {tab === 'options' && (
          <SendForm
            title="Send Options"
            description="Sends a question with two reply buttons. Tapping a button sends the reply image back. Works only if the person messaged your number in the last 24 hours."
            buttonLabel="Send Options"
            send={sendOptions}
          />
        )}
        {tab === 'templates' && <Templates />}
        {tab === 'questions' && <Questions />}
        {tab === 'templatesend' && <TemplateSend />}
        {tab === 'diagrams' && <DiagramTemplates />}
        {tab === 'history' && <History />}
        {tab === 'users' && isSuperuser && <UserManagement currentEmail={email} />}
      </main>
    </div>
  );
}
