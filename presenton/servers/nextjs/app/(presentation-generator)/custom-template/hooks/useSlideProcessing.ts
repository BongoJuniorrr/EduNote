import { useState, useCallback } from "react";
import { toast } from "sonner";
import { ApiResponseHandler } from "@/app/(presentation-generator)/services/api/api-error-handler";
import { ProcessedSlide, SlideData, FontData } from "../types";
import { withBasePath } from "@/utils/basePath";
import { requestTemplateCritic } from "../utils/templateCritic";

function normalizeAssetUrl(url?: string) {
  if (!url) return "";
  if (url.startsWith("/slide_pro/_presenton/")) return url;
  if (
    url.startsWith("/app_data/") ||
    url.startsWith("/static/") ||
    url.startsWith("app_data/") ||
    url.startsWith("static/")
  ) {
    return withBasePath(url);
  }
  return url;
}

export const useSlideProcessing = (
  selectedFile: File | null,
  slides: ProcessedSlide[],
  setSlides: React.Dispatch<React.SetStateAction<ProcessedSlide[]>>,
  
  setFontsData: React.Dispatch<React.SetStateAction<FontData | null>>
) => {
  const [isProcessingPptx, setIsProcessingPptx] = useState(false);

  const waitForSlideToHtmlJob = useCallback(
    async (jobId: string, slideNumber: number) => {
      const startedAt = Date.now();
      const maxWaitMs = 15 * 60 * 1000;

      while (Date.now() - startedAt < maxWaitMs) {
        const response = await fetch(
          withBasePath(`/api/v1/ppt/slide-to-html/jobs/${jobId}`),
          {
            method: "GET",
            cache: "no-store",
          }
        );

        const payload = await ApiResponseHandler.handleResponse(
          response,
          `Failed to check conversion status for slide ${slideNumber}`
        );

        if (payload.status === "completed" && payload.html) {
          return payload.html as string;
        }

        if (payload.status === "failed") {
          throw new Error(
            payload.error || `Failed to convert slide ${slideNumber} to HTML`
          );
        }

        await new Promise((resolve) => setTimeout(resolve, 2000));
      }

      throw new Error(
        `Slide ${slideNumber} conversion exceeded the 15 minute processing window`
      );
    },
    []
  );

  const scoreTemplateSlide = useCallback(
    async (slide: Pick<ProcessedSlide, "slide_number" | "screenshot_url" | "html">, index: number) => {
      try {
        const critic = await requestTemplateCritic(slide);
        setSlides((prev) =>
          prev.map((s, i) =>
            i === index
              ? {
                  ...s,
                  critic,
                  criticLoading: false,
                  criticError: undefined,
                }
              : s
          )
        );
      } catch (error) {
        const errorMessage =
          error instanceof Error ? error.message : "Failed to score this slide";
        setSlides((prev) =>
          prev.map((s, i) =>
            i === index
              ? {
                  ...s,
                  criticLoading: false,
                  criticError: errorMessage,
                }
              : s
          )
        );
      }
    },
    [setSlides]
  );

  // Process individual slide to HTML
  const processSlideToHtml = useCallback(
    async (slide: SlideData, index: number) => {
      console.log(
        `Starting to process slide ${slide.slide_number} at index ${index}`
      );

      // Update slide to processing state
      setSlides((prev) =>
        prev.map((s, i) =>
          i === index
            ? {
                ...s,
                processing: true,
                error: undefined,
                critic: undefined,
                criticLoading: false,
                criticError: undefined,
              }
            : s
        )
      );

      try {
        const jobResponse = await fetch(withBasePath("/api/v1/ppt/slide-to-html/jobs"), {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            image: normalizeAssetUrl(slide.screenshot_url),
            xml: slide.xml_content,
            fonts: slide.normalized_fonts ?? [],
          }),
        });

        const jobData = await ApiResponseHandler.handleResponse(
          jobResponse,
          `Failed to queue conversion for slide ${slide.slide_number}`
        );

        const htmlContent = await waitForSlideToHtmlJob(
          jobData.job_id,
          slide.slide_number
        );

        console.log(`Successfully processed slide ${slide.slide_number}`);
        // Update slide with success
        const critiquedSlide: Pick<
          ProcessedSlide,
          "slide_number" | "screenshot_url" | "html"
        > = {
          slide_number: slide.slide_number,
          screenshot_url: slide.screenshot_url,
          html: htmlContent,
        };
        setSlides((prev) => {
          const newSlides = prev.map((s, i) =>
            i === index
              ? {
                  ...s,
                  processing: false,
                  processed: true,
                  html: htmlContent,
                  critic: undefined,
                  criticLoading: true,
                  criticError: undefined,
                }
              : s
          );

          // Process next slide if available
          const nextIndex = index + 1;
          if (
            nextIndex < newSlides.length &&
            !newSlides[nextIndex].processed &&
            !newSlides[nextIndex].processing
          ) {
            console.log(
              `Scheduling next slide ${nextIndex + 1} for processing`
            );
            setTimeout(() => {
              const nextSlide = newSlides[nextIndex];
              processSlideToHtml(nextSlide, nextIndex);
            }, 1000); // 1 second delay between slides
          }

          return newSlides;
        });
        void scoreTemplateSlide(critiquedSlide, index);
      } catch (error) {
        console.error(`Error processing slide ${slide.slide_number}:`, error);
        const errorMessage =
          error instanceof Error ? error.message : "Failed to convert to HTML";

        // Update slide with error
        setSlides((prev) => {
          const newSlides = prev.map((s, i) =>
            i === index
              ? {
                  ...s,
                  processing: false,
                  processed: false,
                  error: errorMessage,
                  criticLoading: false,
                }
              : s
          );

          // Continue with next slide even if this one failed
          const nextIndex = index + 1;
          if (
            nextIndex < newSlides.length &&
            !newSlides[nextIndex].processed &&
            !newSlides[nextIndex].processing
          ) {
            console.log(`Scheduling next slide ${nextIndex + 1} after error`);
            setTimeout(() => {
              const nextSlide = newSlides[nextIndex];
              processSlideToHtml(nextSlide, nextIndex);
            }, 1000);
          }

          return newSlides;
        });
      }
    },
    [scoreTemplateSlide, setSlides, waitForSlideToHtmlJob]
  );

  // Process PDF or PPTX file to extract slides
  const processFile = useCallback(async () => {
    if (!selectedFile) {
      toast.error("Please select a PDF or PPTX file first");
      return;
    }

    try {
      setIsProcessingPptx(true);

      const formData = new FormData();
      const fileName = selectedFile.name.toLowerCase();
      const isPdf = fileName.endsWith(".pdf");
      const isPptx = fileName.endsWith(".pptx");

      let slidesResponseData: any = null;
      if (isPdf) {
        formData.append("pdf_file", selectedFile);
        const pdfResponse = await fetch(withBasePath("/api/v1/ppt/pdf-slides/process"), {
          method: "POST",
          body: formData,
        });
        slidesResponseData = await ApiResponseHandler.handleResponse(
          pdfResponse,
          "Failed to process PDF file"
        );
      } else if (isPptx) {
        formData.append("pptx_file", selectedFile);
        const pptxResponse = await fetch(withBasePath("/api/v1/ppt/pptx-slides/process"), {
          method: "POST",
          body: formData,
        });
        slidesResponseData = await ApiResponseHandler.handleResponse(
          pptxResponse,
          "Failed to process PPTX file"
        );
      } else {
        throw new Error("Unsupported file type. Please upload a PDF or PPTX file.");
      }

      if (!slidesResponseData.success || !slidesResponseData.slides?.length) {
        throw new Error("No slides found in the uploaded file");
      }

      // Extract fonts data only for PPTX where available
      if (slidesResponseData.fonts) {
        setFontsData(slidesResponseData.fonts);
      }

      // Initialize slides with skeleton state; for PDF, xml/fonts won't exist
      const initialSlides: ProcessedSlide[] = slidesResponseData.slides.map(
        (slide: any) => ({
          slide_number: slide.slide_number,
          screenshot_url: normalizeAssetUrl(slide.screenshot_url),
          xml_content: slide.xml_content ?? "",
          normalized_fonts: slide.normalized_fonts ?? [],
          processing: false,
          processed: false,
          criticLoading: false,
        })
      );

      setSlides(initialSlides);

      const hasUnsupported = Array.isArray(slidesResponseData.fonts?.not_supported_fonts) && slidesResponseData.fonts.not_supported_fonts.length > 0;

      toast.success(
        `Template Processing Finished`,
        {
          description: hasUnsupported
            ? `Please Upload the not supported fonts, and click Extract Template`
            : `All fonts are supported. Starting template extraction...`
        }
      );

      // If all fonts are supported, auto-start extraction from the first slide
      if (!hasUnsupported && initialSlides.length > 0) {
        const firstSlide = initialSlides[0];
        setTimeout(() => processSlideToHtml(firstSlide, 0), 300);
      }

      
    } catch (error) {
      console.error("Error processing file:", error);
      const errorMessage =
        error instanceof Error ? error.message : "An unexpected error occurred";
      toast.error("Processing failed", {
        description: errorMessage,
      });
    } finally {
      setIsProcessingPptx(false);
    }
  }, [selectedFile, processSlideToHtml, setSlides, setFontsData]);

  // Retry failed slide
  const retrySlide = useCallback(
    (index: number) => {
      const slide = slides[index];
      if (slide) {
        processSlideToHtml(slide, index);
      }
    },
    [slides, processSlideToHtml]
  );

  return {
    isProcessingPptx,
    processFile,
    processSlideToHtml,
    retrySlide,
  };
}; 
