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

// 사진 공개 URL 베이스.
//  - self-host (MinIO): STORAGE_PUBLIC_URL = https://files.<domain>  → {base}/{bucket}/{path}
//  - Supabase (구): STORAGE_PUBLIC_URL 없으면 기존 형식으로 fallback.
const storagePublicBase =
  process.env.STORAGE_PUBLIC_URL || process.env.NEXT_PUBLIC_STORAGE_PUBLIC_URL;

/** 사진 공개 URL. MinIO(self-host) 우선, 없으면 Supabase Storage 형식 fallback. */
export function publicStorageUrl(bucket: string, path: string): string {
  if (storagePublicBase) {
    return `${storagePublicBase.replace(/\/$/, "")}/${bucket}/${path}`;
  }
  // Supabase Storage 형식 (STORAGE_PUBLIC_URL 미설정 시)
  return `${url}/storage/v1/object/public/${bucket}/${path}`;
}

export const PHOTO_BUCKET = "auction-photos";
export const JP_PHOTO_BUCKET = "jp-auction-photos";
