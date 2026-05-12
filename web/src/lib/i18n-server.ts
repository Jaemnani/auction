import "server-only";

import { headers } from "next/headers";
import { localeFromPath, makeT, type T } from "./i18n";

/**
 * Server component용 — middleware의 x-pathname 헤더로 locale 결정.
 */
export async function getT(): Promise<T> {
  const h = await headers();
  const path = h.get("x-pathname") ?? h.get("x-invoke-path") ?? "/";
  return makeT(localeFromPath(path));
}
