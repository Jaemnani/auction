import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // dev 서버를 LAN IP로 접속해도 /_next 리소스가 차단되지 않도록 (프로덕션 무영향)
  allowedDevOrigins: ["192.168.50.61"],

  // 지도가 기본 랜딩(/, /jp)이 되면서 목록은 /list, /jp/list 로 이동.
  // 옛 북마크·공유 링크 호환 — 쿼리스트링은 redirect 가 그대로 넘긴다.
  async redirects() {
    return [
      { source: "/map", destination: "/", permanent: true },
      { source: "/jp/map", destination: "/jp", permanent: true },
      // 옛 목록 페이지네이션 링크(/?page=3 등)는 목록으로. page 는 목록 전용 —
      // 지도 필터는 page 를 지운다. sort 등 나머지는 지도도 해석하므로 그대로 둔다.
      { source: "/", has: [{ type: "query", key: "page" }], destination: "/list", permanent: true },
      { source: "/jp", has: [{ type: "query", key: "page" }], destination: "/jp/list", permanent: true },
    ];
  },
};

export default nextConfig;
