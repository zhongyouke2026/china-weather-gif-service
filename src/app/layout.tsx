import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "중국·대만 7일 날씨",
  description: "NOAA GFS + QWeather 중국·대만 7일 날씨 애니메이션 서비스",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
