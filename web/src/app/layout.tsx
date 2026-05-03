import type { Metadata } from "next";
import Link from "next/link";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
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
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <header className="border-b sticky top-0 z-30 bg-background/95 backdrop-blur">
          <div className="mx-auto max-w-[1600px] px-4 h-14 flex items-center gap-6">
            <Link href="/" className="font-semibold">법원경매 검색</Link>
            <nav className="flex items-center gap-4 text-sm text-muted-foreground">
              <Link href="/" className="hover:text-foreground">목록</Link>
              <Link href="/map" className="hover:text-foreground">지도</Link>
            </nav>
          </div>
        </header>
        <main className="flex-1 mx-auto w-full max-w-[1600px] px-4 py-6">
          {children}
        </main>
        <footer className="border-t py-3 text-center text-xs text-muted-foreground">
          데이터: courtauction.go.kr · 본 서비스는 무료 · 공식 사이트 정보를 우선하세요
        </footer>
      </body>
    </html>
  );
}
