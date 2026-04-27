# Postgres Cutover Runbook

> Practical checklist for moving one non-local environment from SQLite to Postgres.
> Keep the first cutover small, boring, and reversible.

## Current State

- Production still defaults to SQLite through `DB_PATH=/data/mvp.db`.
- Postgres runtime is available only when `DATABASE_URL` is set and `POSTGRES_RUNTIME_ENABLED=true`.
- The primary deploy path is GitHub Actions -> ECR -> SSM -> EC2.
- Media still lives on EC2 local disk. This runbook only moves the database.

## AWS Prerequisites

1. Create an RDS Postgres instance.
2. Put it in the same VPC as the EC2 app host.
3. Allow inbound Postgres traffic only from the EC2 app security group.
4. Enable automated RDS backups.
5. Confirm EC2 can reach the RDS endpoint on port `5432`.

## Store The Database URL

Store the production database URL in SSM Parameter Store as a SecureString:

```bash
aws ssm put-parameter \
  --name /family-tree/prod/database-url \
  --type SecureString \
  --value 'postgresql://USER:PASSWORD@RDS_ENDPOINT:5432/family_tree' \
  --overwrite
```

GitHub Actions should not print or store this raw URL.

## Required GitHub Variables

In GitHub `Settings -> Secrets and variables -> Actions -> Variables`:

- `DATABASE_URL_SSM_PARAMETER=/family-tree/prod/database-url`
- `POSTGRES_RUNTIME_ENABLED=true`

Leave those unset or set `POSTGRES_RUNTIME_ENABLED=false` while production should remain on SQLite.

## Required IAM Permission

The EC2 instance role needs permission to read the parameter during deploy because the SSM command runs on the instance:

```json
{
  "Effect": "Allow",
  "Action": "ssm:GetParameter",
  "Resource": "arn:aws:ssm:REGION:ACCOUNT_ID:parameter/family-tree/prod/database-url"
}
```

The GitHub OIDC deploy role still needs its existing SSM deploy permissions, but it does not need direct access to this SecureString.

## Pre-Cutover Backup

SSH/SSM into the EC2 host and copy the current SQLite DB:

```bash
cp /home/ubuntu/family_tree_data/data/mvp.db /home/ubuntu/family_tree_data/data/mvp.db.pre-postgres-cutover
```

Keep this file untouched until the Postgres runtime has been stable for a while.

## Export SQLite Data

On a trusted machine with the current SQLite DB:

```bash
python3 scripts/sqlite_to_postgres_runtime_export.py
```

This writes:

```text
db/generated/runtime_seed.sql
```

## Load Postgres Schema And Data

Load the compatibility schema:

```bash
psql "$DATABASE_URL" -f db/runtime_postgres.sql
```

Load the exported data:

```bash
psql "$DATABASE_URL" -f db/generated/runtime_seed.sql
```

## Compare Row Counts

At minimum compare these tables between SQLite and Postgres:

- `users`
- `circles`
- `circle_memberships`
- `persons`
- `relationships`
- `person_places`
- `media_assets`
- `context_events`
- `person_context_links`
- `discussion_threads`
- `discussion_messages`
- `change_requests`
- `circle_invitations`
- `audit_logs`
- `entity_revisions`
- `auth_sessions`

Do not cut over if counts are unexpectedly different.

## Cutover

1. Confirm `DATABASE_URL_SSM_PARAMETER` is set in GitHub variables.
2. Confirm `POSTGRES_RUNTIME_ENABLED=true` is set in GitHub variables.
3. Run `Deploy to AWS EC2 via SSM (Primary)`.
4. Confirm the GitHub health check passes.

Then verify from the app host:

```bash
curl -fsS http://127.0.0.1/health
```

Expected response includes:

```json
{"status":"ok","db_backend":"postgres"}
```

## Smoke Test

In the browser:

- sign in
- open a circle
- render a graph
- create and edit a person
- create and edit a relationship
- open timeline/context views
- check places/migration GeoJSON
- open existing media

## Rollback

If cutover fails:

1. Set GitHub variable `POSTGRES_RUNTIME_ENABLED=false`.
2. Clear or remove `DATABASE_URL_SSM_PARAMETER`.
3. Redeploy via `Deploy to AWS EC2 via SSM (Primary)`.
4. Confirm `/health` reports `db_backend: sqlite`.
5. Confirm the original SQLite file is still present at:

```text
/home/ubuntu/family_tree_data/data/mvp.db
```

## After Cutover

- Keep the SQLite backup for at least one release cycle.
- Watch app logs after the first real usage session.
- Add an automated RDS backup/restore drill.
- Plan the next storage migration: local media -> S3.
