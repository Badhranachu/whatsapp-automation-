import { useEffect, useRef, useState } from 'react';
import { Button } from './ui';

// Org-chart style diagram of a template's questions -> options -> follow-up questions.
// Used by the Questions editor and by the Diagram Templates page.
//
// Props:
//   root            first question node ({ id, text, depth, options: [{ id, title, next }] })
//   currentId       question to mark with a badge ("You are here" by default)
//   currentLabel    text of that badge
//   onSelect        makes question cards clickable
//   pathQuestionIds / pathOptionIds   (Sets) highlight a route and dim everything else
//   questionNote(q) / optionNote(o)    small extra text (e.g. counts) under a card / on a pill

function QuestionCard({ q, currentId, currentLabel, onSelect, path, note }) {
  const isCurrent = q.id === currentId;
  const onPath = !path || path.has(q.id);
  const endNote = q.options.length === 0;

  const body = (
    <>
      {isCurrent && (
        <span className="absolute -top-2.5 left-3 rounded-full bg-emerald-500 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white">
          {currentLabel}
        </span>
      )}
      <div className={`text-[10px] font-bold uppercase ${endNote ? 'text-amber-600' : 'text-slate-400'}`}>
        {endNote ? `End note · Level ${q.depth}` : `Level ${q.depth}`}
        {endNote && q.wants_reply ? ' · ✍ typed reply' : ''}
      </div>
      <div className="line-clamp-3 break-words font-medium">{q.text}</div>
      {note && <div className="mt-1 text-[11px] font-semibold text-teal-700">{note}</div>}
    </>
  );

  const classes = `relative mx-auto w-40 rounded-lg p-2 text-left text-xs shadow-sm transition sm:w-44 ${
    isCurrent
      ? 'bg-emerald-50 ring-2 ring-emerald-500'
      : onPath
        ? `bg-white ring-1 ${path ? 'ring-emerald-300' : 'ring-slate-300'}`
        : 'bg-white opacity-40 ring-1 ring-slate-200'
  }`;

  return onSelect ? (
    <button
      type="button"
      onClick={() => onSelect(q.id)}
      aria-current={isCurrent ? 'true' : undefined}
      data-current={isCurrent ? 'true' : undefined}
      className={`${classes} hover:ring-emerald-300`}
    >
      {body}
    </button>
  ) : (
    <div data-current={isCurrent ? 'true' : undefined} className={classes}>
      {body}
    </div>
  );
}

function Branch({ q, ...rest }) {
  const { onSelect, pathOptionIds, optionNote } = rest;
  return (
    <li>
      <QuestionCard q={q} {...rest} path={rest.pathQuestionIds} note={rest.questionNote?.(q)} />
      {q.options.length > 0 && (
        <ul>
          {q.options.map((o) => {
            const taken = pathOptionIds?.has(o.id);
            const dim = pathOptionIds && !taken;
            const note = optionNote?.(o);
            return (
              <li key={o.id}>
                <span
                  className={`inline-block max-w-[9rem] truncate rounded-full px-2.5 py-0.5 text-[11px] font-semibold text-white ${
                    dim ? 'bg-slate-300' : taken ? 'bg-emerald-600 ring-2 ring-emerald-300' : 'bg-teal-700'
                  }`}
                >
                  {o.title}
                  {note && <span className="ml-1 opacity-80">· {note}</span>}
                </span>
                {o.next ? (
                  <ul>
                    <Branch q={o.next} {...rest} />
                  </ul>
                ) : (
                  <ul>
                    <li>
                      {onSelect ? (
                        <button
                          type="button"
                          onClick={() => onSelect(q.id)}
                          title="Select the parent question to add a follow-up"
                          className="mx-auto block w-16 rounded-lg border-2 border-dashed border-slate-300 px-1 py-1 text-xs text-slate-400 hover:border-emerald-400 hover:text-emerald-600"
                        >
                          end
                        </button>
                      ) : (
                        <div
                          className={`mx-auto w-16 rounded-lg border-2 border-dashed px-1 py-1 text-xs ${
                            dim ? 'border-slate-200 text-slate-300' : 'border-slate-300 text-slate-400'
                          }`}
                        >
                          end
                        </div>
                      )}
                    </li>
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </li>
  );
}

export default function FlowTree({ root, currentLabel = 'You are here', ...rest }) {
  const box = useRef(null);
  const [full, setFull] = useState(false);
  const [zoom, setZoom] = useState(1);
  const tuning = useRef(false);
  const currentId = rest.currentId;

  // The tree can be wider than the screen. Centre the view on the current question
  // (or the middle of the tree) instead of starting at an empty left edge.
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    if (tuning.current) {
      tuning.current = false;
      return;
    }
    const target = el.querySelector('[data-current="true"]');
    let left = (el.scrollWidth - el.clientWidth) / 2;
    if (target) {
      const t = target.getBoundingClientRect();
      const c = el.getBoundingClientRect();
      left = el.scrollLeft + (t.left + t.width / 2) - (c.left + el.clientWidth / 2);
    }
    el.scrollTo({ left: Math.max(0, left), behavior: 'smooth' });
  }, [root?.id, currentId, full, zoom]);

  const clamp = (z) => Math.min(1.5, Math.max(0.15, Math.round(z * 100) / 100));
  // Shrink until the whole tree fits the visible area (never enlarge past 100%).
  const fit = () => {
    const el = box.current;
    if (!el) return;
    const natural = el.scrollWidth / zoom;
    const next = clamp(Math.min(1, (el.clientWidth - 8) / natural));
    tuning.current = true;
    setZoom(next);
    el.scrollTo({ left: 0 });
  };

  // Full screen: Esc closes it, and the page behind stops scrolling.
  useEffect(() => {
    if (!full) return undefined;
    const onKey = (e) => e.key === 'Escape' && setFull(false);
    document.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
    };
  }, [full]);

  if (!root) return null;

  const tree = (
    <div style={{ zoom }}>
      <ul className="w-max min-w-full">
        <Branch q={root} currentLabel={currentLabel} {...rest} />
      </ul>
    </div>
  );

  const zoomBar = (
    <div className="flex items-center gap-1" role="group" aria-label="Zoom">
      <Button variant="secondary" className="!px-3 !py-1.5" aria-label="Zoom out" onClick={() => setZoom((z) => clamp(z - 0.15))}>
        −
      </Button>
      <span className="w-12 text-center text-xs font-semibold tabular-nums">{Math.round(zoom * 100)}%</span>
      <Button variant="secondary" className="!px-3 !py-1.5" aria-label="Zoom in" onClick={() => setZoom((z) => clamp(z + 0.15))}>
        +
      </Button>
      <Button variant="secondary" className="!py-1.5" onClick={fit}>
        Fit all
      </Button>
      <Button variant="secondary" className="!py-1.5" onClick={() => setZoom(1)}>
        100%
      </Button>
    </div>
  );

  if (full) {
    return (
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Flow diagram, full screen"
        className="fixed inset-0 z-[60] flex flex-col bg-white"
      >
        <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 pb-3 pt-[max(0.75rem,env(safe-area-inset-top))]">
          <h3 className="text-base font-bold">Flow diagram</h3>
          {zoomBar}
          <Button variant="secondary" onClick={() => setFull(false)} aria-label="Close full screen">
            ✕ Close
          </Button>
        </div>
        <div ref={box} className="flow-tree min-h-0 flex-1 overflow-auto p-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
          {tree}
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-end gap-2">
        {zoomBar}
        <Button variant="secondary" className="!py-1.5" onClick={() => setFull(true)}>
          ⛶ Full screen
        </Button>
      </div>
      <div ref={box} className="flow-tree overflow-x-auto pb-3">
        {tree}
      </div>
    </div>
  );
}
