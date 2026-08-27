import type { Metadata } from "next";
import { IBM_Plex_Mono, Inter, Rajdhani } from "next/font/google";
import "./globals.css";

export const dynamic = "force-dynamic";

const bodyFont = Inter({
  variable: "--font-body",
  subsets: ["latin"],
});

const titleFont = Rajdhani({
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
  metadataBase: new URL("https://choquebgr.online"),
  title: {
    default: "CHOQUE - BGR | Centro de Comando",
    template: "%s | CHOQUE - BGR",
  },
  description: "Portal oficial de recrutamento, formação e gestão operacional da CHOQUE - BGR.",
  icons: {
    icon: "/choque-emblem.png",
    apple: "/choque-emblem.png",
  },
  openGraph: {
    type: "website",
    locale: "pt_BR",
    siteName: "CHOQUE - BGR",
    title: "CHOQUE - BGR | Centro de Comando",
    description: "Portal oficial de recrutamento, formação e gestão operacional.",
    images: [{ url: "/choque-emblem.png", width: 768, height: 768, alt: "Brasão oficial CHOQUE BGR" }],
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="pt-BR" className={`${bodyFont.variable} ${titleFont.variable} ${monoFont.variable}`}>
      <body>{children}</body>
    </html>
  );
}
