// anon JWT 발급 — JWT_SECRET 으로 {"role":"anon"} 토큰 서명.
// supabase-js 는 이 키를 Authorization: Bearer <key> 로 보내고,
// PostgREST 가 같은 JWT_SECRET 으로 검증 → anon 역할로 매핑.
//
// 사용:
//   node gen-anon-key.mjs "<JWT_SECRET>"
//   (또는 JWT_SECRET 환경변수)
//
// 의존성 없음 (Node 내장 crypto 로 HS256 직접 서명).

import crypto from "node:crypto";

const secret = process.argv[2] || process.env.JWT_SECRET;
if (!secret) {
  console.error("usage: node gen-anon-key.mjs <JWT_SECRET>   (or set JWT_SECRET env)");
  process.exit(1);
}

const b64url = (buf) =>
  Buffer.from(buf).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

// service_role 키도 같이 발급 (크롤러가 PostgREST 경유 write 할 경우 대비 — 현재는 직접 DB).
function sign(role) {
  const header = b64url(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  // 만료 없음 (장기 서비스 키). 필요시 exp 추가.
  const payload = b64url(JSON.stringify({ role, iss: "auction-selfhost" }));
  const data = `${header}.${payload}`;
  const sig = b64url(crypto.createHmac("sha256", secret).update(data).digest());
  return `${data}.${sig}`;
}

console.log("ANON_KEY:");
console.log(sign("anon"));
console.log("");
console.log("SERVICE_KEY (비밀 — 서버/크롤러 전용, 절대 클라이언트 노출 금지):");
console.log(sign("service_role"));
