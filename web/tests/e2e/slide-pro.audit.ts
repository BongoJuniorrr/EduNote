import { expect, test } from "@playwright/test";

const BASE_URL =
  process.env.WEB_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE ||
  "http://localhost:3000";

test.describe("Slides Presenton Wrapper", () => {
  test("renders /slide_pro as Presenton iframe wrapper and keeps sidebar entry", async ({ page }) => {
    const legacyRequests: string[] = [];

    page.on("request", (request) => {
      if (request.url().includes("/api/v1/slide-pro/")) {
        legacyRequests.push(request.url());
      }
    });

    await page.route("**/slide_pro/_presenton/health", (route) =>
      route.fulfill({
        status: 200,
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ status: "ok" }),
      }),
    );

    await page.route("**/slide_pro/_presenton/presentation", (route) =>
      route.fulfill({
        status: 200,
        headers: { "content-type": "text/html" },
        body: "<html><body><h1>Presenton Embedded UI</h1></body></html>",
      }),
    );

    await page.goto(`${BASE_URL}/slide_pro`);

    await expect(page.getByRole("heading", { name: "Slides" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Slides" })).toBeVisible();

    const iframe = page.locator('iframe[title="Presenton Slides"]');
    await expect(iframe).toBeVisible();
    await expect(iframe).toHaveAttribute("src", "/slide_pro/_presenton/presentation");

    expect(legacyRequests).toHaveLength(0);
  });

  test("shows retry/error state when Presenton upstream is down", async ({ page }) => {
    await page.route("**/slide_pro/_presenton/**", (route) =>
      route.fulfill({
        status: 503,
        headers: { "content-type": "text/plain" },
        body: "upstream unavailable",
      }),
    );

    await page.goto(`${BASE_URL}/slide_pro`);

    await expect(page.getByText("Slides service is temporarily unavailable")).toBeVisible();
    await expect(page.getByRole("button", { name: "Retry connection" })).toBeVisible();
    await expect(page.locator('iframe[title="Presenton Slides"]')).toHaveCount(0);
  });
});
