import { test, expect } from "@playwright/test";

test.describe("Peers Page", () => {
  test.beforeEach(async ({ page }) => {
    // Mock API endpoints
    await page.route("**/network/status", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          running: true,
          peer_id: "QmTestPeerId12345",
          multiaddr: "/ip4/127.0.0.1/tcp/9000/p2p/QmTestPeerId12345",
          peers: 3,
          mdns_enabled: true,
        }),
      });
    });

    await page.route("**/security/status", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          did_active: true,
          peer_id: "QmTestPeerId12345",
          did: "did:key:QmTestPeerId12345",
          revocation_manager_active: true,
          tombstoned_cids: 0,
          cid_enforcement: "enabled",
          auth_proof_type: "ed25519_assertion",
        }),
      });
    });

    await page.route("**/stream/peers*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: 'event: peers\ndata: {"running": true, "peer_id": "QmTest", "peer_count": 2, "peers": [{"peer_id": "Qm123...", "peer_id_full": "Qm1234567890", "multiaddrs": ["/ip4/192.168.1.100/tcp/9000"], "latency_ms": null}], "timestamp": 1234567890}\n\n',
      });
    });

    await page.goto("/peers");
  });

  test("should display the peers page with title", async ({ page }) => {
    await expect(page.getByRole("heading", { name: /P2P Network/i })).toBeVisible();
  });

  test("should show network status cards", async ({ page }) => {
    await expect(page.getByText(/Network Status/i)).toBeVisible();
    await expect(page.getByText(/Connected Peers/i).first()).toBeVisible();
    await expect(page.getByText(/Security/i)).toBeVisible();
  });

  test("should display connection status", async ({ page }) => {
    // Wait for the status to load
    await expect(page.getByText(/Connected/i).first()).toBeVisible({ timeout: 5000 });
  });

  test("should show this node info section", async ({ page }) => {
    await expect(page.getByRole("heading", { name: /This Node/i })).toBeVisible();
    await expect(page.getByText(/Peer ID/i).first()).toBeVisible();
    await expect(page.getByText(/Multiaddr/i)).toBeVisible();
  });

  test("should have copy button for peer ID", async ({ page }) => {
    const copyButton = page.locator("button").filter({ has: page.locator("svg") }).first();
    await expect(copyButton).toBeVisible();
  });

  test("should show connected peers list section", async ({ page }) => {
    await expect(
      page.getByRole("heading", { name: /Connected Peers/i }).nth(1)
    ).toBeVisible();
  });

  test("should have refresh button", async ({ page }) => {
    await expect(page.getByRole("button", { name: /Refresh/i })).toBeVisible();
  });
});
