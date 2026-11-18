import { useEffect, useState, useSyncExternalStore } from 'react';

export const TABS = [
  { id: 'dashboard', label: 'Dashboard', icon: '📊' },
  { id: 'template', label: 'Send Message', icon: '✉️' },
  { id: 'options', label: 'Send Options', icon: '🔘' },
  { id: 'templates', label: 'Templates', icon: '📝' },
  { id: 'questions', label: 'Questions', icon: '❓' },
  { id: 'templatesend', label: 'Template Send', icon: '🚀' },
  { id: 'diagrams', label: 'Diagram Templates', icon: '🗺️' },
  { id: 'history', label: 'History', icon: '🕘' },
];

// true while the screen is phone-sized (below Tailwind's md breakpoint)
function useIsMobile() {
  return useSyncExternalStore(
    (notify) => {
      const mq = window.matchMedia('(max-width: 767px)');
      mq.addEventListener('change', notify);
      return () => mq.removeEventListener('change', notify);
    },
    () => window.matchMedia('(max-width: 767px)').matches,
    () => false,
  );
}

function NavButton({ active, onClick, icon, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={active ? 'page' : undefined}
      className={`flex min-h-11 w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm font-semibold transition ${
        active ? 'bg-emerald-400 text-teal-950' : 'text-teal-100 hover:bg-white/10'
      }`}
    >
      <span aria-hidden="true" className="w-5 text-center">
        {icon}
      </span>
      {children}
    </button>
  );
}

export default function Sidebar({ active, onSelect, email, onLogout, onInstall }) {
  const [open, setOpen] = useState(false); // phone menu drawer
  const isMobile = useIsMobile();

  // Close the drawer with Esc, and stop the page scrolling behind it.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
    };
  }, [open]);

  // Back on a wide screen the drawer state no longer matters.
  useEffect(() => {
    if (!isMobile) setOpen(false);
  }, [isMobile]);

  const choose = (id) => {
    setOpen(false);
    onSelect(id);
  };
  const currentLabel = TABS.find((t) => t.id === active)?.label ?? 'WhatsApp Messenger';

  return (
    <>
      {/* Phone: slim top bar with the menu button */}
      <header className="sticky top-0 z-30 flex items-center gap-2 bg-teal-900 px-2 pb-2 pt-[max(0.5rem,env(safe-area-inset-top))] text-teal-50 shadow md:hidden">
        <button
          type="button"
          aria-label="Open menu"
          aria-expanded={open}
          onClick={() => setOpen(true)}
          className="flex h-11 w-11 items-center justify-center rounded-lg text-2xl hover:bg-white/10"
        >
          ☰
        </button>
        <div className="min-w-0 flex-1 truncate text-base font-bold">{currentLabel}</div>
      </header>

      {open && (
        <div
          className="fixed inset-0 z-40 bg-black/50 md:hidden"
          onClick={() => setOpen(false)}
          aria-hidden="true"
        />
      )}

      <aside
        // off-screen drawer on phones must not be focusable while closed
        inert={isMobile && !open ? true : undefined}
        className={`fixed inset-y-0 left-0 z-50 flex w-72 max-w-[85vw] flex-col overflow-y-auto bg-teal-900 p-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-[max(1rem,env(safe-area-inset-top))] text-teal-50 transition-transform duration-200 md:sticky md:top-0 md:z-auto md:h-screen md:w-60 md:max-w-none md:translate-x-0 ${
          open ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex items-center justify-between px-2 pb-5">
          <div className="text-lg font-bold">💬 WhatsApp Messenger</div>
          <button
            type="button"
            aria-label="Close menu"
            onClick={() => setOpen(false)}
            className="flex h-10 w-10 items-center justify-center rounded-lg text-xl hover:bg-white/10 md:hidden"
          >
            ✕
          </button>
        </div>

        <nav className="flex flex-1 flex-col gap-1">
          {TABS.map((t) => (
            <NavButton key={t.id} icon={t.icon} active={active === t.id} onClick={() => choose(t.id)}>
              {t.label}
            </NavButton>
          ))}
        </nav>

        <div className="mt-3 flex flex-col gap-1 border-t border-white/15 pt-3">
          {onInstall && (
            <NavButton icon="📲" onClick={onInstall}>
              Install app
            </NavButton>
          )}
          <div className="truncate px-3 py-1 text-xs text-teal-200" title={email}>
            {email}
          </div>
          <NavButton
            icon="🚪"
            onClick={() => {
              setOpen(false);
              onLogout();
            }}
          >
            Log out
          </NavButton>
        </div>
      </aside>
    </>
  );
}
