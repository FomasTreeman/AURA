import { test, expect } from "@playwright/test";

test.describe("Query Page", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("should display the query page with title", async ({ page }) => {
    await expect(page.getByRole("heading", { name: /Ask AURA/i })).toBeVisible();
    await expect(
      page.getByPlaceholder(/Ask a question about your documents/i)
    ).toBeVisible();
  });

  test("should have a working query input", async ({ page }) => {
    const input = page.getByPlaceholder(/Ask a question about your documents/i);
    await input.fill("What is machine learning?");
    await expect(input).toHaveValue("What is machine learning?");
  });

  test("should have an Ask button", async ({ page }) => {
    const button = page.getByRole("button", { name: /Ask/i });
    await expect(button).toBeVisible();
  });

  test("should disable Ask button when input is empty", async ({ page }) => {
    const button = page.getByRole("button", { name: /Ask/i });
    // Button should be disabled when input is empty
    await expect(button).toBeDisabled();
  });

  test("should enable Ask button when input has text", async ({ page }) => {
    const input = page.getByPlaceholder(/Ask a question about your documents/i);
    const button = page.getByRole("button", { name: /Ask/i });

    await input.fill("Test question");
    await expect(button).toBeEnabled();
  });

  test("should show empty state message initially", async ({ page }) => {
    await expect(
      page.getByText(/Enter a question above to query your knowledge mesh/i)
    ).toBeVisible();
  });

  test("should submit query on form submit", async ({ page }) => {
    // Mock the SSE endpoint
    await page.route("**/stream/query*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: [
          'event: federation\ndata: {"local_count": 5, "peer_count": 0, "peers_responded": []}\n\n',
          'event: token\ndata: {"token": "Hello"}\n\n',
          'event: token\ndata: {"token": " world"}\n\n',
          'event: sources\ndata: {"sources": []}\n\n',
          'event: done\ndata: {"query_id": "test-123", "duration_ms": 500, "carbon_grams": 0.001}\n\n',
        ].join(""),
      });
    });

    const input = page.getByPlaceholder(/Ask a question about your documents/i);
    await input.fill("Test question");
    await input.press("Enter");

    // Wait for response to appear
    await expect(page.getByText("Hello world")).toBeVisible({ timeout: 10000 });
  });

  test("should display federation info when available", async ({ page }) => {
    await page.route("**/stream/query*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: [
          'event: federation\ndata: {"local_count": 10, "peer_count": 5, "peers_responded": ["peer1"]}\n\n',
          'event: token\ndata: {"token": "Response"}\n\n',
          'event: done\ndata: {"query_id": "test", "duration_ms": 100, "carbon_grams": 0.001}\n\n',
        ].join(""),
      });
    });

    const input = page.getByPlaceholder(/Ask a question about your documents/i);
    await input.fill("Test");
    await input.press("Enter");

    await expect(page.getByText(/local chunks/i)).toBeVisible({ timeout: 5000 });
  });
});
