import { useEffect, useRef, useState } from 'react';

// Small shared Tailwind building blocks.

export const inputClass =
  'w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-base outline-none transition focus:border-emerald-500 focus:ring-2 focus:ring-emerald-200 disabled:opacity-60 sm:text-sm';

export function Button({ variant = 'primary', className = '', ...props }) {
  const styles = {
    primary: 'bg-emerald-500 text-white hover:bg-emerald-600',
    secondary: 'bg-slate-200 text-slate-800 hover:bg-slate-300',
    danger: 'bg-red-50 text-red-700 hover:bg-red-100',
    ghost: 'text-emerald-700 hover:bg-emerald-50',
  };
  return (
    <button
      type="button"
      {...props}
      className={`min-h-11 rounded-lg px-4 py-2.5 text-sm font-semibold transition sm:min-h-10 disabled:cursor-not-allowed disabled:opacity-60 ${styles[variant]} ${className}`}
    />
  );
}

export function Card({ className = '', ...props }) {
  return (
    <section
      {...props}
      className={`rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200 sm:p-6 ${className}`}
    />
  );
}

export function Spinner() {
  return (
    <span
      aria-hidden="true"
      className="mr-2 inline-block h-4 w-4 animate-spin rounded-full border-2 border-white/50 border-t-white align-[-2px]"
    />
  );
}

// Three-dots menu. items: [{ label, onClick, danger?, disabled? }]
export function KebabMenu({ items, label = 'More actions', disabled = false }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => {
      if (e.type === 'keydown' ? e.key === 'Escape' : !ref.current?.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', close);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', close);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        type="button"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        className="flex h-11 w-11 items-center justify-center rounded-full text-xl font-bold leading-none text-slate-500 sm:h-9 sm:w-9 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
      >
        ⋮
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-20 mt-1 w-40 overflow-hidden rounded-lg bg-white py-1 shadow-lg ring-1 ring-slate-200"
        >
          {items.map((item) => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              disabled={item.disabled}
              onClick={() => {
                setOpen(false);
                item.onClick();
              }}
              className={`block min-h-11 w-full px-4 py-2 text-left text-sm font-medium transition sm:min-h-0 disabled:opacity-50 ${
                item.danger ? 'text-red-600 hover:bg-red-50' : 'text-slate-700 hover:bg-slate-100'
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
