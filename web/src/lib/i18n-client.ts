"use client";

import { usePathname } from "next/navigation";
import { localeFromPath, makeT, type T } from "./i18n";

/** Client component hook — usePathname 기반 locale + t(). */
export function useT(): T {
  const pathname = usePathname();
  return makeT(localeFromPath(pathname));
}
