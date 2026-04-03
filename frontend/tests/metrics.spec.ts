import { test, expect } from "@playwright/test";

test.describe("Metrics Page", () => {
  test.beforeEach(async ({ page }) => {
    // Mock API endpoints
    await page.route("**/greenops/status", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          scheduler_running: true,
          grid_intensity_gco2_kwh: 250.5,
          is_low_carbon: false,
          carbon_threshold_gco2_kwh: 200,
          total_carbon_grams: 1.234,
          queries_deferred: 5,
          queued_tasks: 2,
          tasks: [
            { name: "reindex", priority: "low", age_hours: 0.5, max_defer_hours: 24 },
          ],
        }),
      });
    });

    await page.route("**/stream/metrics*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: 'event: metrics\ndata: {"queries_total": 42, "queries_successful": 40, "queries_failed": 2, "peers_connected": 3, "cpu_usage_percent": 25.5, "memory_usage_bytes": 104857600, "carbon_estimate_grams": 1.234, "grid_intensity_gco2_kwh": 250.5, "uptime_seconds": 3600, "timestamp": 1234567890}\n\n',
      });
    });

    await page.goto("/metrics");
  });

  test("should display the metrics page with title", async ({ page }) => {
    await expect(page.getByRole("heading", { name: /Observability/i })).toBeVisible();
  });

  test("should show key metrics cards", async ({ page }) => {
    await expect(page.getByText(/Total Queries/i)).toBeVisible();
    await expect(page.getByText(/Peers/i).first()).toBeVisible();
    await expect(page.getByText(/CPU Usage/i)).toBeVisible();
    await expect(page.getByText(/Memory/i)).toBeVisible();
  });

  test("should display query count from SSE stream", async ({ page }) => {
    // Wait for SSE data to arrive
    await expect(page.getByText("42")).toBeVisible({ timeout: 5000 });
  });

  test("should show carbon footprint section", async ({ page }) => {
    await expect(page.getByRole("heading", { name: /Carbon Footprint/i })).toBeVisible();
    await expect(page.getByText(/Total Emissions/i)).toBeVisible();
    await expect(page.getByText(/Grid Intensity/i)).toBeVisible();
  });

  test("should show scheduler status section", async ({ page }) => {
    await expect(
      page.getByRole("heading", { name: /Carbon-Aware Scheduler/i })
    ).toBeVisible();
    await expect(page.getByText(/Queued Tasks/i)).toBeVisible();
    await expect(page.getByText(/Deferred Queries/i)).toBeVisible();
  });

  test("should show Grafana dashboard section", async ({ page }) => {
    await expect(page.getByRole("heading", { name: /Grafana Dashboard/i })).toBeVisible();
  });

  test("should display uptime", async ({ page }) => {
    await expect(page.getByText(/Uptime/i)).toBeVisible();
  });

  test("should show CPU usage percentage", async ({ page }) => {
    // Wait for metrics to load
    await expect(page.getByText(/25.5%/i)).toBeVisible({ timeout: 5000 });
  });

  test("should indicate carbon status", async ({ page }) => {
    await expect(page.getByText(/Normal Grid Intensity/i)).toBeVisible({ timeout: 5000 });
  });
});
