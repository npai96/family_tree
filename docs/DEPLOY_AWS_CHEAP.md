# Cheap AWS Deployment + GitHub Actions CI/CD

> This is the cheapest practical path for your current app: one Linux VM + Docker Compose + Caddy TLS + GitHub Actions.

## Target architecture (v1)

- 1x EC2 or Lightsail instance (small)
- Docker Compose services:
  - `app` (FastAPI)
  - `caddy` (reverse proxy + free TLS)
- Persistent data on instance disk:
  - SQLite DB file
  - media folder
- GitHub Actions:
  - CI: test on PR/push
  - CD: deploy main to server over SSH

## Cost expectation (rough)

- Lightsail 1 GB plan: about $5-7/month + bandwidth overages
- EC2 t4g.small + EBS + data transfer: often around $8-18/month depending usage

If you want dead-simple billing, start with Lightsail.

## One-time server setup

1. Create Ubuntu server.
2. Point your domain A record to server public IP.
3. SSH in and run:

```bash
cd ~
# copy repo or just copy deploy script first
bash deploy/ec2/bootstrap.sh
```

4. Re-login (docker group membership).

## GitHub repository secrets

Add these in GitHub -> Settings -> Secrets and variables -> Actions:

- `AWS_EC2_HOST` = server public IP or DNS
- `AWS_EC2_USER` = ssh user (usually `ubuntu`)
- `AWS_EC2_SSH_KEY` = private key (full PEM text)
- `APP_DOMAIN` = your domain (example: `family.example.com`)

## CI/CD behavior

- CI workflow: `.github/workflows/ci.yml`
  - runs tests on PR and push
- CD workflow: `.github/workflows/deploy-aws-ec2.yml`
  - triggers on push to `main`
  - uploads tarball via SCP
  - deploys via SSH
  - rebuilds/restarts containers via compose

## Verify deployment

On server:

```bash
cd ~/apps/family_tree/current
docker compose -f docker-compose.prod.yml ps
```

Health check:

```bash
curl -fsSL https://<your-domain>/health
```

## Notes for next phase (when traffic grows)

- move DB from SQLite -> Postgres (RDS or managed Postgres)
- move media from local disk -> S3
- add background workers for media derivatives
- add CloudWatch/log aggregation and alarms
