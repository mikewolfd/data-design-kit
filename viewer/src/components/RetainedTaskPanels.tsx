import {
  Children,
  cloneElement,
  isValidElement,
  useState,
  type ReactElement,
  type ReactNode,
} from 'react';

type Panel = { key: string; children: ReactNode };
const MAX_RETAINED_PANELS = 6;

/** A research task outlives its visible tab. Catalog identity owns this component's lifetime. */
export function RetainedTaskPanels({
  taskKey,
  tab,
  children,
  active: parentActive = true,
}: {
  taskKey: string;
  tab: string;
  children: ReactNode;
  active?: boolean;
}) {
  const [panels, setPanels] = useState<Panel[]>([]);
  const [lastKey, setLastKey] = useState('');
  const [evicted, setEvicted] = useState(false);
  const retain = ['Data', 'Query', 'Connections'].includes(tab);
  // Derive retained context at the navigation boundary, before painting the destination.
  if (lastKey !== taskKey) {
    if (retain) {
      const previous = panels.filter((panel) => panel.key !== taskKey);
      const existing = panels.find((panel) => panel.key === taskKey);
      setEvicted(evicted || previous.length >= MAX_RETAINED_PANELS);
      setPanels([
        ...previous.slice(-(MAX_RETAINED_PANELS - 1)),
        existing ?? { key: taskKey, children },
      ]);
    }
    setLastKey(taskKey);
  }
  return (
    <>
      {evicted && (
        <p className="muted task-retention-note" role="status">
          This session keeps the six most recent data and query views. Older views reopen without
          their previous draft or records.
        </p>
      )}
      {(retain ? panels : [...panels, { key: taskKey, children }]).map((panel) => {
        const selected = panel.key === taskKey;
        const active = selected && parentActive;
        const content = selected ? children : panel.children;
        return (
          <div
            key={panel.key}
            role="tabpanel"
            tabIndex={active ? 0 : -1}
            aria-labelledby={active ? `tab-${tab}` : undefined}
            id={active ? `panel-${tab}` : undefined}
            className="tab-content"
            hidden={!active}
            inert={!active}
          >
            {Children.map(content, (child) =>
              isValidElement(child)
                ? cloneElement(child as ReactElement<{ active?: boolean }>, { active })
                : child,
            )}
          </div>
        );
      })}
    </>
  );
}
