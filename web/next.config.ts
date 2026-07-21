import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // dev 서버를 LAN IP로 접속해도 /_next 리소스가 차단되지 않도록 (프로덕션 무영향)
  allowedDevOrigins: ["192.168.50.61"],
};

export default nextConfig;
