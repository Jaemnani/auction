// 경량 i18n 모듈 — locale은 path 기반 (`/jp/*` → ja, 그 외 → ko)으로 자동 결정.
//
// 사용 예:
//   const t = useT();                       // client component (locale = current pathname)
//   const t = await getT();                 // server component
//   const t = makeT("ja");                  // 명시적
//   t("filter.pref")                        // → "都道府県" (ja) / "도도부현" (ko)
//
// 향후 next-intl 마이그레이션 시: messages 구조 그대로 + t() 호출 사이트만 useTranslations로 치환.

// 순수 i18n 모듈 — server/client 양쪽에서 안전하게 import.
// server hook → lib/i18n-server.ts (getT)
// client hook → lib/i18n-client.ts (useT)

export const LOCALES = ["ko", "ja"] as const;
export type Locale = (typeof LOCALES)[number];

export type MessageDict = {
  [key: string]: string | MessageDict;
};

// path 기반 locale 결정 — 한 곳에서 룰 관리.
export function localeFromPath(pathname: string | null | undefined): Locale {
  if (!pathname) return "ko";
  return pathname === "/jp" || pathname.startsWith("/jp/") ? "ja" : "ko";
}

// ====================================================================
// 메시지 — 일단 inline. 키가 늘어나면 별도 messages/{ko,ja}.json으로 분리.
// ====================================================================
const MESSAGES: Record<Locale, MessageDict> = {
  ko: {
    nav: { list: "목록", map: "지도" },
    common: {
      all: "전체",
      apply: "검색",
      reset: "초기화",
      search: "검색",
      detail: "상세",
      back_to_list: "← 목록",
    },
    filter: {
      pref: "도도부현",
      court: "법원",
      sale_cls: "종별",
      status: "상태",
      case_kind: "사건 종류",
      price_min: "가격 최저",
      price_max: "가격 최고",
      kw: "주소 / 사건번호",
      yen10k: "⚠ 1万円 함정만",
      has_pdf: "📑 三点セット 보유",
      with_geo: "🗺 좌표 보유만",
    },
    list: {
      photo: "사진",
      case_court: "사건번호 · 법원",
      sale_std: "売却基準",
      area: "면적",
      dong_ho: "동·호수",
      bid_period: "入札期間",
      address: "所在地",
      no_match: "조건에 맞는 매물이 없습니다.",
      reset_filter: "필터 초기화",
    },
    map: {
      title: "매물 지도",
      marker_count: "매물",
      circle_select: "⭕ 원형 영역 선택",
      circle_drag: "📍 드래그로 원 그리기",
      circle_clear: "✕ 원형 선택 해제",
      auto_refresh: "지도 이동 시 자동 새로고침",
    },
    detail: {
      area: "면적",
      location: "위치",
      photos: "사진",
      schedule: "매각 일정",
      property_spec: "물건 명세",
      bit_original: "BIT 원본",
      three_set_pdf: "📑 三点セット PDF 다운로드",
      market_history: "매각기일 이력",
    },
  },
  ja: {
    nav: { list: "リスト", map: "地図" },
    common: {
      all: "すべて",
      apply: "検索",
      reset: "リセット",
      search: "検索",
      detail: "詳細",
      back_to_list: "← リスト",
    },
    filter: {
      pref: "都道府県",
      court: "裁判所",
      sale_cls: "種別",
      status: "状態",
      case_kind: "事件種類",
      price_min: "価格 最低",
      price_max: "価格 最高",
      kw: "住所 / 事件番号",
      yen10k: "⚠ 1万円トラップのみ",
      has_pdf: "📑 三点セット あり",
      with_geo: "🗺 座標あり のみ",
    },
    list: {
      photo: "写真",
      case_court: "事件番号 · 裁判所",
      sale_std: "売却基準",
      area: "面積",
      dong_ho: "号室/棟",
      bid_period: "入札期間",
      address: "所在地",
      no_match: "条件に一致する物件はありません。",
      reset_filter: "フィルタをリセット",
    },
    map: {
      title: "物件マップ",
      marker_count: "物件",
      circle_select: "⭕ 円形範囲選択",
      circle_drag: "📍 ドラッグで円を描く",
      circle_clear: "✕ 円形選択を解除",
      auto_refresh: "地図移動時に自動更新",
    },
    detail: {
      area: "面積",
      location: "位置",
      photos: "写真",
      schedule: "売却スケジュール",
      property_spec: "物件明細",
      bit_original: "BIT 元データ",
      three_set_pdf: "📑 三点セット PDF ダウンロード",
      market_history: "売却期日履歴",
    },
  },
};

function pick(dict: MessageDict, path: string): string | undefined {
  let cur: MessageDict | string = dict;
  for (const part of path.split(".")) {
    if (typeof cur !== "object" || cur === null) return undefined;
    cur = (cur as MessageDict)[part];
    if (cur === undefined) return undefined;
  }
  return typeof cur === "string" ? cur : undefined;
}

export type T = (key: string) => string;

/** 명시적 locale로 t() 생성. fallback: ko → key 자체. */
export function makeT(locale: Locale): T {
  return (key: string) =>
    pick(MESSAGES[locale], key)
      ?? pick(MESSAGES.ko, key)
      ?? key;
}

// getT는 lib/i18n-server.ts (next/headers 사용 — server only)
// useT는 lib/i18n-client.ts (next/navigation — client only)
