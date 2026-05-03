"use client";

import { useEffect, useState, useTransition } from "react";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import type { PropertyFilters } from "@/lib/types";

type Option = { code: string; name: string };

type Props = {
  courts: Option[];
  sdList: Option[];
  usageLcl: Option[];
  initial: PropertyFilters;
};

const SORT_OPTIONS: { value: NonNullable<PropertyFilters["sort"]>; label: string }[] = [
  { value: "sale_date", label: "매각기일 빠른 순" },
  { value: "appraisal_desc", label: "감정가 높은 순" },
  { value: "appraisal_asc", label: "감정가 낮은 순" },
  { value: "fail_desc", label: "유찰 많은 순" },
  { value: "discount_desc", label: "할인율 높은 순" },
];

export function FilterSidebar({ courts, sdList, usageLcl, initial }: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const [isPending, startTransition] = useTransition();

  const [f, setF] = useState<PropertyFilters>(initial);
  const [showAdvanced, setShowAdvanced] = useState(
    !!(initial.min_appraisal || initial.max_appraisal || initial.min_sale ||
       initial.max_sale || initial.min_fail || initial.max_fail ||
       initial.sale_from || initial.sale_to || initial.usage_mcl || initial.sgg),
  );

  const [sgg, setSgg] = useState<Option[]>([]);
  const [usageMcl, setUsageMcl] = useState<Option[]>([]);

  useEffect(() => {
    let cancel = false;
    if (!f.sd) { setSgg([]); return; }
    fetch(`/api/regions/sgg?sd=${f.sd}`)
      .then((r) => r.json())
      .then((rows) => { if (!cancel) setSgg(rows); })
      .catch(() => {});
    return () => { cancel = true; };
  }, [f.sd]);

  useEffect(() => {
    let cancel = false;
    if (!f.usage_lcl) { setUsageMcl([]); return; }
    fetch(`/api/usage?level=2&parent=${f.usage_lcl}`)
      .then((r) => r.json())
      .then((rows) => { if (!cancel) setUsageMcl(rows); })
      .catch(() => {});
    return () => { cancel = true; };
  }, [f.usage_lcl]);

  function set<K extends keyof PropertyFilters>(k: K, v: PropertyFilters[K]) {
    setF((prev) => ({ ...prev, [k]: v }));
  }

  const pickStr = (v: unknown): string | undefined => {
    if (v == null || v === "" || v === "all") return undefined;
    return String(v);
  };

  function apply() {
    const params = new URLSearchParams(sp.toString());
    const writable: (keyof PropertyFilters)[] = [
      "q", "court", "sd", "sgg", "usage_lcl", "usage_mcl", "usage_scl",
      "min_appraisal", "max_appraisal", "min_sale", "max_sale",
      "min_fail", "max_fail", "sale_from", "sale_to", "sort",
    ];
    for (const k of writable) {
      const v = f[k];
      if (v === undefined || v === null || v === "") {
        params.delete(k as string);
      } else {
        params.set(k as string, String(v));
      }
    }
    params.delete("page");
    startTransition(() => router.push(`${pathname}?${params.toString()}`));
  }

  function reset() {
    setF({});
    startTransition(() => router.push(pathname));
  }

  // 활성 필터 카운트
  const activeCount = [
    f.q, f.court, f.sd, f.sgg, f.usage_lcl, f.usage_mcl,
    f.min_appraisal, f.max_appraisal, f.min_sale, f.max_sale,
    f.min_fail, f.max_fail, f.sale_from, f.sale_to,
  ].filter((v) => v !== undefined && v !== "" && v !== null).length;

  // 코드 → 한글 라벨 lookup (기본값: "전체")
  const nameOf = (code: string | undefined, list: Option[], placeholder = "전체") =>
    !code ? placeholder
      : (list.find((o) => o.code === code)?.name ?? code);
  const sortLabelOf = (v: PropertyFilters["sort"]) =>
    SORT_OPTIONS.find((o) => o.value === (v ?? "sale_date"))?.label ?? "정렬";

  return (
    <div className="rounded-lg border bg-card p-4 space-y-3">
      {/* 1행: 키워드(가장 넓게) + 정렬 + 버튼 */}
      <div className="flex flex-wrap items-end gap-2">
        <div className="flex-1 min-w-[200px]">
          <Label htmlFor="q" className="text-xs">키워드 (주소 / 사건번호)</Label>
          <Input
            id="q"
            value={f.q ?? ""}
            onChange={(e) => set("q", e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && apply()}
            placeholder="예: 강남구, 2023타경6292"
          />
        </div>
        <div className="w-44">
          <Label className="text-xs">정렬</Label>
          <Select value={f.sort ?? "sale_date"} onValueChange={(v) => set("sort", (pickStr(v) ?? "sale_date") as PropertyFilters["sort"])}>
            <SelectTrigger className="w-full"><SelectValue>{sortLabelOf(f.sort)}</SelectValue></SelectTrigger>
            <SelectContent>
              {SORT_OPTIONS.map((o) => (
                <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button onClick={apply} disabled={isPending}>
          {isPending ? "검색 중…" : `검색${activeCount > 0 ? ` (${activeCount})` : ""}`}
        </Button>
        <Button onClick={reset} variant="outline">초기화</Button>
        <Button
          onClick={() => setShowAdvanced((v) => !v)}
          variant="ghost"
          className="ml-auto"
        >
          {showAdvanced ? "필터 접기 ▲" : "상세 필터 ▼"}
        </Button>
      </div>

      {/* 2행: 법원 / 지역 / 용도 — 항상 노출 */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
        <div>
          <Label className="text-xs">법원</Label>
          <Select value={f.court ?? "all"} onValueChange={(v) => set("court", pickStr(v))}>
            <SelectTrigger className="w-full"><SelectValue placeholder="전체">{nameOf(f.court, courts)}</SelectValue></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">전체</SelectItem>
              {courts.map((c) => (
                <SelectItem key={c.code} value={c.code}>{c.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label className="text-xs">시·도</Label>
          <Select value={f.sd ?? "all"} onValueChange={(v) => {
            set("sd", pickStr(v));
            set("sgg", undefined);
          }}>
            <SelectTrigger className="w-full"><SelectValue placeholder="전체">{nameOf(f.sd, sdList)}</SelectValue></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">전체</SelectItem>
              {sdList.map((s) => (
                <SelectItem key={s.code} value={s.code}>{s.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label className="text-xs">시·군·구</Label>
          <Select value={f.sgg ?? "all"} onValueChange={(v) => set("sgg", pickStr(v))} disabled={!f.sd}>
            <SelectTrigger className="w-full"><SelectValue placeholder="전체">{nameOf(f.sgg, sgg)}</SelectValue></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">전체</SelectItem>
              {sgg.map((s) => (
                <SelectItem key={s.code} value={s.code}>{s.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label className="text-xs">용도 (대)</Label>
          <Select value={f.usage_lcl ?? "all"} onValueChange={(v) => {
            set("usage_lcl", pickStr(v));
            set("usage_mcl", undefined);
          }}>
            <SelectTrigger className="w-full"><SelectValue placeholder="전체">{nameOf(f.usage_lcl, usageLcl)}</SelectValue></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">전체</SelectItem>
              {usageLcl.map((u) => (
                <SelectItem key={u.code} value={u.code}>{u.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label className="text-xs">용도 (중)</Label>
          <Select value={f.usage_mcl ?? "all"} onValueChange={(v) => set("usage_mcl", pickStr(v))} disabled={!f.usage_lcl}>
            <SelectTrigger className="w-full"><SelectValue placeholder="전체">{nameOf(f.usage_mcl, usageMcl)}</SelectValue></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">전체</SelectItem>
              {usageMcl.map((u) => (
                <SelectItem key={u.code} value={u.code}>{u.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* 3행: 가격/유찰/기일 — 토글 */}
      {showAdvanced && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 pt-2 border-t">
          <RangeField label="감정가 (만원)"
            min={f.min_appraisal} max={f.max_appraisal}
            onMin={(v) => set("min_appraisal", v)} onMax={(v) => set("max_appraisal", v)} />
          <RangeField label="최저매각가 (만원)"
            min={f.min_sale} max={f.max_sale}
            onMin={(v) => set("min_sale", v)} onMax={(v) => set("max_sale", v)} />
          <RangeField label="유찰횟수"
            min={f.min_fail} max={f.max_fail}
            onMin={(v) => set("min_fail", v)} onMax={(v) => set("max_fail", v)} />
          <div>
            <Label className="text-xs">매각기일</Label>
            <div className="flex gap-1">
              <Input type="date" value={f.sale_from ?? ""}
                     onChange={(e) => set("sale_from", e.target.value || undefined)} />
              <Input type="date" value={f.sale_to ?? ""}
                     onChange={(e) => set("sale_to", e.target.value || undefined)} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function RangeField({ label, min, max, onMin, onMax }: {
  label: string;
  min: number | undefined;
  max: number | undefined;
  onMin: (v: number | undefined) => void;
  onMax: (v: number | undefined) => void;
}) {
  return (
    <div>
      <Label className="text-xs">{label}</Label>
      <div className="flex gap-1">
        <Input type="number" placeholder="최소" value={min ?? ""}
               onChange={(e) => onMin(e.target.value ? Number(e.target.value) : undefined)} />
        <Input type="number" placeholder="최대" value={max ?? ""}
               onChange={(e) => onMax(e.target.value ? Number(e.target.value) : undefined)} />
      </div>
    </div>
  );
}
