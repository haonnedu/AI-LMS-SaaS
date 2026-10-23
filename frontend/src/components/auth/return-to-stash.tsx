"use client";
import { useEffect } from "react";
import { stashReturnTo } from "@/lib/client/return-to";
export function ReturnToStash({ value }: { value: string }) {
  useEffect(() => { stashReturnTo(value); }, [value]);
  return null;
}
