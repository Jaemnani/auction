// BIT 三点セット PDF 다운로드 server proxy.
// 2단계 호출 (확인 POST → 다운로드 GET)을 본 서버에서 대리. 클라이언트 CORS 회피.
//
// 사용:
//   GET /api/jp/pdf/{sale_unit_id}?court_id={5자리}
//
// 흐름:
//   1) GET /  ← BIT 메인 (세션 쿠키 워밍업)
//   2) POST /app/top/pt001/h02 (블록 → 도도부현 선택 페이지)
//   3) POST /app/areaselect/ps002/h05 (세션 + 검색 컨텍스트 확보)
//   4) POST /app/detail/pd001/h03 body=courtId&saleUnitId → "success" 텍스트
//   5) GET /app/detail/pd001/h04?courtId&saleUnitId → PDF binary

import { NextRequest, NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

const BIT_BASE = "https://www.bit.courts.go.jp";
const UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";

const PREFECTURE_BLOCK: Record<string, string> = {
  "91":"01","92":"01","93":"01","94":"01",
  "02":"02","03":"02","04":"02","05":"02","06":"02","07":"02",
  "08":"03","09":"03","10":"03","11":"03","12":"03","13":"03","14":"03",
  "15":"04","16":"04","17":"04","18":"04","19":"04","20":"04",
  "21":"05","22":"05","23":"05","24":"05",
  "25":"06","26":"06","27":"06","28":"06","29":"06","30":"06",
  "31":"07","32":"07","33":"07","34":"07","35":"07",
  "36":"08","37":"08","38":"08","39":"08",
  "40":"09","41":"09","42":"09","43":"09","44":"09","45":"09","46":"09","47":"09",
};

type CookieJar = Map<string, string>;

function mergeCookies(jar: CookieJar, setCookieHeaders: string[]) {
  for (const sc of setCookieHeaders) {
    const eq = sc.indexOf("=");
    const semi = sc.indexOf(";");
    if (eq < 0) continue;
    const name = sc.slice(0, eq).trim();
    const value = sc.slice(eq + 1, semi > 0 ? semi : undefined).trim();
    if (name) jar.set(name, value);
  }
}

function cookieHeader(jar: CookieJar): string {
  return Array.from(jar.entries()).map(([k, v]) => `${k}=${v}`).join("; ");
}

async function bitFetch(
  jar: CookieJar, path: string, init: RequestInit & { referer?: string } = {},
): Promise<Response> {
  const headers: Record<string, string> = {
    "User-Agent": UA,
    "Accept-Language": "ja,ko;q=0.9,en;q=0.8",
    ...(init.headers as Record<string, string> ?? {}),
  };
  if (jar.size > 0) headers["Cookie"] = cookieHeader(jar);
  if (init.referer) headers["Referer"] = `${BIT_BASE}${init.referer}`;
  const r = await fetch(`${BIT_BASE}${path}`, {
    ...init,
    headers,
    redirect: "follow",
    cache: "no-store",
  });
  // Set-Cookie 누적 — Node 18+ getSetCookie 지원
  const setCookies: string[] = r.headers.getSetCookie?.() ?? [];
  if (setCookies.length === 0) {
    const sc = r.headers.get("set-cookie");
    if (sc) mergeCookies(jar, [sc]);
  } else {
    mergeCookies(jar, setCookies);
  }
  return r;
}

export async function GET(
  req: NextRequest,
  ctx: { params: Promise<{ sale_unit_id: string }> },
) {
  const { sale_unit_id } = await ctx.params;
  const url = new URL(req.url);
  let courtId = url.searchParams.get("court_id");
  let prefId: string | null = url.searchParams.get("pref");

  // courtId 없으면 DB에서 lookup
  if (!courtId || !prefId) {
    const { data, error } = await supabase
      .from("jp_properties")
      .select("prefecture_code, jp_cases!inner(jp_courts!inner(code))")
      .eq("sale_unit_id", sale_unit_id)
      .maybeSingle();
    if (error || !data) {
      return NextResponse.json(
        { error: "property not found or DB error", detail: error?.message },
        { status: 404 },
      );
    }
    type Row = {
      prefecture_code: string | null;
      jp_cases: { jp_courts: { code: string | null } | null } | null;
    };
    const row = data as unknown as Row;
    courtId = courtId ?? row.jp_cases?.jp_courts?.code ?? null;
    prefId = prefId ?? row.prefecture_code ?? null;
  }
  if (!courtId) {
    return NextResponse.json({ error: "court_id required" }, { status: 400 });
  }
  if (!prefId) {
    return NextResponse.json({ error: "prefecture not found for property" }, { status: 400 });
  }
  const block = PREFECTURE_BLOCK[prefId];
  if (!block) {
    return NextResponse.json({ error: `unknown prefecture ${prefId}` }, { status: 400 });
  }

  const jar: CookieJar = new Map();

  try {
    // 1) 메인 페이지 (세션 워밍업)
    await bitFetch(jar, "/", { method: "GET" });

    // 2) 블록 선택
    await bitFetch(jar, "/app/top/pt001/h02", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ blockCls: block, tabId: "property" }).toString(),
      referer: "/",
    });

    // 3) 도도부현 검색 — 세션에 검색 컨텍스트 확보
    const searchBody = new URLSearchParams();
    searchBody.set("prefecturesId", prefId);
    searchBody.set("tabId", "property");
    searchBody.set("blockCls", block);
    for (const sc of ["1", "2", "3", "4"]) searchBody.append("saleCls", sc);
    searchBody.set("saleClsSelected", "1,2,3,4");
    searchBody.set("saleStandardAmountCls", "1");
    searchBody.set("currentPage", "1");
    searchBody.set("pageSize", "10");
    searchBody.set("resultListSearchButtonFlag", "0");
    searchBody.set("pageListChangeFlg", "0");
    await bitFetch(jar, "/app/areaselect/ps002/h05", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: searchBody.toString(),
      referer: "/app/top/pt001/h02",
    });

    // 4) 三点セット 확인 POST
    const confirmBody = new URLSearchParams({
      courtId, saleUnitId: sale_unit_id,
    }).toString();
    const confirmRes = await bitFetch(jar, "/app/detail/pd001/h03", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: confirmBody,
      referer: "/app/areaselect/ps002/h05",
    });
    const confirmText = await confirmRes.text();
    if (!/success/.test(confirmText)) {
      return NextResponse.json(
        { error: "BIT 確認 거부", detail: confirmText.slice(0, 200) },
        { status: 502 },
      );
    }

    // 5) PDF 다운로드
    const pdfPath = `/app/detail/pd001/h04?courtId=${encodeURIComponent(courtId)}&saleUnitId=${encodeURIComponent(sale_unit_id)}`;
    const pdfRes = await bitFetch(jar, pdfPath, {
      method: "GET",
      referer: "/app/areaselect/ps002/h05",
    });
    if (!pdfRes.ok) {
      return NextResponse.json(
        { error: `BIT PDF HTTP ${pdfRes.status}` },
        { status: 502 },
      );
    }
    const pdfBuf = await pdfRes.arrayBuffer();

    return new NextResponse(pdfBuf, {
      status: 200,
      headers: {
        "Content-Type": "application/pdf",
        "Content-Disposition": `inline; filename="bit_${sale_unit_id}.pdf"`,
        // BIT가 PDF를 자주 갱신하지 않으니 5분 캐시
        "Cache-Control": "public, max-age=300",
      },
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return NextResponse.json({ error: "proxy failed", detail: msg }, { status: 502 });
  }
}
