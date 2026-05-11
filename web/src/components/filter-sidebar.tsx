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

/** 패스 키워드 그룹 — risk_flags 코드와 1:1 매핑. */
const RISK_GROUPS: Array<{ title: string; items: { code: string; label: string }[] }> = [
  {
    title: "권리관계",
    items: [
      { code: "share_sale", label: "지분 매각" },
      { code: "yuchi", label: "유치권" },
      { code: "legal_ground", label: "법정지상권" },
      { code: "senior_tenant", label: "선순위 임차인" },
      { code: "rent_unknown", label: "임대관계 미상" },
      { code: "illegal_bld", label: "위반건축물" },
    ],
  },
  {
    title: "토지·건물",
    items: [
      { code: "maeng_ji", label: "맹지" },
      { code: "reserve_forest", label: "보전산지" },
      { code: "forestry_land", label: "임업용 산지" },
      { code: "agri_zone", label: "농림지역" },
      { code: "nat_protect", label: "자연보전권역" },
      { code: "private_road", label: "사도" },
      { code: "pollak", label: "포락지" },
      { code: "pamyo", label: "파묘" },
      { code: "power_line", label: "송전선 / 구분지상권" },
      { code: "show_only", label: "제시외 물건" },
      { code: "farm_land", label: "농지" },
      { code: "forest_only", label: "임야 단독" },
      { code: "tiny_area", label: "초소형 (30㎡↓)" },
    ],
  },
  {
    title: "경매 진행",
    items: [
      { code: "many_fails", label: "유찰 5회 이상" },
      { code: "special_20", label: "특별 보증금 20%" },
      { code: "claim_90", label: "청구금액 90% 이상" },
      { code: "stopped", label: "정지/연기/취하" },
    ],
  },
  {
    title: "기타",
    items: [
      { code: "new_villa", label: "신축 빌라 (5년)" },
      { code: "share_maeng", label: "지분+맹지 조합 ⚠" },
    ],
  },
];

const SORT_OPTIONS: { value: NonNullable<PropertyFilters["sort"]>; label: string }[] = [
  { value: "sale_date", label: "매각기일 ↑ (빠른 순)" },
  { value: "sale_date_desc", label: "매각기일 ↓ (늦은 순)" },
  { value: "appraisal_asc", label: "감정가 ↑ (낮은 순)" },
  { value: "appraisal_desc", label: "감정가 ↓ (높은 순)" },
  { value: "min_sale_asc", label: "최저가 ↑ (낮은 순)" },
  { value: "min_sale_desc", label: "최저가 ↓ (높은 순)" },
  { value: "fail_asc", label: "유찰 ↑ (적은 순)" },
  { value: "fail_desc", label: "유찰 ↓ (많은 순)" },
  { value: "discount_desc", label: "할인율 ↓ (높은 순)" },
  { value: "discount_asc", label: "할인율 ↑ (낮은 순)" },
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
      "min_fail", "max_fail", "min_rate", "max_rate",
      "sale_from", "sale_to", "sort", "addr_state",
    ];
    for (const k of writable) {
      const v = f[k];
      if (v === undefined || v === null || v === "") {
        params.delete(k as string);
      } else {
        params.set(k as string, String(v));
      }
    }
    if (f.upcoming_only) params.set("upcoming_only", "1");
    else params.delete("upcoming_only");
    // exclude_flags — 콤마 구분 URL 단일 키
    if (f.exclude_flags && f.exclude_flags.length > 0) {
      params.set("exclude_flags", f.exclude_flags.join(","));
    } else {
      params.delete("exclude_flags");
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
  ].filter((v) => v !== undefined && v !== "" && v !== null).length
    + (f.exclude_flags?.length ?? 0);

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
          <RangeField label="매각가율 (%)"
            min={f.min_rate} max={f.max_rate}
            onMin={(v) => set("min_rate", v)} onMax={(v) => set("max_rate", v)} />
          <div>
            <Label className="text-xs">매각기일</Label>
            <div className="flex gap-1">
              <Input type="date" value={f.sale_from ?? ""}
                     onChange={(e) => set("sale_from", e.target.value || undefined)} />
              <Input type="date" value={f.sale_to ?? ""}
                     onChange={(e) => set("sale_to", e.target.value || undefined)} />
            </div>
            <label className="text-xs flex items-center gap-1.5 mt-1.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={!!f.upcoming_only}
                onChange={(e) => set("upcoming_only", e.target.checked || undefined)}
              />
              <span>미래 기일만</span>
            </label>
          </div>
          <div>
            <Label className="text-xs">주소 상태</Label>
            <Select
              value={f.addr_state ?? "all"}
              onValueChange={(v) => {
                const s = pickStr(v);
                set("addr_state", s === "with_road" || s === "no_road" ? s : undefined);
              }}
            >
              <SelectTrigger className="w-full">
                <SelectValue placeholder="전체">{
                  f.addr_state === "with_road" ? "도로명 있음만"
                  : f.addr_state === "no_road" ? "도로명 미수집만"
                  : "전체"
                }</SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">전체</SelectItem>
                <SelectItem value="with_road">도로명 있음만</SelectItem>
                <SelectItem value="no_road">도로명 미수집만</SelectItem>
              </SelectContent>
            </Select>
            <div className="text-[10px] text-muted-foreground mt-1">
              일부 매물은 좌표만 있고 도로명이 없습니다.
            </div>
          </div>
        </div>
      )}

      {/* 패스 키워드 — 위험 매물 제외 (advanced 토글과 독립적으로 항시 노출) */}
      <details className="pt-2 border-t" open={showAdvanced || (f.exclude_flags?.length ?? 0) > 0}>
        <summary className="cursor-pointer text-sm font-medium select-none flex items-center gap-2">
          <span>🚫 제외할 매물 특징</span>
          {f.exclude_flags && f.exclude_flags.length > 0 && (
            <span className="text-xs rounded bg-rose-100 text-rose-700 px-1.5 py-0.5">
              {f.exclude_flags.length}개 선택
            </span>
          )}
          <span className="ml-auto text-[10px] text-muted-foreground">
            체크한 특징이 있는 매물은 결과에서 제외
          </span>
        </summary>
        <div className="space-y-3 mt-3">
          {RISK_GROUPS.map((g) => (
            <div key={g.title}>
              <div className="text-xs font-semibold text-muted-foreground mb-1.5">{g.title}</div>
              <div className="flex flex-wrap gap-1.5">
                {g.items.map((it) => {
                  const active = f.exclude_flags?.includes(it.code) ?? false;
                  return (
                    <label
                      key={it.code}
                      className={
                        "inline-flex items-center gap-1 cursor-pointer select-none rounded border px-2 py-1 text-xs transition " +
                        (active
                          ? "bg-rose-100 border-rose-300 text-rose-700"
                          : "bg-card border-border hover:bg-muted")
                      }
                    >
                      <input
                        type="checkbox"
                        className="hidden"
                        checked={active}
                        onChange={(e) => {
                          const prev = f.exclude_flags ?? [];
                          const next = e.target.checked
                            ? Array.from(new Set([...prev, it.code]))
                            : prev.filter((c) => c !== it.code);
                          set("exclude_flags", next.length > 0 ? next : undefined);
                        }}
                      />
                      <span>{active ? "✕" : "○"}</span>
                      <span>{it.label}</span>
                    </label>
                  );
                })}
              </div>
            </div>
          ))}
          <div className="text-[10px] text-muted-foreground pt-2 border-t">
            매물의 위험 분석은 detail 적재 시 자동 계산.
            기존 매물은 <code className="bg-muted px-1 rounded">crawler/scripts/ingest.py backfill-risk-flags</code> 1회 실행 필요.
          </div>
        </div>
      </details>
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
