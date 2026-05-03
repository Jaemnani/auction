import { NextResponse } from "next/server";
import { fetchSggList } from "@/lib/queries";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const sd = url.searchParams.get("sd") ?? undefined;
  const rows = await fetchSggList(sd);
  return NextResponse.json(rows);
}
