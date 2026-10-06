# Temporary sandbox tools

These standalone Python tools support local sandbox certification. They are not production ingress or an automatic Telegram setup service. No Odoo code is imported by them.

## Webhook-only gateway

```sh
python3 addons/omni_telegram/tools/webhook_gateway.py --port 8088 --upstream-port 8077
```

Bind Odoo itself to `127.0.0.1:8077`, set `--db-filter='^omni_build_20261006$'`, `--no-database-list`, `--workers=0` and `--max-cron-threads=0` for the current disposable sandbox. Keep its existing configuration and isolated data directory. The gateway binds only to loopback, then the temporary tunnel targets `http://127.0.0.1:8088`.

Only `GET /healthz` and `POST /omni/inbound/<canonical-uuid>` are available. The gateway rejects query strings, unsupported paths, missing/malformed/duplicate secret headers, ambiguous lengths, chunked requests and bodies over 1 MiB. Eight request slots, socket timeouts and a connection deadline bound resource use. It constructs a fresh local request with only content type, secret header and connection-close headers; cookies, incoming Host and proxy headers are discarded. Upstream response bodies/headers are not exposed. Logging excludes request metadata and bodies. Actual secret equality and endpoint/policy scope remain enforced by the Odoo adapter.

The health check proves gateway reachability only. It does not certify Odoo or Telegram. Nonexistent webhook endpoints return 404 from Odoo. This standard-library server is deliberately limited to a temporary development tunnel; use hardened managed ingress for production.

[Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) supply temporary HTTPS addresses without a domain/account. Launch with `cloudflared tunnel --no-autoupdate --protocol http2 --url http://127.0.0.1:8088`. The hostname changes on restart and the tunnel ends when its process stops. Do not tunnel directly to Odoo's port. Stop the tunnel first when closing a test session, then the gateway and isolated Odoo process. No system service is installed by this setup.

## Hidden-input secret provisioning

Create a private directory outside the checkout with mode 700. Run the helper interactively, passing only non-secret identifiers:

```sh
python3 addons/omni_telegram/tools/provision_sandbox_secret.py \
  --database omni_build_20261006 --company-id 1 --bot-id BOT_NUMERIC_ID \
  --output /tmp/omni-sandbox-runtime/telegram-secret.json
```

Enter the rotated token at the hidden prompt. The helper validates the bot prefix, creates a random webhook secret and writes a tenant-bound JSON bundle with mode 600. It refuses an existing file, a shared parent directory or noninteractive token input. The token is never placed in command arguments or printed. The local user's account remains trusted; this is a temporary secret injection input, not an encrypted vault.

Provisioning neither starts network access nor registers/sends anything. At the authorized connection step, the sandbox launcher must privately load the bundle into the selected `OMNI_SECRET_...` environment variable before starting Odoo. Never print the file, source it as shell code, commit it, or put its value on a command line. The current running Odoo process has no bundle loaded. Remove the temporary bundle once no longer needed under the agreed test lifecycle; `/tmp` is not durable storage.

## Checks

```sh
python3 -m unittest discover -s addons/omni_telegram/tools -p 'test_*.py'
```

Seven tests cover path/header/body restrictions, sanitized upstream failure, session/header stripping, secret-file mode/scope, identity checks and refusal to overwrite. These do not replace core Odoo/provider tests or actual live certification.
