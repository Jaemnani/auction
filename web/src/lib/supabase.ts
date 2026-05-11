import { createClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

if (!url || !anonKey) {
  throw new Error("NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY missing");
}

export const supabase = createClient(url, anonKey, {
  auth: { persistSession: false },
});

/** Supabase Storage 공개 URL — anon 읽기 정책이 있어야 동작. */
export function publicStorageUrl(bucket: string, path: string): string {
  return `${url}/storage/v1/object/public/${bucket}/${path}`;
}

export const JP_PHOTO_BUCKET = "jp-auction-photos";
