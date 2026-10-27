import { expect, test } from "@playwright/test";

const BASE_URL =
  process.env.WEB_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE ||
  "http://localhost:3000";

test.describe("Research Quiz Gen Plus Wrapper", () => {
  test("renders Quiz Gen Plus inside Research Mode as an embedded iframe", async ({
    page,
  }) => {
    await page.route("**/api/v1/knowledge/list", (route) =>
      route.fulfill({
        status: 200,
        headers: { "content-type": "application/json" },
        body: JSON.stringify([{ name: "Default KB", is_default: true }]),
      }),
    );

    await page.route("**/research/_quiz_gen_plus/index.html", (route) =>
      route.fulfill({
        status: 200,
        headers: { "content-type": "text/html" },
        body: "<html><body><h1>Quiz Gen Plus Embedded UI</h1></body></html>",
      }),
    );

    await page.route("**/research/_quiz_gen_plus/**", (route) =>
      route.fulfill({
        status: 200,
        headers: { "content-type": "text/html" },
        body: "<html><body><h1>Quiz Gen Plus Embedded UI</h1></body></html>",
      }),
    );

    await page.goto(`${BASE_URL}/research`);
    await page.getByRole("button", { name: "Quiz Gen Plus" }).click();

    await expect(
      page.getByRole("link", { name: "Open source site" }),
    ).toBeVisible();

    const iframe = page.locator('iframe[title="Quiz Gen Plus"]');
    await expect(iframe).toBeVisible();
    await expect(iframe).toHaveAttribute(
      "src",
      "/research/_quiz_gen_plus/index.html",
    );
  });

  test("shows retry state when Quiz Gen Plus upstream is down", async ({
    page,
  }) => {
    await page.route("**/api/v1/knowledge/list", (route) =>
      route.fulfill({
        status: 200,
        headers: { "content-type": "application/json" },
        body: JSON.stringify([{ name: "Default KB", is_default: true }]),
      }),
    );

    await page.route("**/research/_quiz_gen_plus/**", (route) =>
      route.fulfill({
        status: 503,
        headers: { "content-type": "text/plain" },
        body: "upstream unavailable",
      }),
    );

    await page.route("**/research/_quiz_gen_plus/index.html", (route) =>
      route.fulfill({
        status: 503,
        headers: { "content-type": "text/plain" },
        body: "upstream unavailable",
      }),
    );

    await page.goto(`${BASE_URL}/research`);
    await page.getByRole("button", { name: "Quiz Gen Plus" }).click();

    await expect(
      page.getByText("Quiz Gen Plus is temporarily unavailable"),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Retry connection" }),
    ).toBeVisible();
    await expect(page.locator('iframe[title="Quiz Gen Plus"]')).toHaveCount(0);
  });
});
