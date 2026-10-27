import { test, expect } from "@playwright/test";
import fs from "node:fs";

const BASE_URL =
  process.env.WEB_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE ||
  "http://localhost:3000";

type WorkflowType =
  | "slide_deck"
  | "exam_blueprint"
  | "lesson_plan"
  | "learning_outcome_mapper"
  | "rubric_builder"
  | "misconception_detector"
  | "adaptive_quiz_coach"
  | "curriculum_alignment"
  | "content_safety_fact_check";

const WORKFLOW_LABELS: Array<{ id: WorkflowType; label: string }> = [
  { id: "slide_deck", label: "Slide Generator" },
  { id: "exam_blueprint", label: "Exam Matrix Builder" },
  { id: "lesson_plan", label: "Lesson Plan Generator" },
  { id: "learning_outcome_mapper", label: "Learning Outcome Mapper" },
  { id: "rubric_builder", label: "Rubric Builder" },
  { id: "misconception_detector", label: "Misconception Detector" },
  { id: "adaptive_quiz_coach", label: "Adaptive Quiz Coach" },
  { id: "curriculum_alignment", label: "Curriculum Alignment Checker" },
  { id: "content_safety_fact_check", label: "Safety & Fact Checker" },
];

function buildWorkflowCatalog() {
  return {
    workflows: WORKFLOW_LABELS.map((item) => ({
      id: item.id,
      name: item.label,
      description: `${item.label} description`,
      templates: [
        {
          id: "default",
          name: "Default Template",
          description: "Default template",
          settings:
            item.id === "slide_deck"
              ? {
                  target_grade: "University",
                  duration_minutes: 45,
                  slide_count: 10,
                  style: "clean-academic",
                }
              : {
                  mode: "default",
                },
        },
      ],
    })),
  };
}

function buildRunResponse(workflow: WorkflowType) {
  const base = {
    success: true,
    workflow,
    run_id: `edu_test_${workflow}`,
    artifact_base_url: `/api/outputs/edu-studio/edu_test_${workflow}/artifacts`,
    artifacts: [],
    parsed_materials: [],
    warnings: [],
  };

  if (workflow === "slide_deck") {
    return {
      ...base,
      result: {
        workflow,
        title: "Slide Deck Test",
        summary: "Deck summary",
        deliverable_markdown:
          "# Slide Deck Test\n\nEquation: $O(n^2)$ and inline \\(a^2+b^2\\).",
        structured_data: {
          deck_theme: {
            palette: {
              background: "#F8FAFC",
              foreground: "#0F172A",
              accent: "#0EA5E9",
              muted: "#475569",
            },
            typography: {
              font_family: "Inter, Segoe UI, sans-serif",
              title_scale: "2rem",
              body_scale: "1rem",
            },
            visual_style: "clean-academic",
            ratio: "16:9",
          },
          slides: [
            {
              title: "Slide 1",
              objective: "Explain complexity",
              key_points: ["$O(n^2)$", "Use an architecture comparison table"],
              activity: "Discuss the scaling behavior",
              speaker_notes: "Keep formulas simple",
              layout_hint: "equation",
              visual_hint: "icon-set:education",
              visual_prompt:
                "Show a central equation card with two side callouts for complexity and optimization.",
            },
            {
              title: "Slide 2",
              objective: "Summarize",
              key_points: ["System design", "Evaluation checklist"],
              activity: "Quick quiz",
              speaker_notes: "End with recap",
              layout_hint: "summary",
              visual_hint: "diagram:summary",
              visual_prompt:
                "Create a layered summary board with three checklist panels and one highlighted takeaway.",
            },
          ],
          design_guidelines: ["Consistent spacing"],
          assessment_checkpoints: ["Question after each section"],
        },
        quality_checks: [{ name: "basic_validation", status: "pass", detail: "ok" }],
        next_actions: ["next"],
      },
    };
  }

  return {
    ...base,
    result: {
      workflow,
      title: `${workflow} title`,
      summary: `${workflow} summary`,
      deliverable_markdown: `# ${workflow}\n\n- output item`,
      structured_data: { output: [{ id: workflow, value: "ok" }] },
      quality_checks: [{ name: "basic_validation", status: "pass", detail: "ok" }],
      next_actions: ["next"],
    },
  };
}

test.describe("Edu Studio :: Full workflow regression", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/api/v1/edu-studio/templates", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(buildWorkflowCatalog()),
      });
    });

    await page.route("**/api/v1/edu-studio/llm-options", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          configs: [
            {
              id: "qwen_teacher_env",
              name: "Qwen-Teacher (.env)",
              provider: "huggingface",
              model: "qwen-test",
              is_active: false,
              metadata: { device: "cuda:1" },
            },
          ],
        }),
      });
    });

    await page.route("**/api/v1/knowledge/list", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          { name: "exploring_cs", is_default: true },
          { name: "teaching_materials", is_default: false },
        ]),
      });
    });
  });

  test("runs all workflows and shows output", async ({ page }) => {
    await page.route("**/api/v1/edu-studio/run", async (route) => {
      const payload = route.request().postDataJSON() as { workflow: WorkflowType };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(buildRunResponse(payload.workflow)),
      });
    });

    await page.goto(`${BASE_URL}/edu_studio`);

    const workflowSelect = page.locator('label:has-text("Workflow") + select');
    for (const workflow of WORKFLOW_LABELS) {
      await workflowSelect.selectOption({ label: workflow.label });
      await page.getByRole("button", { name: /Run/i }).click();
      await expect(page.getByText("Workflow Output")).toBeVisible();
      await expect(
        page.locator("h3").filter({
          hasText: new RegExp(`${workflow.id} title|Slide Deck Test`),
        }),
      ).toBeVisible();
      await expect(page.getByText("Structured Data")).toBeVisible();
    }
  });

  test("renders latex and supports PDF/PPT export with artifact upload", async ({ page }) => {
    await page.route("**/api/v1/edu-studio/run", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(buildRunResponse("slide_deck")),
      });
    });

    let uploadCount = 0;
    await page.route("**/api/v1/edu-studio/runs/*/artifacts", async (route) => {
      uploadCount += 1;
      const artifact =
        uploadCount === 1
          ? {
              file_name: "edu_test_slide_deck_slides.pdf",
              size_bytes: 2048,
              content_type: "application/pdf",
              uploaded_at: new Date().toISOString(),
              url: "/api/outputs/edu-studio/edu_test_slide_deck/artifacts/edu_test_slide_deck_slides.pdf",
            }
          : {
              file_name: "edu_test_slide_deck_slides.pptx",
              size_bytes: 3072,
              content_type:
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
              uploaded_at: new Date().toISOString(),
              url: "/api/outputs/edu-studio/edu_test_slide_deck/artifacts/edu_test_slide_deck_slides.pptx",
            };

      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          run_id: "edu_test_slide_deck",
          artifact_base_url: "/api/outputs/edu-studio/edu_test_slide_deck/artifacts",
          artifacts: [artifact],
        }),
      });
    });

    await page.goto(`${BASE_URL}/edu_studio`);
    await page.getByRole("button", { name: /Run/i }).click();

    await expect(page.locator(".katex").first()).toBeVisible();
    await expect(page.getByTestId("slide-illustration").first()).toBeVisible();

    const pdfDownload = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export PDF" }).click();
    const pdf = await pdfDownload;
    const pdfPath = await pdf.path();
    expect(pdfPath).toBeTruthy();
    if (pdfPath) {
      expect(fs.statSync(pdfPath).size).toBeGreaterThan(0);
    }

    const pptDownload = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export PowerPoint" }).click();
    const ppt = await pptDownload;
    const pptPath = await ppt.path();
    expect(pptPath).toBeTruthy();
    if (pptPath) {
      expect(fs.statSync(pptPath).size).toBeGreaterThan(0);
    }

    await expect(page.getByText("Persisted Artifacts")).toBeVisible();
    await expect(page.getByRole("link", { name: /slides\.pdf/i })).toBeVisible();
    await expect(page.getByRole("link", { name: /slides\.pptx/i })).toBeVisible();
  });

  test("shows friendly error when backend returns failure", async ({ page }) => {
    await page.route("**/api/v1/edu-studio/run", async (route) => {
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Simulated backend failure" }),
      });
    });

    await page.goto(`${BASE_URL}/edu_studio`);
    await page.getByRole("button", { name: /Run/i }).click();
    await expect(page.getByText("Simulated backend failure")).toBeVisible();
  });

  test("run-with-files path works and qwen teacher page is reachable", async ({ page }) => {
    await page.route("**/api/v1/edu-studio/run-with-files", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(buildRunResponse("lesson_plan")),
      });
    });

    await page.goto(`${BASE_URL}/edu_studio`);
    await page.locator('input[type="file"]').setInputFiles({
      name: "material.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("Uploaded material"),
    });

    await page.getByRole("button", { name: /Run/i }).click();
    await expect(page.getByText("lesson_plan title")).toBeVisible();

    await page.getByRole("link", { name: "Qwen-Teacher Model" }).click();
    await expect(page).toHaveURL(/\/edu_studio\/qwen_teacher$/);
    await expect(page.getByText("Qwen-Teacher Model Showcase")).toBeVisible();
  });
});
