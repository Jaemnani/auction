import { NextResponse, type NextRequest } from "next/server";

/**
 * Server component에서 현재 path를 얻기 위한 헤더 부착.
 * (Next.js 16의 server component는 `headers()`로 클라이언트 헤더만 받을 수 있고
 * 현재 라우트 path를 직접 못 얻음 → middleware에서 `x-pathname`을 명시 부착.)
 *
 * lib/i18n.ts의 getT()가 이 헤더로 locale을 결정함.
 */
export function middleware(req: NextRequest) {
  const headers = new Headers(req.headers);
  headers.set("x-pathname", req.nextUrl.pathname);
  return NextResponse.next({ request: { headers } });
}

export const config = {
  matcher: [
    // _next/* 와 favicon 제외한 모든 라우트
    "/((?!_next/static|_next/image|favicon.ico).*)",
  ],
};
