const KEY = "eduvia:returnTo";
// Only same-site /join/<token> paths are ever stored or followed (no open redirect).
const JOIN = /^\/join\/[A-Za-z0-9_-]{32,128}$/;
export function stashReturnTo(value: string) { if (JOIN.test(value)) sessionStorage.setItem(KEY, value); }
export function takeReturnTo(): string | null {
  const value = sessionStorage.getItem(KEY);
  sessionStorage.removeItem(KEY);
  return value && JOIN.test(value) ? value : null;
}
