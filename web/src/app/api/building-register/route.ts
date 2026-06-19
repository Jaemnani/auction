// 건축HUB 건축물대장 표제부 프록시 (서버 전용) — data.go.kr key 숨김.
// 호출: /api/building-register?sigungu_cd=41570&bjdong_cd=10800&bun=0147&ji=0000
//
// 표제부(getBrTitleInfo): 건물명·주용도·준공일·층수·연면적·세대수·구조 등.
// 주의: data.go.kr ServiceKey는 이미 URL-encoded → raw concat (재인코딩 금지).
//       응답은 _type=json으로 강제. 필드명은 KR 환경에서 표본 검증 권장.

import { NextResponse } from "next/server";

const ENDPOINT =
  "https://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const sigunguCd = url.searchParams.get("sigungu_cd"); // 5자리 (sd+sgg)
  const bjdongCd = url.searchParams.get("bjdong_cd");   // 5자리 (읍면동3+리2)
  const bun = url.searchParams.get("bun");              // 본번 4자리
  const ji = url.searchParams.get("ji");                // 부번 4자리
  const platGbCd = url.searchParams.get("plat_gb_cd") || "0"; // 0=대지 1=산

  if (!sigunguCd || !bjdongCd || !bun) {
    return NextResponse.json(
      { error: "sigungu_cd, bjdong_cd, bun required" }, { status: 400 },
    );
  }
  const apiKey = process.env.DATA_GO_KR_API_KEY;
  if (!apiKey) {
    return NextResponse.json({ error: "DATA_GO_KR_API_KEY not set" }, { status: 500 });
  }

  const target = `${ENDPOINT}?serviceKey=${apiKey}`
    + `&sigunguCd=${encodeURIComponent(sigunguCd)}`
    + `&bjdongCd=${encodeURIComponent(bjdongCd)}`
    + `&platGbCd=${encodeURIComponent(platGbCd)}`
    + `&bun=${encodeURIComponent(bun)}`
    + `&ji=${encodeURIComponent(ji || "0000")}`
    + `&numOfRows=10&pageNo=1&_type=json`;

  try {
    const r = await fetch(target, {
      headers: { Accept: "application/json" },
      next: { revalidate: 86400 }, // 건축물대장은 자주 안 바뀜 → 1일 캐싱
    });
    if (!r.ok) {
      return NextResponse.json({ error: `upstream ${r.status}` }, { status: 502 });
    }
    const body = await r.json();
    const raw = body?.response?.body?.items?.item;
    const list = Array.isArray(raw) ? raw : raw ? [raw] : [];
    return NextResponse.json({
      total: body?.response?.body?.totalCount ?? 0,
      items: list.map(normalizeTitle),
    });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}

/** 표제부 응답 → 핵심 필드 정규화 (없으면 빈 문자열). raw도 함께 보존. */
function normalizeTitle(d: Record<string, unknown>) {
  const s = (v: unknown) => (v == null ? "" : String(v).trim());
  return {
    name: s(d.bldNm),
    mainPurpose: s(d.mainPurpsCdNm),
    etcPurpose: s(d.etcPurps),
    structure: s(d.strctCdNm),
    useApprovalDay: s(d.useAprDay), // YYYYMMDD
    groundFloors: s(d.grndFlrCnt),
    undergroundFloors: s(d.ugrndFlrCnt),
    totalArea: s(d.totArea),
    archArea: s(d.archArea),
    platArea: s(d.platArea),
    bcRat: s(d.bcRat),  // 건폐율
    vlRat: s(d.vlRat),  // 용적률
    households: s(d.hhldCnt),
    families: s(d.fmlyCnt),
    hoCnt: s(d.hoCnt),
    height: s(d.heit),
    regKind: s(d.regstrKindCdNm), // 일반/집합
    regGb: s(d.regstrGbCdNm),
    platPlc: s(d.platPlc),
    raw: d,
  };
}
