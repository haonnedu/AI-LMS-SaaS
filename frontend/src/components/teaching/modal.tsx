"use client";
import { useEffect, useRef, type ReactNode } from "react";
import styles from "./teaching.module.css";
/** Native modal <dialog>: focus trap, Esc to close, focus restored on close. */
export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = ref.current;
    const previous = document.activeElement as HTMLElement | null;
    node?.showModal();
    return () => { node?.close(); previous?.focus(); };
  }, []);
  return <dialog ref={ref} className={`modal ${styles.dialog}`} aria-labelledby="modal-title" onCancel={event => { event.preventDefault(); onClose(); }}>
    <h2 id="modal-title">{title}</h2>{children}
  </dialog>;
}
