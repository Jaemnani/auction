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

  // ServiceKey는 이미 URL-encoded form이므로 raw concat (재인코딩하면 망가짐)
  const target = `${endpoint}?serviceKey=${apiKey}`
    + `&pageNo=1&numOfRows=${numOfRows}`
    + `&LAWD_CD=${encodeURIComponent(lawdCd)}`
    + `&DEAL_YMD=${encodeURIComponent(dealYmd)}`;

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
    const items = body?.response?.body?.items?.item;
    return NextResponse.json({
      total: body?.response?.body?.totalCount ?? 0,
      items: Array.isArray(items) ? items : items ? [items] : [],
    });
  } catch (e) {
    return NextResponse.json(
      { error: String(e) }, { status: 500 },
    );
  }
}
