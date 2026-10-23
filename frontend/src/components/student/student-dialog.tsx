"use client";
import { useEffect, useId, useRef, type ReactNode } from "react";
import styles from "./student.module.css";
/** Native modal dialog (focus trap, focus restored). `onClose` omitted means it cannot be dismissed (e.g. time is up). */
export function StudentDialog({ title, onClose, children }: { title: string; onClose?: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  useEffect(() => {
    const node = ref.current;
    const previous = document.activeElement as HTMLElement | null;
    node?.showModal();
    return () => { node?.close(); previous?.focus(); };
  }, []);
  return <dialog ref={ref} className={`modal ${styles.dialog}`} aria-labelledby={id} onCancel={event => { event.preventDefault(); onClose?.(); }}>
    <h2 id={id}>{title}</h2>{children}
  </dialog>;
}
