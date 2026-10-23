"use client";
import { useRef, type KeyboardEvent } from "react";
import styles from "./teaching.module.css";
export const tabId = (prefix: string, id: string) => `${prefix}-tab-${id}`;
export const panelId = (prefix: string, id: string) => `${prefix}-panel-${id}`;
/** Accessible tablist (roving tabindex, arrow/Home/End keys). Callers render the matching role="tabpanel" with panelId/tabId. */
export function Tabs({ prefix, label, tabs, active, onChange }: { prefix: string; label: string; tabs: { id: string; label: string }[]; active: string; onChange: (id: string) => void }) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  function onKey(event: KeyboardEvent, index: number) {
    let next = -1;
    if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = tabs.length - 1;
    if (next < 0) return;
    event.preventDefault();
    onChange(tabs[next].id);
    refs.current[tabs[next].id]?.focus();
  }
  return <div role="tablist" aria-label={label} className={styles.tabs}>{tabs.map((tab, index) =>
    <button key={tab.id} ref={node => { refs.current[tab.id] = node; }} type="button" role="tab" id={tabId(prefix, tab.id)} aria-selected={active === tab.id} aria-controls={panelId(prefix, tab.id)} tabIndex={active === tab.id ? 0 : -1}
      className={styles.tab} onClick={() => onChange(tab.id)} onKeyDown={event => onKey(event, index)}>{tab.label}</button>)}</div>;
}
