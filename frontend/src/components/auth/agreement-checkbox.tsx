"use client";
import Link from "next/link";

/** Required acceptance of the user agreement + privacy notice (decision 0009). Links open in a new tab so the form keeps its state. */
export function AgreementCheckbox({ checked, onChange, disabled }: { checked: boolean; onChange: (checked: boolean) => void; disabled?: boolean }) {
  return <label style={{ display: "flex", flexDirection: "row", gap: 10, alignItems: "flex-start", lineHeight: 1.5 }}>
    <input type="checkbox" required checked={checked} disabled={disabled} onChange={event => onChange(event.target.checked)} style={{ width: 20, height: 20, marginTop: 2, flexShrink: 0 }} />
    <span>Tôi đã đọc và đồng ý với <Link href="/terms" target="_blank" rel="noopener noreferrer">Thỏa thuận người dùng</Link> và <Link href="/privacy" target="_blank" rel="noopener noreferrer">Thông báo quyền riêng tư</Link></span>
  </label>;
}
