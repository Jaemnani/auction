// 국토부 실거래가 OpenAPI 프록시 (서버 전용)
// data.go.kr key를 클라이언트에 노출하지 않도록 Next.js Route에서 호출.
// 호출 패턴: /api/molit-deals?type=apt&lawd_cd=11680&deal_ymd=202604

import { NextResponse } from "next/server";

const ENDPOINTS: Record<string, string> = {
  // 아파트 매매 (기본)
  apt:      "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade",
  // 아파트 매매 상세 (지번/등기일자 등 더 많은 필드)
  apt_dev:  "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev",
  // 아파트 분양권 전매
  apt_resale: "https://apis.data.go.kr/1613000/RTMSDataSvcSilvTrade/getRTMSDataSvcSilvTrade",
  // 연립/다세대 매매
  rh:       "https://apis.data.go.kr/1613000/RTMSDataSvcRHTrade/getRTMSDataSvcRHTrade",
  // 단독/다가구 매매
  sh:       "https://apis.data.go.kr/1613000/RTMSDataSvcSHTrade/getRTMSDataSvcSHTrade",
  // 오피스텔 매매
  offi:     "https://apis.data.go.kr/1613000/RTMSDataSvcOffiTrade/getRTMSDataSvcOffiTrade",
  // 토지 매매
  land:     "https://apis.data.go.kr/1613000/RTMSDataSvcLandTrade/getRTMSDataSvcLandTrade",
  // 상업업무용 매매 (근린생활시설/사무실/상가)
  nrg:      "https://apis.data.go.kr/1613000/RTMSDataSvcNrgTrade/getRTMSDataSvcNrgTrade",
  // 공장 및 창고 등 매매
  indu:     "https://apis.data.go.kr/1613000/RTMSDataSvcInduTrade/getRTMSDataSvcInduTrade",
};

export async function GET(req: Request) {
  const url = new URL(req.url);
  const type = url.searchParams.get("type") || "apt";
  const lawdCd = url.searchParams.get("lawd_cd"); // 5자리 법정동 코드 (sgg_code 5자리 그대로 사용)
  const dealYmd = url.searchParams.get("deal_ymd"); // YYYYMM
  const numOfRows = url.searchParams.get("num_of_rows") || "50";

  const endpoint = ENDPOINTS[type];
  if (!endpoint) {
    return NextResponse.json({ error: `unknown type: ${type}` }, { status: 400 });
  }
  if (!lawdCd || !dealYmd) {
    return NextResponse.json(
      { error: "lawd_cd, deal_ymd required" }, { status: 400 },
    );
  }

  const apiKey = process.env.DATA_GO_KR_API_KEY;
  if (!apiKey) {
    return NextResponse.json(
      { error: "DATA_GO_KR_API_KEY not set" }, { status: 500 },
    );
  }

  // 숫자 검증 — numOfRows는 외부 URL에 concat되므로 파라미터 오염 방지차 정수만.
  const rows = Math.min(1000, Math.max(1, Number(numOfRows) || 50));

  // ServiceKey는 이미 URL-encoded form이므로 raw concat (재인코딩하면 망가짐).
  // _type=json — 신형 RTMSDataSvc 엔드포인트는 기본 XML, 이 파라미터로 JSON 강제.
  const target = `${endpoint}?serviceKey=${apiKey}`
    + `&pageNo=1&numOfRows=${rows}`
    + `&LAWD_CD=${encodeURIComponent(lawdCd)}`
    + `&DEAL_YMD=${encodeURIComponent(dealYmd)}`
    + `&_type=json`;

  try {
    const r = await fetch(target, {
      headers: { Accept: "application/json" },
      next: { revalidate: 3600 },
    });
    if (!r.ok) {
      return NextResponse.json(
        { error: `upstream ${r.status}` }, { status: 502 },
      );
    }
    const body = await r.json();
    // OpenAPI 표준 응답: { response: { header, body: { items: { item: [...] } } } }
    const raw = body?.response?.body?.items?.item;
    const list = Array.isArray(raw) ? raw : raw ? [raw] : [];
    // 신형 RTMSDataSvc는 영문 필드명 + 유형별 차이 → 유형 무관 형태로 정규화.
    const items = list.map(normalizeDeal);
    return NextResponse.json({
      total: body?.response?.body?.totalCount ?? 0,
      items,
    });
  } catch (e) {
    return NextResponse.json(
      { error: String(e) }, { status: 500 },
    );
  }
}

/** RTMSDataSvc 응답(영문 필드) → 유형 무관 정규화 형태.
 *  유형별 차이를 폴백 체인으로 흡수:
 *   이름:   aptNm(아파트) / offiNm(오피) / mhouseNm(연립) / houseType(단독) /
 *           buildingType(상업·공장) / 없으면 법정동(umdNm)
 *   면적:   excluUseAr(전용) / dealArea(토지) / totalFloorAr(단독 연면적) /
 *           buildingAr(상업 건물) / landAr(연립 대지권)
 */
function normalizeDeal(d: Record<string, unknown>) {
  const s = (v: unknown) => (v == null ? "" : String(v).trim());
  const num = (v: unknown) => {
    const n = parseFloat(s(v).replace(/,/g, ""));
    return Number.isFinite(n) ? n : null;
  };
  return {
    name: s(d.aptNm) || s(d.offiNm) || s(d.mhouseNm) || s(d.houseType)
      || s(d.buildingType) || s(d.umdNm),
    umd: s(d.umdNm),
    jibun: s(d.jibun),
    year: s(d.dealYear),
    month: s(d.dealMonth),
    day: s(d.dealDay),
    // 거래금액(만원). 영문 dealAmount는 " 50,000" 형태 → 정수 만원.
    amountManwon: num(d.dealAmount),
    // 면적(㎡)
    area: num(d.excluUseAr) ?? num(d.dealArea) ?? num(d.totalFloorAr)
      ?? num(d.buildingAr) ?? num(d.landAr),
    floor: s(d.floor) || null,
  };
}
