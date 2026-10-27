import type { Metadata } from "next";
import localFont from "next/font/local";
import { Roboto, Instrument_Sans } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";
import MixpanelInitializer from "./MixpanelInitializer";
import { Toaster } from "@/components/ui/sonner";

const runtimeBasePath = (process.env.NEXT_PUBLIC_BASE_PATH || "").replace(/\/+$/, "");

const clientBasePathPatch = `
(() => {
  const basePath = ${JSON.stringify(runtimeBasePath)};
  if (!basePath || typeof window === "undefined") return;

  const hasProtocol = (value) => /^[a-zA-Z][a-zA-Z\\d+\\-.]*:/.test(value) || value.startsWith("//");
  const normalize = (value) => {
    if (!value || typeof value !== "string") return value;
    if (hasProtocol(value)) return value;
    if (!value.startsWith("/")) return value;
    if (value === basePath || value.startsWith(basePath + "/")) return value;
    return basePath + value;
  };

  const nativeFetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    if (typeof input === "string") {
      return nativeFetch(normalize(input), init);
    }

    if (input && typeof input.url === "string") {
      try {
        const url = new URL(input.url, window.location.origin);
        if (url.origin === window.location.origin) {
          const normalized = normalize(url.pathname + url.search + url.hash);
          if (normalized !== url.pathname + url.search + url.hash) {
            return nativeFetch(normalized, init);
          }
        }
      } catch {
        return nativeFetch(input, init);
      }
    }

    return nativeFetch(input, init);
  };

  const NativeEventSource = window.EventSource;
  if (NativeEventSource) {
    window.EventSource = function (url, config) {
      return new NativeEventSource(normalize(typeof url === "string" ? url : String(url)), config);
    };
    window.EventSource.prototype = NativeEventSource.prototype;
  }
})();
`;
const inter = localFont({
  src: [
    {
      path: "./fonts/Inter.ttf",
      weight: "400",
      style: "normal",
    },
  ],
  variable: "--font-inter",
});

const instrument_sans = Instrument_Sans({
  subsets: ["latin"],
  weight: ["400"],
  variable: "--font-instrument-sans",
});

const roboto = Roboto({
  subsets: ["latin"],
  weight: ["400"],
  variable: "--font-roboto",
});


export const metadata: Metadata = {
  metadataBase: new URL("https://edunote.orzlab.net"),
  title: "EduNote Slides",
  description:
    "EduNote Slides workspace for generating and editing presentations.",
  keywords: [
    "EduNote Slides",
    "AI slides",
    "presentation editor",
    "slide generation",
    "data storytelling",
  ],
  openGraph: {
    title: "EduNote Slides",
    description:
      "EduNote Slides workspace for generating and editing presentations.",
    url: "https://edunote.orzlab.net/slide_pro",
    siteName: "EduNote Slides",
    images: [
      {
        url: "https://edunote.orzlab.net/slide_pro/_presenton/Logo.png",
        width: 1200,
        height: 630,
        alt: "EduNote Slides",
      },
    ],
    type: "website",
    locale: "en_US",
  },
  alternates: {
    canonical: "https://edunote.orzlab.net/slide_pro",
  },
  twitter: {
    card: "summary_large_image",
    title: "EduNote Slides",
    description:
      "EduNote Slides workspace for generating and editing presentations.",
    images: ["https://edunote.orzlab.net/slide_pro/_presenton/Logo.png"],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {

  return (
    <html lang="en">
      <body
        className={`${inter.variable} ${roboto.variable} ${instrument_sans.variable} antialiased`}
      >
        <script dangerouslySetInnerHTML={{ __html: clientBasePathPatch }} />
        <Providers>
          <MixpanelInitializer>

            {children}

          </MixpanelInitializer>
        </Providers>
        <Toaster position="top-center" />
      </body>
    </html>
  );
}
