import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Laris Chat",
  description: "Trò chuyện và làm việc với tài liệu trong Laris.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="vi">
      <body>{children}</body>
    </html>
  );
}
