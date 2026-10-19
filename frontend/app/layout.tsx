import type { Metadata } from "next";
import { Familjen_Grotesk, Inter_Tight, Martian_Mono } from "next/font/google";
import { Preloader } from "@/components/fx/Preloader";
import "./globals.css";

const familjen = Familjen_Grotesk({
  variable: "--font-familjen",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

const interTight = Inter_Tight({
  variable: "--font-inter-tight",
  subsets: ["latin"],
  weight: ["400", "500"],
});

const martian = Martian_Mono({
  variable: "--font-martian",
  subsets: ["latin"],
  weight: ["400"],
});

const TITLE = "Vik · AI venture capitalist";

// Icons and the share image come from the file conventions in this folder
// (icon.svg, apple-icon.png, opengraph-image.png), all made by brand/build.py.
export const metadata: Metadata = {
  // Absolute base for the share image URL; Render sets RENDER_EXTERNAL_URL on the web service.
  metadataBase: new URL(process.env.RENDER_EXTERNAL_URL ?? "http://localhost:3000"),
  title: {
    default: TITLE,
    template: "%s · Vik",
  },
  description:
    "Know your numbers before they do. Load your data, face a panel of AI investors and rehearse your pitch against the source of truth.",
  openGraph: {
    title: TITLE,
    description: "Your AI venture capitalist. Know your numbers before they do.",
    siteName: "Vik",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: "Your AI venture capitalist. Know your numbers before they do.",
  },
};

// Runs before first paint: restores the saved theme and skips the preloader after its first run.
const bootScript = `try{var t=localStorage.getItem("vik-theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;if(sessionStorage.getItem("vik-preloaded"))document.documentElement.dataset.preloaded=""}catch(e){}`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      data-theme="dark"
      suppressHydrationWarning
      className={`${familjen.variable} ${interTight.variable} ${martian.variable} h-full`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: bootScript }} />
      </head>
      <body className="min-h-full">
        <Preloader />
        {children}
      </body>
    </html>
  );
}
