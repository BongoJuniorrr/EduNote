import fs from "fs";
import path from "path";

import puppeteer, { ElementHandle, Page } from "puppeteer";
import { NextRequest, NextResponse } from "next/server";

import { sanitizeFilename } from "@/app/(presentation-generator)/utils/others";
import { buildLocalAppUrl, withBasePath } from "@/utils/basePath";

const SLIDE_WIDTH = 1280;
const SLIDE_HEIGHT = 720;
const SLIDE_WAIT_TIMEOUT_MS = 300000;

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const { id, title } = await req.json();
  if (!id) {
    return NextResponse.json(
      { error: "Missing Presentation ID" },
      { status: 400 }
    );
  }

  const browser = await puppeteer.launch({
    executablePath: process.env.PUPPETEER_EXECUTABLE_PATH,
    headless: true,
    protocolTimeout: SLIDE_WAIT_TIMEOUT_MS,
    args: [
      "--no-sandbox",
      "--disable-setuid-sandbox",
      "--disable-dev-shm-usage",
      "--disable-gpu",
      "--disable-web-security",
      "--disable-background-timer-throttling",
      "--disable-backgrounding-occluded-windows",
      "--disable-renderer-backgrounding",
      "--disable-features=TranslateUI",
      "--disable-ipc-flooding-protection",
    ],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({
      width: SLIDE_WIDTH,
      height: SLIDE_HEIGHT,
      deviceScaleFactor: 1,
    });
    page.setDefaultNavigationTimeout(SLIDE_WAIT_TIMEOUT_MS);
    page.setDefaultTimeout(SLIDE_WAIT_TIMEOUT_MS);

    await page.goto(buildLocalAppUrl(`/pdf-maker?id=${id}`), {
      waitUntil: "domcontentloaded",
      timeout: SLIDE_WAIT_TIMEOUT_MS,
    });
    await waitForExportSlides(page);
    const slideImages = await captureSlideImages(page);

    await page.setContent(buildPdfDocumentHtml(slideImages), {
      waitUntil: "load",
    });
    await page.waitForFunction(
      () => Array.from(document.images).every((image) => image.complete),
      { timeout: SLIDE_WAIT_TIMEOUT_MS }
    );
    await page.emulateMediaType("screen");

    const pdfBuffer = await page.pdf({
      printBackground: true,
      margin: { top: 0, right: 0, bottom: 0, left: 0 },
      preferCSSPageSize: true,
    });

    const sanitizedTitle = sanitizeFilename(title ?? "presentation");
    const appDataDirectory = process.env.APP_DATA_DIRECTORY!;
    if (!appDataDirectory) {
      return NextResponse.json(
        { error: "App data directory not found" },
        { status: 500 }
      );
    }

    const destinationPath = path.join(
      appDataDirectory,
      "exports",
      `${sanitizedTitle}.pdf`
    );
    await fs.promises.mkdir(path.dirname(destinationPath), { recursive: true });
    await fs.promises.writeFile(destinationPath, pdfBuffer);

    return NextResponse.json({
      success: true,
      path: withBasePath(`/app_data/exports/${sanitizedTitle}.pdf`),
    });
  } finally {
    await browser.close();
  }
}

async function waitForExportSlides(page: Page) {
  await page.waitForSelector("#presentation-slides-wrapper", {
    timeout: SLIDE_WAIT_TIMEOUT_MS,
  });
  await page.waitForFunction(
    () => {
      const wrapper = document.querySelector("#presentation-slides-wrapper");
      if (!wrapper) return false;
      const slides = wrapper.querySelectorAll("[data-export-slide]");
      if (!slides.length) return false;
      return Array.from(document.images).every((image) => image.complete);
    },
    { timeout: SLIDE_WAIT_TIMEOUT_MS }
  );
  await page.waitForFunction('() => document.readyState === "complete"');
  await sleep(500);
}

async function captureSlideImages(page: Page): Promise<string[]> {
  const slideHandles = await page.$$("[data-export-slide]");
  if (!slideHandles.length) {
    throw new Error("No export slides found");
  }

  const slideImages: string[] = [];

  for (const slideHandle of slideHandles) {
    await slideHandle.evaluate((element) => {
      element.scrollIntoView({ block: "center", inline: "center" });
    });
    await waitForSlideToStabilize(slideHandle);
    await sleep(150);
    const screenshot = (await slideHandle.screenshot({
      type: "png",
      captureBeyondViewport: false,
    })) as Uint8Array;
    slideImages.push(`data:image/png;base64,${Buffer.from(screenshot).toString("base64")}`);
  }

  return slideImages;
}

async function waitForSlideToStabilize(slideHandle: ElementHandle<Element>) {
  await slideHandle.evaluate(async (element) => {
    const imageElements = Array.from(
      element.querySelectorAll("img")
    ) as HTMLImageElement[];

    await Promise.all(
      imageElements.map(async (image) => {
        if (!image.complete) {
          await new Promise<void>((resolve) => {
            const finalize = () => resolve();
            image.addEventListener("load", finalize, { once: true });
            image.addEventListener("error", finalize, { once: true });
          });
        }

        if (typeof image.decode === "function") {
          try {
            await image.decode();
          } catch {
            // Ignore decode failures; the image may still be renderable.
          }
        }
      })
    );

    if ("fonts" in document && (document as Document & { fonts?: FontFaceSet }).fonts) {
      try {
        await (document as Document & { fonts: FontFaceSet }).fonts.ready;
      } catch {
        // Ignore font readiness failures and continue with the current render state.
      }
    }

    await new Promise<void>((resolve) =>
      requestAnimationFrame(() =>
        requestAnimationFrame(() => resolve())
      )
    );
  });
}

function buildPdfDocumentHtml(slideImages: string[]) {
  const slidePages = slideImages
    .map(
      (image, index) => `
        <section class="page"${index === slideImages.length - 1 ? ' data-last="true"' : ""}>
          <img src="${image}" alt="Slide ${index + 1}" />
        </section>
      `
    )
    .join("");

  return `<!DOCTYPE html>
    <html>
      <head>
        <meta charset="utf-8" />
        <style>
          @page {
            size: ${SLIDE_WIDTH}px ${SLIDE_HEIGHT}px;
            margin: 0;
          }
          html, body {
            margin: 0;
            padding: 0;
            background: #ffffff;
          }
          body {
            font-size: 0;
          }
          .page {
            width: ${SLIDE_WIDTH}px;
            height: ${SLIDE_HEIGHT}px;
            margin: 0;
            overflow: hidden;
            break-after: page;
            page-break-after: always;
          }
          .page[data-last="true"] {
            break-after: auto;
            page-break-after: auto;
          }
          .page img {
            display: block;
            width: ${SLIDE_WIDTH}px;
            height: ${SLIDE_HEIGHT}px;
            object-fit: fill;
          }
        </style>
      </head>
      <body>${slidePages}</body>
    </html>`;
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
