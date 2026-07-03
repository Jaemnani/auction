import { NextResponse } from "next/server";
import { fetchSggList } from "@/lib/queries";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const sd = url.searchParams.get("sd") ?? undefined;
  const rows = await fetchSggList(sd);
  // 시군구 코드는 거의 불변 → 브라우저/CDN 캐시 허용 (시·도 변경 시 반복 호출 절감).
  return NextResponse.json(rows, {
    headers: { "Cache-Control": "public, max-age=3600, s-maxage=86400" },
  });
}
