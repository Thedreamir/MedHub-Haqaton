import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Check-up Intelligence — PRIME Green Clinic",
  description: "Конструктор персонального чекапа: ОСМС + PRIME, маршрут одного дня, карта здоровья.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}
