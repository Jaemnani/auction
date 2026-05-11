import { NextResponse } from "next/server";
import { fetchPropertiesForMap, type Bbox } from "@/lib/queries";
import { parseFiltersFromSearchParams } from "@/lib/url";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const sp = Object.fromEntries(url.searchParams.entries());
  const filters = parseFiltersFromSearchParams(sp);

  // bbox는 별도 처리
  const num = (k: string) => {
    const v = url.searchParams.get(k);
    return v ? Number(v) : null;
  };
  const minLng = num("min_lng");
  const minLat = num("min_lat");
  const maxLng = num("max_lng");
  const maxLat = num("max_lat");
  const max = Math.min(1000, Math.max(50, num("max") ?? 1000));

  let bbox: Bbox | undefined;
  if (
    minLng != null && minLat != null && maxLng != null && maxLat != null
    && !isNaN(minLng) && !isNaN(minLat) && !isNaN(maxLng) && !isNaN(maxLat)
  ) {
    bbox = { minLng, minLat, maxLng, maxLat };
  }

  try {
    const rows = await fetchPropertiesForMap(filters, max, bbox);
    return NextResponse.json({ rows, count: rows.length, bbox });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
