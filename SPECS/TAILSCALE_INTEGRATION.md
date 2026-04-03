# Tailscale Integration — AURA

Purpose
- Describe how to use Tailscale (or a self-hosted alternative like Headscale) to provide secure, authenticated, encrypted networking for both single-office (LAN-first) and multi-office federation for AURA.
- Explain recommended deployment modes, config changes, security controls, operational flows, and DevOps integration points.
- Show minimal examples and checklist items so teams can adopt Tailscale quickly and safely while preserving AURA's P2P identity and security model.

Summary / Motivation
- Running a fully P2P AURA network over raw public IPs is operationally heavy (NAT, firewalls, certificates). Tailscale provides a simple mesh VPN with:
  - Encrypted, authenticated connections (WireGuard-based).
  - Stable per-device Tailscale IPs (100.x.y.z or magic DNS names) that can be used as `P2P_ADVERTISE_HOST`.
  - ACLs, short-lived auth keys, device tags and SSO integration for centralized device admission.
- Benefits:
  - Simplifies multi-office federation: devices in different offices join the same tailnet and can dial AURA P2P ports directly without complex site-to-site VPN setup.
  - Limits cloud exposure: tailnet membership is controlled centrally; you can avoid open public ports and rely on encrypted overlay.
  - Eases provisioning: use auth keys / automated tailscaled bootstrap to onboard devices.

Design overview
- Each physical device (or edge gateway) runs tailscaled (Tailscale daemon) and becomes a tailnet member. AURA backend continues to run locally.
- AURA config points `P2P_ADVERTISE_HOST` to the device's Tailscale IP (or MagicDNS name), so peers dial the Tailscale address.
- mDNS discovery can remain enabled for local LAN discovery. For cross-office federation, rely on Tailscale (tailnet) discovery + Rendezvous disabled or used as fallback.
- Optionally run a Tailscale subnet router in each office (a gateway) to expose an office LAN range into the tailnet for devices that cannot run tailscaled directly.

How it maps to AURA components
- P2P network:
  - The `AuraP2PAdapter` listens on `P2P_HOST:P2P_PORT` (typically `0.0.0.0:9000`).
  - Advertised multiaddr becomes `/ip4/<P2S_IP>/tcp/9000/p2p/<peer_id>` where `<P2S_IP>` is the Tailscale IP.
- Discovery:
  - For multi-office, mDNS is not sufficient; use tailnet connectivity to dial peers. Rendezvous remains optional — tailscale reduces the need for a public rendezvous.
- Security:
  - Tailscale secures transport. Continue to use AURA's signing/envelope protocol at the application layer. This provides defense-in-depth: even if a tailnet device is compromised, AURA message-level signatures restrict malicious behavior.
- DevOps & provisioning:
  - Use Tailscale auth keys (prefers ephemeral or scoped keys) stored in a secrets manager. CI/CD can produce signed images and a tailscale bootstrap. For air-gapped shops use Headscale.

Recommended deployment patterns

1) Per-device tailscaled (recommended)
- Install `tailscaled` on each device.
- Start tailscaled and `tailscale up --authkey <PREAUTH_KEY> --hostname aura-node-<id>`.
- Configure `P2P_ADVERTISE_HOST` to the Tailscale IPv4 address (e.g., 100.x.x.x) or to the MagicDNS hostname (e.g., aura-node-01.tailnet.example.com).
- Start AURA backend (container or service) binding to `0.0.0.0` and port `P2P_PORT`.

Pros:
- Direct, encrypted device-to-device connections.
- Fine-grained device admission via Tailscale ACLs and tags.

Cons:
- Each device must run tailscaled and manage tailscale updates.

2) Office gateway / subnet router
- Run a single tailscaled subnet-router on an office gateway (e.g., a small VM or physical server).
- That gateway advertises the office subnet into the tailnet. Devices that cannot run tailscaled join by normal LAN connectivity and are reachable across tailnet via the gateway.
- Configure AURA nodes on devices to advertise the gateway-provided tailnet IP (or use the device's own tailnet IP if it also runs tailscaled).

Pros:
- Minimal changes on constrained devices.
- Centralized tailnet control for an office.

Cons:
- Gateway becomes a dependency; gatekeeper availability matters.

3) Containerized tailscaled (advanced)
- Run tailscaled in host network mode so that the Tailscale IP is reachable by the AURA container network.
- Typical pattern:
  - run `tailscaled` on host,
  - start `tailscale up` on host or in privileged container,
  - run AURA container with `--network host` so `P2P_ADVERTISE_HOST` can use the host Tailscale IP.
- Avoid putting tailscaled in the same container namespace as the app unless you understand network namespace isolation.

Configuration changes & env recommendations
- Recommended env variables:
```/dev/null/example.env#L1-20
P2P_HOST=0.0.0.0
P2P_PORT=9000
P2P_MDNS_ENABLED=true               # keep for local LAN discovery
P2P_ADVERTISE_HOST=<TAILSCALE_IP>   # e.g., 100.101.102.103 or magic DNS host
RENDEZVOUS_URL=                     # optional; can be left empty if tailscale is used
```
- How to set the Tailscale IP:
  - Programmatically: `tailscale ip -4` returns the device tailnet IPv4; CI or provisioning scripts can set `P2P_ADVERTISE_HOST` automatically.
  - Or use MagicDNS names and set `P2P_ADVERTISE_HOST` to the hostname (ensure DNS resolves to the tailnet IP on each node).

Bootstrap & provisioning examples
- Admin flow (small fleet):
  1. Create ephemeral pre-auth key in Tailscale admin console: `tailscale admin preauthkey create --reusable=false --expiry=1h --tags role=aura-node`.
  2. On each node: install tailscale, `sudo tailscaled`, then `tailscale up --authkey <KEY> --hostname aura-node-<id>`.
  3. Confirm `tailscale status` and `tailscale ip -4`.
  4. Set `P2P_ADVERTISE_HOST` to `tailscale ip -4` and start AURA.

- Automated provisioning (DevOps):
  - Use secrets manager (Vault/Secrets Manager) to distribute short-lived pre-auth keys per host.
  - CI produces signed config bundles containing the preauth key and orchestration manifest.
  - Use a provisioning helper script (example below) to `tailscale up` and write the environment file.

Tailscale auth-key lifecycle & best practices
- Prefer short-lived, single-use pre-auth keys tied to device tags.
- Use tags like `role:aura-node` and use Tailscale ACL rules to restrict who can talk to what (see Security section).
- Rotate keys regularly and revoke lost/compromised keys immediately via admin console or API.
- For organizations, enable SSO-based login and require device approval policies in the Tailscale admin console.

Security considerations
- Transport security: Tailscale provides WireGuard encryption. This should be considered the primary transport encryption.
- Application-level auth: maintain all AURA message-level signing, verification and revocation checks (it’s already present in code). Do not rely only on Tailscale for authorization.
- ACLs: enforce Tailscale ACLs so only approved devices can dial port 9000 (or other P2P ports). Example ACL rules can restrict source-destination pairs or only allow devices with a `role:aura-node` tag to reach `100.101.102.103:9000`.
- Device trust: require manual device approval for unknown machines; use SSO & device postures where possible.
- Headscale option: for fully self-hosted tailnet control, use Headscale instead of Tailscale; it provides equivalent functionality with local control.
- Logging and privacy: Tailscale routes encrypted traffic; audits are available in Tailscale admin logs for connections. Continue to redact sensitive content at application logging level.

Operational notes & troubleshooting
- Verify connectivity:
  - `tailscale status` to see peers.
  - `tailscale ping <peer>` to check latency.
  - Confirm that the AURA `multiaddr` is reachable: `nc -vz <TAILSCALE_IP> 9000` (or `curl` to a simple connect-check endpoint).
- NAT/DERP: Tailscale uses DERP relays if direct NAT traversal fails. Expect some additional latency in those cases; for low-latency local federation, ensure direct connections (NAT hole-punching) are possible or use subnet routers.
- Performance: measure latency and throughput; LLM streaming is sensitive to latency — prefer local Ollama or same-region hosts to minimize tailscale relay hops.
- MTU: tailscale may reduce MTU; ensure your application avoids extremely large UDP datagrams or excessive jumbo frames.
- DNS: MagicDNS simplifies naming (`aura-node-01.tailnet.example.com`); ensure nodes can resolve each other or use ips directly.

Multi-office federation patterns using Tailscale
- Pattern A: All devices in all offices join the same tailnet
  - Simpler: join all devices to one tailnet (controlled ACLs).
  - Pros: direct dialing between any offices/devices.
  - Cons: central tailnet management; if you want separation between orgs/customers, use multiple tailnets.

- Pattern B: One tailnet per office + inter-site tailscale peering (via shared user accounts or routing)
  - Use a central headscale/Tailscale account to allow selected peers from Offices A & B to communicate (or use subnet routers at each office that are tailnet members).
  - Pros: separation by default; controlled cross-office links.
  - Cons: slightly more complex routing.

- Pattern C: Hybrid — local tailnet + cloud rendezvous/registry
  - Use tailscale primarily for transport; use a central Rendezvous for management metadata, audit, and to store allowlists.
  - Ensure all rendezvous interactions are authenticated & encrypted.

DevOps integration & CI/CD
- Secrets:
  - Store Tailscale pre-auth keys in the org secrets manager and distribute as ephemeral credentials via provisioning scripts.
- CI:
  - CI should never call production tailnet devices directly. For integration tests, run a local tailscaled (or mock) in ephemeral CI runners or use a Headscale test instance.
- Automation:
  - Provide a `provision_tailscale.sh` script or Ansible role that:
    - Installs tailscaled,
    - Runs `tailscale up --authkey ...`,
    - Fetches the tailnet IP and writes `P2P_ADVERTISE_HOST` to the AURA env file,
    - Starts AURA service.
- Audit & telemetry:
  - Integrate Tailscale admin logs into central SIEM if permitted.
  - Collect tailnet connection metrics (DERP usage, direct vs relay) to measure cross-office performance.

Example quickstart (commands)
- On device (admin-approved preauth key):
```/dev/null/example-commands.sh#L1-50
# install tailscale (OS dependent)
sudo apt-get install -y tailscale

# start tailscaled (systemd usually)
sudo systemctl enable --now tailscaled

# bring up the device onto the tailnet (use your preauth key)
sudo tailscale up --authkey tskey-xxxxxxxx --hostname aura-node-01

# get tailscale IP
TAILSCALE_IP=$(tailscale ip -4)

# set env and start AURA (example)
export P2P_ADVERTISE_HOST=$TAILSCALE_IP
export P2P_HOST=0.0.0.0
export P2P_PORT=9000

# start aura (systemd/docker)
# e.g., docker run --network host -e P2P_ADVERTISE_HOST=$P2P_ADVERTISE_HOST ...
```

Testing & validation checklist
- Per-device:
  - Tailscale is up and `tailscale status` shows peer devices.
  - AURA binds successfully and reports `multiaddr` with Tailscale IP.
  - A simple federated query between node A and B succeeds and shows `peers_responded` > 0.
- Multi-office:
  - Verify two offices can reach each other's Tailscale IPs directly (no DERP relay) when possible.
  - Run a load test for SSE streaming across sites to measure latency and throughput.
- Security:
  - Attempt to dial P2P port from a non-authorized tailscale device: should be blocked by ACL or Tailscale admin configuration.
  - Revoke a device in Tailscale and confirm it no longer appears in AURA peer lists.

Edge cases and caveats
- mDNS over tailscale: mDNS does not naturally cross Tailscale meshes. Use MagicDNS or Rendezvous for cross-site discovery.
- Tailscale relays (DERP) may increase latency — for production-grade cross-office inference, consider colocated model hosts or gateway placement.
- Air-gapped offices: use Headscale and local pre-auth key generation rather than public Tailscale service.

Operational recommendations (short list)
- Use short-lived, scoped pre-auth keys and device tags.
- Require device approval for new devices joining tailnet.
- Maintain AURA application-level signing & revocation regardless of tailscale.
- Use MagicDNS for simpler hostnames and avoid hardcoding IPv4s when possible.
- Automate provisioning via scripts integrated with secrets manager and orchestration.
- Monitor DERP use and prefer direct NAT traversal for performance.

Appendix: Sample env fragment (final)
```/dev/null/example.env#L1-12
# Tailscale-backed P2P
P2P_HOST=0.0.0.0
P2P_PORT=9000
P2P_MDNS_ENABLED=true
P2P_ADVERTISE_HOST=$(tailscale ip -4) # set at provisioning time
RENDEZVOUS_URL=                        # optional; leave empty if not used
```

If you want, I can:
- Add a `scripts/provision_tailscale.sh` provisioning script (install tailscaled, tailscale up, write env file).
- Produce a `docker-compose.tailscale.yml` showing the recommended `--network host` pattern and workflow.
- Draft Tailscale ACL examples for `role:aura-node` and a sample admin onboarding flow.
Which of those would you like next?