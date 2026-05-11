"use client";

import { useState } from "react";

type Props = {
  /** 다운로드/복사 대상 markdown 본문 */
  markdown: string;
  /** 다운로드 시 사용할 파일명 (확장자 제외). 영문/숫자/하이픈 권장. */
  filename: string;
};

/**
 * 상세 페이지용 export 버튼 2종:
 *   - 📋 클립보드 복사 (navigator.clipboard)
 *   - 📄 .md 다운로드 (Blob)
 */
export function ExportButtons({ markdown, filename }: Props) {
  const [copied, setCopied] = useState<"copy" | "download" | null>(null);

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(markdown);
      setCopied("copy");
      setTimeout(() => setCopied(null), 1500);
    } catch (e) {
      console.error("clipboard write failed:", e);
      alert("클립보드 복사 실패 — 브라우저 권한을 확인하세요.");
    }
  };

  const onDownload = () => {
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${filename}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    setCopied("download");
    setTimeout(() => setCopied(null), 1500);
  };

  return (
    <div className="inline-flex gap-2">
      <button
        type="button"
        onClick={onCopy}
        className="inline-flex items-center gap-1 rounded-md border bg-card hover:bg-muted px-2.5 py-1 text-xs font-medium"
      >
        {copied === "copy" ? "✓ 복사 완료" : "📋 클립보드 복사"}
      </button>
      <button
        type="button"
        onClick={onDownload}
        className="inline-flex items-center gap-1 rounded-md border bg-card hover:bg-muted px-2.5 py-1 text-xs font-medium"
      >
        {copied === "download" ? "✓ 다운로드 완료" : "📄 .md 다운로드"}
      </button>
    </div>
  );
}
