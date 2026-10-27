import { ApiResponseHandler } from "@/app/(presentation-generator)/services/api/api-error-handler";
import { withBasePath } from "@/utils/basePath";
import { ProcessedSlide, TemplateCriticResult } from "../types";

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

export async function requestTemplateCritic(
  slide: Pick<ProcessedSlide, "slide_number" | "screenshot_url" | "html">
): Promise<TemplateCriticResult> {
  const response = await fetch(withBasePath("/api/v1/ppt/template-critic"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      slide_number: slide.slide_number,
      image: normalizeAssetUrl(slide.screenshot_url),
      html: slide.html,
    }),
  });

  const data = await ApiResponseHandler.handleResponse(
    response,
    `Failed to score slide ${slide.slide_number}`
  );

  return {
    score: data.score ?? 0,
    save_guidance: data.save_guidance ?? "",
    summary: data.summary ?? "",
    strengths: Array.isArray(data.strengths) ? data.strengths : [],
    risks: Array.isArray(data.risks) ? data.risks : [],
    suggested_fixes: Array.isArray(data.suggested_fixes)
      ? data.suggested_fixes
      : [],
    breakdown: {
      visual_fidelity: data.breakdown?.visual_fidelity ?? 0,
      editability: data.breakdown?.editability ?? 0,
      reusability: data.breakdown?.reusability ?? 0,
      readability: data.breakdown?.readability ?? 0,
      cleanliness: data.breakdown?.cleanliness ?? 0,
    },
    model: data.model,
    visual_provider: data.visual_provider,
  };
}

export function getCriticTone(score: number): "good" | "warn" | "bad" {
  if (score >= 85) return "good";
  if (score >= 65) return "warn";
  return "bad";
}

export function getCriticLabel(score: number): string {
  if (score >= 85) return "Strong";
  if (score >= 70) return "Usable";
  if (score >= 55) return "Needs polish";
  return "Weak";
}
