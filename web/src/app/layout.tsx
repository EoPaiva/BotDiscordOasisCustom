import type { Metadata } from "next";
import { Barlow_Condensed, IBM_Plex_Mono, Source_Sans_3 } from "next/font/google";
import "./globals.css";

export const dynamic = "force-dynamic";

const bodyFont = Source_Sans_3({
  variable: "--font-body",
  subsets: ["latin"],
});

const titleFont = Barlow_Condensed({
  variable: "--font-title",
  subsets: ["latin"],
  weight: ["500", "600", "700"],
});

const monoFont = IBM_Plex_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "Centro de Comando | CHOQUE - BGR",
  description: "Sistema interno de comando e gestão da CHOQUE - BGR.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="pt-BR" className={`${bodyFont.variable} ${titleFont.variable} ${monoFont.variable}`}>
      <body>{children}</body>
    </html>
  );
}
