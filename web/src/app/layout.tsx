import type { Metadata } from "next";
import Link from "next/link";
import { Barlow, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { AreaUnitProvider } from "@/lib/area-unit";
import { AreaUnitToggle } from "@/components/area-unit-toggle";
import { CountryToggle } from "@/components/country-toggle";
import { PrimaryNav } from "@/components/primary-nav";

// aib.vote와 동일한 영문/숫자 폰트 (한글은 Pretendard Variable, globals.css에서 import)
const barlow = Barlow({
  variable: "--font-barlow",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  display: "swap",
});

const monoFont = JetBrains_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  display: "swap",
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
      className={`${barlow.variable} ${monoFont.variable} h-full antialiased`}
    >
      <head>
        {/* Pretendard Variable — 한글 본문 (aib.vote와 동일) */}
        <link
          rel="stylesheet"
          href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/variable/pretendardvariable-dynamic-subset.min.css"
        />
      </head>
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <AreaUnitProvider>
        <header className="border-b sticky top-0 z-30 bg-background/85 backdrop-blur supports-[backdrop-filter]:bg-background/70">
          <div className="mx-auto max-w-[1600px] px-4 h-14 flex items-center gap-6">
            <Link href="/" className="flex items-baseline gap-2">
              <span className="text-lg font-bold tracking-tight">법원경매</span>
              <span className="text-xs text-muted-foreground hidden sm:inline">무료 검색</span>
            </Link>
            <PrimaryNav />
            <div className="ml-auto flex items-center gap-2">
              <CountryToggle />
              <AreaUnitToggle />
            </div>
          </div>
        </header>
        <main className="flex-1 mx-auto w-full max-w-[1600px] px-4 py-6">
          {children}
        </main>
        <footer className="border-t py-3 text-center text-xs text-muted-foreground">
          데이터: courtauction.go.kr · 본 서비스는 무료 · 공식 사이트 정보를 우선하세요
        </footer>
        </AreaUnitProvider>
      </body>
    </html>
  );
}
