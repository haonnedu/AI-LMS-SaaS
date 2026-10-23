"use client";
import { useEffect, useState } from "react";
import type { components } from "@/lib/api/generated";
import { read } from "@/lib/client/api";
import { sortUnits } from "@/lib/client/library";
import styles from "./teaching.module.css";

export type Unit = components["schemas"]["CurriculumUnitDTO"];
export type Subject = components["schemas"]["CurriculumSubjectDTO"];
export const GRADES = Array.from({ length: 12 }, (_, i) => i + 1);
export const dateTime = (value: string | null | undefined) => value ? new Date(value).toLocaleString("vi-VN") : "—";

/** Status label + chip tone. */
export type Tone = "info" | "warn" | "error" | undefined;
export function Chip({ label, tone }: { label: string; tone?: Tone }) { return <span className={styles.chip} data-tone={tone}>{label}</span>; }

/** Units already seen by any picker, so tables can show titles instead of ids. */
const unitCache = new Map<string, Unit>();
export const unitLabel = (id: string | null | undefined) => {
  if (!id) return "—";
  const unit = unitCache.get(id);
  return unit ? `${unit.unitCode} · ${unit.titleVi}` : id.slice(0, 8);
};
export function useSubjects(onError: (e: unknown) => void) {
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let live = true;
    read("/api/backend/curriculum/subjects").then((res: { items: Subject[] }) => { if (live) { setSubjects(res.items); setLoaded(true); } }, (e: unknown) => { if (live) { onError(e); setLoaded(true); } });
    return () => { live = false; };
  }, [onError]);
  return { subjects, loaded };
}
export function useUnits(subjectCode: string, grade: string, onError: (e: unknown) => void) {
  const [units, setUnits] = useState<Unit[]>([]);
  useEffect(() => {
    if (!subjectCode || !grade) return;
    let live = true;
    read(`/api/backend/curriculum/units?subject=${encodeURIComponent(subjectCode)}&grade=${encodeURIComponent(grade)}`).then(
      (res: { items: Unit[] }) => { for (const u of res.items) unitCache.set(u.id, u); if (live) setUnits(sortUnits(res.items)); },
      (e: unknown) => { if (live) onError(e); });
    return () => { live = false; };
  }, [subjectCode, grade, onError]);
  return subjectCode && grade ? units : [];
}

/** Subject -> grade -> unit selects. With `withUnit=false` only subject and grade are chosen. */
export function UnitPicker({ unitId, onUnit, onSubject, withUnit = true, onError, required = false }: {
  unitId?: string; onUnit?: (id: string) => void; onSubject?: (subject: Subject | null, grade: number | null) => void; withUnit?: boolean; onError: (e: unknown) => void; required?: boolean;
}) {
  const { subjects, loaded } = useSubjects(onError);
  const [code, setCode] = useState("");
  const [grade, setGrade] = useState("");
  const units = useUnits(code, grade, onError);
  const change = (nextCode: string, nextGrade: string) => {
    setCode(nextCode); setGrade(nextGrade); onUnit?.("");
    onSubject?.(subjects.find(s => s.code === nextCode) || null, nextGrade ? Number(nextGrade) : null);
  };
  return <div className={styles.tagGrid}>
    <label className={styles.field}><span>Môn học{required ? " *" : ""}</span>
      <select value={code} onChange={e => change(e.target.value, "")} disabled={!loaded} required={required}>
        <option value="">Chọn môn học</option>{subjects.map(s => <option key={s.id} value={s.code}>{s.nameVi}</option>)}
      </select></label>
    <label className={styles.field}><span>Lớp{required ? " *" : ""}</span>
      <select value={grade} onChange={e => change(code, e.target.value)} disabled={!code} required={required}>
        <option value="">Chọn lớp</option>{GRADES.map(g => <option key={g} value={g}>Lớp {g}</option>)}
      </select></label>
    {withUnit && <label className={styles.field}><span>Đơn vị kiến thức</span>
      <select value={unitId || ""} onChange={e => onUnit?.(e.target.value)} disabled={!units.length}>
        <option value="">{units.length || !code || !grade ? "Không chọn" : "Không có đơn vị"}</option>
        {unitId && !units.some(u => u.id === unitId) && <option value={unitId}>{unitLabel(unitId)}</option>}
        {units.map(u => <option key={u.id} value={u.id}>{u.unitCode} · {u.titleVi}</option>)}
      </select></label>}
  </div>;
}
