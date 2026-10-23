"use client";
import Link from "next/link";
export default function ErrorPage({ reset }: { reset: () => void }) {
  return <section role="alert"><h1>Chưa thể tải trang</h1><p>Dịch vụ tạm thời không khả dụng. Vui lòng thử lại.</p><button className="button button-primary" onClick={reset}>Thử lại</button><Link href="/login">Về đăng nhập</Link></section>;
}
