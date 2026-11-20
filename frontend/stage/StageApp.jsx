import { useEffect, useRef, useState } from 'react';
import Sidebar from '../src/components/Sidebar';
import Dashboard from '../src/components/Dashboard';
import SendForm from '../src/components/SendForm';
import History from '../src/components/History';
import Templates from '../src/components/Templates';
import Questions from '../src/components/Questions';
import TemplateSend from '../src/components/TemplateSend';
import DiagramTemplates from '../src/components/DiagramTemplates';
import UserManagement from '../src/components/UserManagement';
import AuditLog from '../src/components/AuditLog';
import Profile from '../src/components/Profile';
import { sendMessage } from '../src/services/api'; // swapped for stage/demoApi.js by vite.stage.config.js
import { confirmLeave } from '../src/services/unsaved';

// A public, read-only copy of the whole app. Same screens and sidebar as the signed-in app, running on dummy
// data held in memory: visitors can click and edit everything, but nothing is saved or sent anywhere.
const PREFIX = '/stage';
const TAB_PATHS = {
  dashboard: PREFIX,
  template: `${PREFIX}/send-message`,
  templates: `${PREFIX}/templates`,
  questions: `${PREFIX}/questions`,
  templatesend: `${PREFIX}/template-send`,
  diagrams: `${PREFIX}/diagrams`,
  history: `${PREFIX}/history`,
  profile: `${PREFIX}/profile`,
  users: `${PREFIX}/users`,
  audit: `${PREFIX}/audit-log`,
};
const DEMO_EMAIL = 'demo.admin@example.com';

function tabFromPath(pathname) {
  const clean = pathname.replace(/\/+$/, '') || PREFIX;
  return Object.keys(TAB_PATHS).find((id) => TAB_PATHS[id] === clean) ?? 'dashboard';
}

export default function StageApp() {
  const [tab, setTab] = useState(() => tabFromPath(window.location.pathname));
  const tabRef = useRef(tab);
  tabRef.current = tab;

  // keep the address bar in step with the page (also fixes unknown /stage/... addresses)
  useEffect(() => {
    if (window.location.pathname !== TAB_PATHS[tab]) window.history.replaceState(null, '', TAB_PATHS[tab]);
  }, [tab]);

  // Back / Forward between pages, asking first when a form has unsaved typing
  useEffect(() => {
    const onPop = async () => {
      const next = tabFromPath(window.location.pathname);
      if (next === tabRef.current) return;
      if (await confirmLeave()) setTab(next);
      else window.history.pushState(null, '', TAB_PATHS[tabRef.current]);
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const go = async (id) => {
    if (id === tab) return;
    if (await confirmLeave()) {
      window.history.pushState(null, '', TAB_PATHS[id]);
      setTab(id);
    }
  };

  return (
    <div className="flex min-h-dvh flex-col md:flex-row">
      <Sidebar
        active={tab}
        onSelect={go}
        email={DEMO_EMAIL}
        isSuperuser
        onLogout={() => window.location.assign('/')} // "Log out" leaves the demo for the real sign-in page
      />
      <main className="min-w-0 flex-1 p-3 pb-[max(1rem,env(safe-area-inset-bottom))] sm:p-6">
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
        {tab === 'users' && <UserManagement currentEmail={DEMO_EMAIL} />}
        {tab === 'audit' && <AuditLog />}
      </main>
    </div>
  );
}
