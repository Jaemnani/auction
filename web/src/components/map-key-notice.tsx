// 구글 지도 API 키 미설정/로드 실패 시 지도 대신 보여주는 안내 박스.
// 키 없이 배포돼도 페이지가 깨지지 않게 하는 안전망.

type Props = {
  error?: string | null;
  className?: string;
};

export function MapKeyNotice({ error, className }: Props) {
  return (
    <div
      className={
        "flex h-full min-h-[280px] w-full flex-col items-center justify-center gap-2 " +
        "rounded-md border bg-muted/20 p-6 text-center text-sm text-muted-foreground " +
        (className ?? "")
      }
    >
      <div className="font-medium text-foreground">지도를 표시할 수 없습니다</div>
      {error ? <div className="text-xs">{error}</div> : null}
      <div className="text-xs">
        <code className="rounded bg-muted px-1 py-0.5">NEXT_PUBLIC_GOOGLE_MAPS_API_KEY</code>
        {" "}환경변수에 Google Maps API 키를 설정해 주세요.
      </div>
    </div>
  );
}
