import { createClient } from "@supabase/supabase-js";

// server-only — 이 모듈은 client component 에서 import 안 함 (검증됨).
// NEXT_PUBLIC_ 접두사 없는 키 우선 사용 (anon key 도 client 번들에서 제외 → 보안 ↑).
// Vercel 등에 NEXT_PUBLIC_* 만 set 되어 있는 환경 호환 위해 fallback 유지.
const url = process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL;
const anonKey = process.env.SUPABASE_KEY
  || process.env.SUPABASE_ANON_KEY
  || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

if (!url || !anonKey) {
  throw new Error(
    "Supabase keys missing — set SUPABASE_URL + SUPABASE_KEY in .env.local "
    + "(or NEXT_PUBLIC_SUPABASE_URL + NEXT_PUBLIC_SUPABASE_ANON_KEY for Vercel)"
  );
}

export const supabase = createClient(url, anonKey, {
  auth: { persistSession: false },
});

/** Supabase Storage 공개 URL — anon 읽기 정책이 있어야 동작. */
export function publicStorageUrl(bucket: string, path: string): string {
  return `${url}/storage/v1/object/public/${bucket}/${path}`;
}

export const JP_PHOTO_BUCKET = "jp-auction-photos";
