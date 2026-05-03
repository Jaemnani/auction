import { NextResponse } from "next/server";
import { fetchUsageList } from "@/lib/queries";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const level = Number(url.searchParams.get("level") ?? "1") as 1 | 2 | 3;
  const parent = url.searchParams.get("parent") ?? undefined;
  const rows = await fetchUsageList(level, parent);
  return NextResponse.json(rows);
}
