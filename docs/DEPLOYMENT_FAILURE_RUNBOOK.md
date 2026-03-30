# Deployment Failure Runbook

> Practical triage notes for when deploys fail. Start narrow, identify which layer is broken, then fix only that layer.

## Current primary deploy path

Normal path now:

- GitHub Actions
- assume AWS role via OIDC
- build image
- push image to ECR
- call AWS SSM
- EC2 pulls image from ECR
- `docker compose` restarts app
- health check runs over SSM

Fallback path:

- `.github/workflows/deploy-aws-ec2.yml`
- use only if the SSM path is broken

## First question: where did it fail?

Look at the failed workflow step name first.

Use this map:

1. `Configure AWS credentials`
- problem is GitHub OIDC / IAM trust

2. `Login to Amazon ECR` or `Build and push image`
- problem is ECR authz or image push permissions

3. `Trigger deploy command via SSM`
- problem is GitHub role missing SSM permissions, wrong instance ID, or SSM not targeting the instance properly

4. `Wait for SSM deploy completion` or `Show SSM command output`
- GitHub reached SSM, but the command failed on the EC2 instance

5. `Verify app health over SSM`
- deploy command completed, but the app is unhealthy after restart

## Triage by layer

## A) GitHub -> AWS auth failure

Symptoms:

- `configure-aws-credentials` fails
- assume-role / OIDC / `AccessDenied` errors before any build/push

Check:

- GitHub secret `AWS_GITHUB_ACTIONS_ROLE_ARN`
- IAM role trust policy matches repo `npai96/family_tree`
- trust policy `sub` matches the branch/ref you are deploying from

## B) ECR push failure

Symptoms:

- `docker push` denied
- missing `ecr:*` upload permissions

Check:

- GitHub IAM role has ECR push policy
- `AWS_REGION` GitHub variable is correct
- `ECR_REPOSITORY` GitHub variable matches the actual ECR repo name

Known-good model:

- GitHub role can push `family-tree:<sha>` and `family-tree:latest`

## C) SSM send-command failure

Symptoms:

- `ssm:SendCommand` access denied
- workflow never gets a `CommandId`

Check:

- GitHub IAM role has:
  - `ssm:SendCommand`
  - `ssm:GetCommandInvocation`
  - `ssm:ListCommandInvocations`
- GitHub variable `AWS_EC2_INSTANCE_ID` is correct
- SSM target instance exists and is online in `Managed nodes`

## D) SSM command runs but fails on EC2

Symptoms:

- `Waiter CommandExecuted failed`
- `Show SSM command output` contains shell/app errors

This is usually the most useful failure because it gives the real server-side error.

Use the `StdOut` and `StdErr` in the workflow first.

Then SSH to EC2 and check:

```bash
cd ~/apps/family_tree/current
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=100 app
docker compose -f docker-compose.prod.yml logs --tail=100 caddy
```

## E) App health check fails after deploy

Symptoms:

- deploy command succeeds
- `/health` check fails

Check on EC2:

```bash
cd ~/apps/family_tree/current
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml exec app python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health').read().decode())"
```

If direct app health works but browser access fails:

- likely Caddy / HTTP / HTTPS / browser-cache issue, not app startup

## Quick recovery options

## Option 1: re-run the primary SSM deploy

Use if:

- ECR push succeeded
- SSM failed due to a transient shell/runtime issue you have now fixed

## Option 2: deploy previous ECR image manually on EC2

Use if:

- app is broken after a new deploy
- you know an older image tag was healthy

On EC2:

```bash
cd ~/apps/family_tree/current
bash ~/deploy-image.sh <old-sha> 13.238.11.159 869694272453.dkr.ecr.ap-southeast-2.amazonaws.com/family-tree:<old-sha>
```

Then verify:

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml exec app python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health').read().decode())"
```

## Option 3: use SSH fallback workflow

Use only if:

- SSM path is broken
- you need to get a fix out urgently

Workflow:

- `.github/workflows/deploy-aws-ec2.yml`

This requires temporarily loosening SSH inbound for GitHub again.

## Manual EC2 checks

Useful commands:

```bash
cd ~/apps/family_tree/current
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=100 app
docker compose -f docker-compose.prod.yml logs --tail=100 caddy
aws --version
curl -s http://169.254.169.254/latest/meta-data/iam/security-credentials/
```

If ECR pull is suspicious:

```bash
aws ecr get-login-password --region ap-southeast-2 | docker login --username AWS --password-stdin 869694272453.dkr.ecr.ap-southeast-2.amazonaws.com
docker pull 869694272453.dkr.ecr.ap-southeast-2.amazonaws.com/family-tree:latest
```

## What to paste when asking for help

If a deploy fails, capture:

1. workflow name
2. failing step name
3. full error from that step
4. if present, `Show SSM command output`
5. on-EC2 outputs of:
   - `docker compose -f docker-compose.prod.yml ps`
   - `docker compose -f docker-compose.prod.yml logs --tail=100 app`

That is usually enough to isolate the broken layer quickly.
