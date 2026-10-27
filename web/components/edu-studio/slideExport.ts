"use client";

export interface CapturedSlide {
  fileName: string;
  blob: Blob;
  dataUrl: string;
  width: number;
  height: number;
}

async function canvasToBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (!blob) {
        reject(new Error("Failed to convert slide canvas to image blob."));
        return;
      }
      resolve(blob);
    }, "image/png");
  });
}

export async function captureSlidesAsPng(
  slideNodes: HTMLElement[],
  namePrefix = "slide",
): Promise<CapturedSlide[]> {
  if (!slideNodes.length) {
    throw new Error("No slides available for export.");
  }

  const { default: html2canvas } = await import("html2canvas");

  const captured: CapturedSlide[] = [];
  for (let index = 0; index < slideNodes.length; index += 1) {
    const node = slideNodes[index];
    const width = Math.max(node.scrollWidth, node.clientWidth);
    const height = Math.max(node.scrollHeight, node.clientHeight);
    const canvas = await html2canvas(node, {
      scale: 2,
      width,
      height,
      windowWidth: width,
      windowHeight: height,
      useCORS: true,
      logging: false,
      backgroundColor: "#ffffff",
      allowTaint: true,
    });

    const blob = await canvasToBlob(canvas);
    const dataUrl = canvas.toDataURL("image/png");
    const fileName = `${namePrefix}_${String(index + 1).padStart(2, "0")}.png`;

    captured.push({
      fileName,
      blob,
      dataUrl,
      width: canvas.width,
      height: canvas.height,
    });
  }

  return captured;
}

export async function buildSlidesZip(slides: CapturedSlide[]): Promise<Blob> {
  const { default: JSZip } = await import("jszip");
  const zip = new JSZip();

  slides.forEach((slide) => {
    zip.file(slide.fileName, slide.blob);
  });

  return zip.generateAsync({ type: "blob" });
}

export async function buildSlidesPdf(slides: CapturedSlide[]): Promise<Blob> {
  const { default: jsPDF } = await import("jspdf");

  const pdf = new jsPDF({
    orientation: "landscape",
    unit: "pt",
    format: "a4",
    compress: true,
  });

  const pageWidth = pdf.internal.pageSize.getWidth();
  const pageHeight = pdf.internal.pageSize.getHeight();

  slides.forEach((slide, index) => {
    if (index > 0) {
      pdf.addPage();
    }
    const slideRatio = slide.width / Math.max(1, slide.height);
    const pageRatio = pageWidth / Math.max(1, pageHeight);

    let renderWidth = pageWidth;
    let renderHeight = pageHeight;
    if (slideRatio > pageRatio) {
      renderHeight = pageWidth / slideRatio;
    } else {
      renderWidth = pageHeight * slideRatio;
    }

    const offsetX = (pageWidth - renderWidth) / 2;
    const offsetY = (pageHeight - renderHeight) / 2;
    pdf.addImage(
      slide.dataUrl,
      "PNG",
      offsetX,
      offsetY,
      renderWidth,
      renderHeight,
      undefined,
      "FAST",
    );
  });

  const out = pdf.output("blob");
  return out;
}

export async function buildSlidesPptx(slides: CapturedSlide[]): Promise<Blob> {
  const { loadPptxGenJS } = await import("@/lib/pptxBrowser");
  const PptxGenJS = await loadPptxGenJS();

  const pptx = new PptxGenJS();
  pptx.layout = "LAYOUT_WIDE";
  pptx.author = "Edu Studio";
  pptx.subject = "Slide Deck";
  pptx.company = "EduNote";

  slides.forEach((slide) => {
    const page = pptx.addSlide();
    page.addImage({
      data: slide.dataUrl,
      x: 0,
      y: 0,
      w: 13.333,
      h: 7.5,
    });
  });

  const out = (await pptx.write({ outputType: "blob" })) as Blob;
  return out;
}

export function downloadBlob(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function blobToFile(blob: Blob, fileName: string, type: string): File {
  return new File([blob], fileName, {
    type,
    lastModified: Date.now(),
  });
}
