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

export const metadata: Metadata = {
  title: {
    default: "JUNE × VICKY — your AI venture capitalist",
    template: "%s · JUNE × VICKY",
  },
  description:
    "Know your numbers before they do. Load your data, face a panel of AI investors and rehearse your pitch against the source of truth.",
  openGraph: {
    title: "JUNE × VICKY",
    description: "Your AI venture capitalist. Know your numbers before they do.",
    siteName: "JUNE × VICKY",
    type: "website",
  },
};

// Runs before first paint: restores the saved theme and skips the preloader after its first run.
const bootScript = `try{var t=localStorage.getItem("vicky-theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;if(sessionStorage.getItem("vicky-preloaded"))document.documentElement.dataset.preloaded=""}catch(e){}`;

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
