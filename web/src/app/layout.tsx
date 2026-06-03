import type { Metadata } from "next";
import Link from "next/link";
import { Barlow, JetBrains_Mono, Noto_Sans_JP } from "next/font/google";
import "./globals.css";
import { AreaUnitProvider } from "@/lib/area-unit";
import { AreaUnitToggle } from "@/components/area-unit-toggle";
import { CountryToggle } from "@/components/country-toggle";
import { PrimaryNav } from "@/components/primary-nav";
import { Container } from "@/app/_components/container";

// DESIGN.md 디스플레이 family — Barlow. weight 3종만 (LCP 보호).
const barlow = Barlow({
  variable: "--font-barlow",
  subsets: ["latin"],
  weight: ["400", "600", "700"],
  display: "swap",
});

const monoFont = JetBrains_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
  display: "swap",
});

// DESIGN.md body fallback — 일본어 본문(/jp/*) 가독성.
// preload: false — 한국 페이지에선 안 쓰니 LCP 보호.
const notoSansJp = Noto_Sans_JP({
  variable: "--font-noto-sans-jp",
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  display: "swap",
  preload: false,
});

export const metadata: Metadata = {
  title: "법원경매 검색",
  description: "courtauction.go.kr 데이터 기반 무료 경매물건 검색",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="ko"
      className={`${barlow.variable} ${monoFont.variable} ${notoSansJp.variable} h-full antialiased`}
    >
      <head>
        {/* Pretendard Variable — 한글 본문. preconnect로 TLS handshake 선행. */}
        <link rel="preconnect" href="https://cdn.jsdelivr.net" crossOrigin="anonymous" />
        <link rel="dns-prefetch" href="https://cdn.jsdelivr.net" />
        <link
          rel="stylesheet"
          href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/variable/pretendardvariable-dynamic-subset.min.css"
        />
      </head>
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <AreaUnitProvider>
        <header className="border-b sticky top-0 z-30 bg-background/85 backdrop-blur supports-[backdrop-filter]:bg-background/70">
          {/* 헤더는 default(1280) — 콘텐츠 양 적어 좁아도 OK */}
          <Container maxW="wide" className="h-14 flex items-center gap-6">
            <Link href="/" className="flex items-baseline gap-2">
              <span className="text-lg font-bold tracking-tight">법원경매</span>
              <span className="text-caption-sm text-text-muted hidden sm:inline">무료 검색</span>
            </Link>
            <PrimaryNav />
            <div className="ml-auto flex items-center gap-2">
              <CountryToggle />
              <AreaUnitToggle />
            </div>
          </Container>
        </header>
        <main className="flex-1 grow w-full">
          {/* main 은 wide(1440) — 일본 매물 테이블 9컬럼·한국 다중 필터 폭 수용.
              헤더/푸터와 폭이 살짝 다르지만 한·일 페이지 폭은 동일. */}
          <Container maxW="wide" className="py-6">
            {children}
          </Container>
        </main>
        <footer className="border-t py-3">
          <Container maxW="wide" className="text-center text-caption-sm text-text-muted">
            데이터: courtauction.go.kr · 본 서비스는 무료 · 공식 사이트 정보를 우선하세요
          </Container>
        </footer>
        </AreaUnitProvider>
      </body>
    </html>
  );
}
