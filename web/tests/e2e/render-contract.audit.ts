import { expect, test } from "@playwright/test";

import {
  colorToPpt,
  estimateTextOverflow,
  isTitleElement,
  previewFontFamily,
  resolveOfficeFont,
} from "../../lib/slidePro/renderContract";
import type { SlideElement, SlideProDeck } from "../../types/slidePro";

const mockDeck: SlideProDeck = {
  version: "1.1",
  deck_id: "mock",
  meta: {
    title: "Mock",
    language: "en",
    template_id: "academic_evidence",
  },
  size: { width: 1600, height: 900 },
  theme: {
    palette: {
      background: "#F6F9FF",
      foreground: "#0F172A",
      accent: "#0EA5E9",
      muted: "#475569",
    },
    fonts: {
      title: "Sora",
      body: "IBM Plex Sans",
    },
  },
  slides: [],
};

test("alpha color parser returns pptx color + transparency", async () => {
  const color = colorToPpt("#0EA5E933", "#FFFFFF");
  expect(color.color).toBe("0EA5E9");
  expect(color.transparency).toBe(80);
});

test("font mapping keeps title/body parity between preview and export contract", async () => {
  expect(resolveOfficeFont(mockDeck.theme.fonts.title, "title")).toBe("Aptos");
  expect(resolveOfficeFont(mockDeck.theme.fonts.body, "body")).toBe("Calibri");
  expect(previewFontFamily(mockDeck, "title")).toContain("Aptos");
  expect(previewFontFamily(mockDeck, "body")).toContain("Calibri");
  expect(isTitleElement({ id: "s1_title" } as SlideElement)).toBeTruthy();
  expect(isTitleElement({ id: "s1_objective" } as SlideElement)).toBeFalsy();
});

test("overflow estimator flags dense text for constrained layout box", async () => {
  const overflowing: SlideElement = {
    id: "s1_bullets",
    type: "bullets",
    box: { x: 96, y: 300, w: 460, h: 130, rot: 0 },
    style: { fontSize: 24, lineHeight: 1.28, color: "#0F172A" },
    content: [
      "Claim: completion reached 72% with measurable gains across all cohorts.",
      "Evidence: benchmark report documents sustained uplift over twelve weeks.",
      "Implication: scale implementation while preserving quality controls.",
      "Additional detail: maintain diagnostics and monitor failure cases.",
    ],
  };
  const fitted: SlideElement = {
    ...overflowing,
    box: { ...overflowing.box, h: 300 },
  };

  expect(estimateTextOverflow(overflowing)).toBeTruthy();
  expect(estimateTextOverflow(fitted)).toBeFalsy();
});
