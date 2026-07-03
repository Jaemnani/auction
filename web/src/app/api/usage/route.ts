import { NextResponse } from "next/server";
import { fetchUsageList } from "@/lib/queries";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const level = Number(url.searchParams.get("level") ?? "1") as 1 | 2 | 3;
  const parent = url.searchParams.get("parent") ?? undefined;
  const rows = await fetchUsageList(level, parent);
  // 용도 코드는 거의 불변 → 브라우저/CDN 캐시 허용 (사이드바 반복 호출 절감).
  return NextResponse.json(rows, {
    headers: { "Cache-Control": "public, max-age=3600, s-maxage=86400" },
  });
}
