# Asset infrastructure

The filesystem stores bytes; SQLite is the authoritative catalog for ownership,
lifecycle and lookup. Web routes and MCP adapters must call `AssetService`
rather than walking `outputs/users` directly.

## Rollout

1. Back up both `db/app_data.db` and the complete `outputs` directory.
2. Preview legacy discovery with `python -m app.asset_admin backfill --dry-run`.
3. Start the application or run `python -m app.asset_admin backfill` once.
4. Verify with `python -m app.asset_admin audit`.
5. Keep `PRINCIPAL_IDENTITY_MODE=compat` during the browser-cookie migration.
6. After active browsers have received `lc_principal`, change the mode to
   `enforced`. Do not re-enable `ALLOW_LEGACY_ANON_HEADER`.

Back up `db/principal_cookie.secret` with application secrets. Multi-instance
deployments must set the same explicit `PRINCIPAL_COOKIE_SECRET` on every host.

Backfill never moves or renames media. It reads existing sidecars and stores
relative paths in the `assets` table. The `asset_backfill` migration marker is
written only after a run completes without registration errors.

## Backup and recovery

`python -m app.asset_admin backup-db` uses SQLite's online backup API and runs an
integrity check before publishing the backup. It does **not** copy media files.
Infrastructure backups must capture the complete `outputs` directory and the DB
from the same operational window. Restore into an isolated directory first,
then run `python -m app.asset_admin audit` before serving traffic.

## Compatibility boundary

The legacy unsigned `anon_id` cookie is accepted only in `compat` mode and is
immediately upgraded to a signed, HTTP-only cookie. The raw `X-Anon-Id` header
is disabled by default. Client IP is audit information, not browser gallery
ownership.

Static JSON sidecars under `/outputs/users` are blocked. New consumers should
use the ownership-checked `/api/v1/assets/{asset_id}/content` and `thumbnail`
endpoints. Existing image URLs remain available during the UI transition.
