import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans, Newsreader, Noto_Sans_Devanagari } from "next/font/google";
import "./globals.css";

const newsreader = Newsreader({ variable: "--font-newsreader", subsets: ["latin"], weight: ["400", "500", "600"] });
const plex = IBM_Plex_Sans({ variable: "--font-plex", subsets: ["latin"], weight: ["400", "500", "600"] });
const plexMono = IBM_Plex_Mono({ variable: "--font-plex-mono", subsets: ["latin"], weight: ["400", "500"] });
// Customers write in Nepali, Hindi and Bhojpuri: Devanagari glyphs fall through to this in every stack.
const deva = Noto_Sans_Devanagari({ variable: "--font-deva", subsets: ["devanagari"], weight: ["400", "500", "600"] });

export const metadata: Metadata = {
  title: "Pheri",
  description: "The next step for every customer, inside your rules.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${newsreader.variable} ${plex.variable} ${plexMono.variable} ${deva.variable} h-full`}>
      <body className="min-h-full">{children}</body>
    </html>
  );
}
