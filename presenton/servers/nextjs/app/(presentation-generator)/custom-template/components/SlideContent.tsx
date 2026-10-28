'use client'

import React, { memo } from "react";
import { withBasePath } from "@/utils/basePath";

function normalizeTemplatePreviewAssets(markup: string) {
  if (!markup) return markup;

  const rewrite = (rawUrl: string) => {
    if (!rawUrl) return rawUrl;
    const normalizedUrl =
      rawUrl.startsWith("app_data/") || rawUrl.startsWith("static/")
        ? `/${rawUrl}`
        : rawUrl;
    if (normalizedUrl.startsWith("/slide_pro/_presenton/")) return normalizedUrl;
    if (
      normalizedUrl.startsWith("/app_data/") ||
      normalizedUrl.startsWith("/static/")
    ) {
      return withBasePath(normalizedUrl);
    }
    return normalizedUrl;
  };

  return markup
    .replace(
      /(src|href)=(["'])((?:\/)?(?:app_data|static)\/[^"']+)\2/g,
      (_, attr, quote, url) => `${attr}=${quote}${rewrite(url)}${quote}`
    )
    .replace(
      /url\((["']?)((?:\/)?(?:app_data|static)\/[^)"']+)\1\)/g,
      (_, quote, url) => `url(${quote}${rewrite(url)}${quote})`
    );
}

const SlideContent = memo(({ slide }: { slide: any }) => {
  const cleanHtml = slide.html
    .replace(/^```html\s*/i, "")
    .replace(/```$/g, "")
    .replace(/<!DOCTYPE html>/gi, "")
    .replace(/<html>/gi, "")
    .replace(/<\/html>/gi, "");
  const normalizedHtml = normalizeTemplatePreviewAssets(cleanHtml);
  return (
    <div
      dangerouslySetInnerHTML={{
        __html: normalizedHtml,
      }}
    />
  );
});

export default SlideContent;
