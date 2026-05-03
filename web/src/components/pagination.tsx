import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { buildHref } from "@/lib/url";
import type { PropertyFilters } from "@/lib/types";

type Props = {
  filters: PropertyFilters;
  page: number;
  pageSize: number;
  total: number;
  basePath: string;
};

export function Pagination({ filters, page, pageSize, total, basePath }: Props) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const win = 5;
  const start = Math.max(1, page - Math.floor(win / 2));
  const end = Math.min(totalPages, start + win - 1);
  const realStart = Math.max(1, end - win + 1);

  const linkCls = (active: boolean, disabled?: boolean) =>
    cn(
      buttonVariants({ variant: active ? "default" : "outline", size: "sm" }),
      disabled && "pointer-events-none opacity-50",
    );

  return (
    <div className="flex items-center justify-between">
      <div className="text-xs text-muted-foreground">
        총 <strong>{total.toLocaleString()}</strong>건 · {page} / {totalPages} 페이지
      </div>
      <div className="flex items-center gap-1">
        <Link
          href={buildHref(basePath, filters, { page: 1 })}
          className={linkCls(false, page <= 1)}
          aria-disabled={page <= 1}
        >«</Link>
        <Link
          href={buildHref(basePath, filters, { page: page - 1 })}
          className={linkCls(false, page <= 1)}
          aria-disabled={page <= 1}
        >‹</Link>
        {Array.from({ length: end - realStart + 1 }, (_, i) => realStart + i).map((p) => (
          <Link
            key={p}
            href={buildHref(basePath, filters, { page: p })}
            className={linkCls(p === page)}
          >{p}</Link>
        ))}
        <Link
          href={buildHref(basePath, filters, { page: page + 1 })}
          className={linkCls(false, page >= totalPages)}
          aria-disabled={page >= totalPages}
        >›</Link>
        <Link
          href={buildHref(basePath, filters, { page: totalPages })}
          className={linkCls(false, page >= totalPages)}
          aria-disabled={page >= totalPages}
        >»</Link>
      </div>
    </div>
  );
}
