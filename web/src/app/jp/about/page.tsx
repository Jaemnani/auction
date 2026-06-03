import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

export const metadata = {
  title: "일본 BIT — 한·일 비교 / 로드맵",
  description: "BIT 정찰 결과 + 한국 vs 일본 경매제도 비교 + 로드맵",
};

const COMPARE = [
  ["평가 주체", "감정평가사 → 법원", "부동산감정사 → 법원"],
  ["평가액 명칭", "감정가", "売却基準価額(매각기준가액)"],
  ["최저 입찰가", "감정가 (1회차)", "買受可能価額 = 매각기준 × 80%"],
  ["1회차 시작가", "감정가 100%", "감정가 대비 ~70~80% 수준"],
  ["유찰 시 가격", "1회 유찰 시 자동 30% (서울 등 20%)", "자동 차감 없음. 미낙찰 시 평가 재조정"],
  ["유찰 횟수 한도", "사실상 없음 (7회 유찰 사례)", "보통 3회. 그 후 절차 정지"],
  ["입찰 보증금", "최저가의 10% (특별 시 20%)", "매각기준가액의 20%"],
  ["결정 자료", "매각물건명세서·현황조사서·감정평가서", "三点セット — 物件明細書·現況調査報告書·不動産評価書"],
  ["사건번호", "2024타경5532", "令和○○年(ケ)○○号 / (ヌ)"],
  ["사이트 형식", "WebSquare RIA (JSON)", "Java Struts (HTML)"],
  ["통합 사이트", "courtauction.go.kr", "bit.courts.go.jp"],
];

const JP_FEATURES = [
  { title: "1万円 함정 매물 경고", desc: "매각기준가액이 비정상적으로 낮은 매물(예: 10,000円) 자동 검출. 관리비·수선적립금 체납 가능성 경고" },
  { title: "삼점세트 LLM 요약", desc: "BIT는 개인정보 마스킹으로 법원 직접 열람을 강제 — 보조 도구가 PDF 미러링·OCR·요약 제공 시 한국판보다 큰 가치" },
  { title: "빈집률·인구 추이 결합", desc: "일본 빈집(空き家)이 전체 주택의 13.8%. 자치체별 인구 추이·빈집률을 매물에 결합" },
  { title: "외국인 투자자 모드", desc: "엔저 영향으로 한국·중국·싱가포르 투자자 관심 증가. 한국어 UI 그대로 살린 일본 매물 검색 도구로 포지셔닝" },
  { title: "평가 재조정 이력 추적", desc: "유찰 자동 차감 없는 일본은 평가가 시점별로 변경됨. 변경 이력을 시각화" },
  { title: "특별매각(선착순) 알림", desc: "기간입찰 미낙찰 후 선착순 단계가 며칠간 열림. 알림 기능으로 차별화" },
];

export default function JpAboutPage() {
  return (
    <div className="space-y-6">
      <div className="text-xs">
        <Link href="/jp" className="text-muted-foreground hover:text-primary hover:underline">
          ← 일본 매물 목록
        </Link>
      </div>

      <section className="rounded-lg border bg-card p-6 space-y-2">
        <h1 className="text-2xl font-bold tracking-tight">한·일 경매제도 비교 + BIT 정찰 메모</h1>
        <p className="text-sm text-muted-foreground">
          한국 courtauction.go.kr와 일본 bit.courts.go.jp는 같은 "법원 경매" 도메인이지만 절차·평가·사이트
          기술 모두 다릅니다. 본 사이트는 동일 UX로 두 시장을 묶는 것을 목표로 합니다.
        </p>
      </section>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">🇰🇷 vs 🇯🇵 핵심 비교</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[140px]">항목</TableHead>
                <TableHead>🇰🇷 한국</TableHead>
                <TableHead>🇯🇵 일본</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {COMPARE.map(([k, kr, jp]) => (
                <TableRow key={k}>
                  <TableCell className="font-medium text-sm">{k}</TableCell>
                  <TableCell className="text-sm">{kr}</TableCell>
                  <TableCell className="text-sm">{jp}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card className="border-amber-300 bg-amber-50/40">
        <CardHeader>
          <CardTitle className="text-base">⚡ 가장 큰 차이 — 유찰 메커니즘</CardTitle>
        </CardHeader>
        <CardContent className="grid md:grid-cols-2 gap-4 text-sm">
          <div className="rounded-md bg-card p-3 border">
            <div className="font-semibold mb-1">🇰🇷 한국</div>
            <div className="text-muted-foreground">
              안 팔리면 자동으로 또 깎고, 또 깎고… 7회 유찰 시 감정가의 18%까지.
            </div>
          </div>
          <div className="rounded-md bg-card p-3 border">
            <div className="font-semibold mb-1">🇯🇵 일본</div>
            <div className="text-muted-foreground">
              세 번 안에 처리, 안 되면 그냥 멈춤. 미낙찰 시 평가 재조정 후 재입찰.
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">🎯 일본판 차별화 기능 후보</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid md:grid-cols-2 gap-3">
            {JP_FEATURES.map((f) => (
              <div key={f.title} className="rounded-md border bg-card p-3">
                <div className="font-semibold text-sm mb-1">{f.title}</div>
                <div className="text-xs text-muted-foreground">{f.desc}</div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">📚 데이터 소스</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>항목</TableHead>
                <TableHead>URL</TableHead>
                <TableHead>한국 대응</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow>
                <TableCell className="text-sm">BIT (법원 공식)</TableCell>
                <TableCell><a href="https://www.bit.courts.go.jp" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline text-xs font-mono">bit.courts.go.jp</a></TableCell>
                <TableCell className="text-xs">courtauction.go.kr</TableCell>
              </TableRow>
              <TableRow>
                <TableCell className="text-sm">用語集</TableCell>
                <TableCell><a href="https://www.bit.courts.go.jp/words/" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline text-xs font-mono">bit.courts.go.jp/words</a></TableCell>
                <TableCell className="text-xs">—</TableCell>
              </TableRow>
              <TableRow>
                <TableCell className="text-sm">国土交通省 不動産取引価格</TableCell>
                <TableCell><a href="https://www.land.mlit.go.jp/webland/" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline text-xs font-mono">land.mlit.go.jp</a></TableCell>
                <TableCell className="text-xs">data.go.kr 실거래가</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <div className="text-xs text-muted-foreground text-center pt-4">
        BIT 정찰 노트: <code className="text-foreground bg-muted px-1 rounded">docs/bit_api_recon.md</code> ·
        스키마 결정: <code className="text-foreground bg-muted px-1 rounded">docs/jp_schema_design.md</code>
      </div>
    </div>
  );
}
