# AWS Setup Running Guide (solo, low-cost)

> This is the live checklist for getting the app deployed on AWS with GitHub Actions.

## Scope

- AWS EC2 Free Tier path (Ubuntu)
- GitHub Actions CI/CD
- No custom domain required initially

---

## Step 0: Prereqs

- GitHub repo with this code
- AWS account
- SSH key pair for EC2 (PEM file downloaded locally)

---

## Step 1: Launch EC2 instance

In AWS Console:

1. Go to `EC2` -> `Launch instance`
2. Name: `family-tree-prod`
3. AMI: `Ubuntu Server 22.04 LTS`
4. Instance type: `t2.micro` (or `t3.micro` if eligible)
5. Key pair: create/select one and download PEM
6. Security group inbound rules:
   - SSH (22) from your IP for manual admin access
   - If GitHub Actions will deploy over SSH, port 22 must also be reachable from GitHub-hosted runners
   - HTTP (80) from `0.0.0.0/0`
   - HTTPS (443) from `0.0.0.0/0`
7. Launch

For the first deployment, the simplest path is to temporarily allow `SSH (22)` from `0.0.0.0/0`, confirm the workflow works, then tighten access later. If you leave port 22 open broadly, rely on SSH keys only, disable password auth, and keep the key secret.

---

## Step 2: Allocate Elastic IP (stable address)

1. `EC2` -> `Elastic IPs` -> `Allocate`
2. Select new Elastic IP -> `Actions` -> `Associate`
3. Resource type: `Instance`
4. Choose `family-tree-prod`

Now this IP is your stable host.

---

## Step 3: SSH to instance

From local terminal:

```bash
chmod 400 /path/to/your-key.pem
ssh -i /path/to/your-key.pem ubuntu@<ELASTIC_IP>
```

If connection fails, check:
- security group SSH rule
- PEM path/permissions
- correct user (`ubuntu` for Ubuntu AMI)

If local SSH works but GitHub Actions times out, the server is almost always reachable from your laptop but not from GitHub's runners. That points to one of:
- EC2 security group only allows your IP
- network ACL blocks inbound port `22`
- `AWS_EC2_HOST` points to the wrong host, private IP, or stale public IP

---

## Step 4: Bootstrap server

On your local machine (repo root), copy and run bootstrap script:

```bash
scp -i /path/to/your-key.pem deploy/ec2/bootstrap.sh ubuntu@<ELASTIC_IP>:~/
ssh -i /path/to/your-key.pem ubuntu@<ELASTIC_IP> 'bash ~/bootstrap.sh'
```

Re-login once after bootstrap so Docker group permissions apply:

```bash
ssh -i /path/to/your-key.pem ubuntu@<ELASTIC_IP>
docker --version
docker compose version
```

---

## Step 5: Add GitHub Actions secrets

In GitHub repo:

`Settings` -> `Secrets and variables` -> `Actions` -> `New repository secret`

Add:

1. `AWS_EC2_HOST`
   - value: `<ELASTIC_IP>` (or EC2 public DNS)

2. `AWS_EC2_USER`
   - value: `ubuntu`

3. `AWS_EC2_SSH_KEY`
   - value: full PEM private key contents, including:
     - `-----BEGIN ... PRIVATE KEY-----`
     - `-----END ... PRIVATE KEY-----`

4. `APP_DOMAIN`
   - if no domain yet: same as `<ELASTIC_IP>` (temporary)
   - later: set to real domain (example `app.example.com`)

---

## Step 6: Trigger first deployment

CD workflow file:
- `.github/workflows/deploy-aws-ec2.yml`

Trigger by:
- pushing to `main`, or
- `Actions` -> `Deploy to AWS EC2` -> `Run workflow`

---

## Step 7: Verify deployment

Check GitHub Action logs first.

Then on server:

```bash
ssh -i /path/to/your-key.pem ubuntu@<ELASTIC_IP>
cd ~/apps/family_tree/current
docker compose -f docker-compose.prod.yml ps
```

Health check:

```bash
curl -i http://<ELASTIC_IP>/health
```

You should get HTTP 200 with JSON health response.

---

## Step 8: Basic app smoke test

In browser:

- `http://<ELASTIC_IP>/`

Manually verify:

1. sign in
2. create/select circle
3. render graph
4. create one person
5. create one relationship

---

## Step 9: Rollback quick path

If a deploy breaks:

```bash
ssh -i /path/to/your-key.pem ubuntu@<ELASTIC_IP>
ls -1 ~/apps/family_tree/releases
ln -sfn ~/apps/family_tree/releases/<PREV_SHA> ~/apps/family_tree/current
cd ~/apps/family_tree/current
docker compose -f docker-compose.prod.yml up -d --build --remove-orphans
```

---

## Step 10: Upgrade from temporary mode to production mode

Current temporary mode:

- no custom domain
- no HTTPS cert
- SQLite + local media on one instance

Production upgrades:

1. buy/setup domain + DNS A record to Elastic IP
2. set `APP_DOMAIN` to real domain
3. enable HTTPS via Caddy domain config
4. migrate SQLite -> Postgres
5. migrate local media -> S3

---

## Step 11: Prepare ECR publishing (next increment)

This is the next infra step after the current manual SSH deploy is working.

Goal:

- GitHub builds the image once
- GitHub pushes the image to Amazon ECR
- EC2 later pulls that image instead of receiving image tar files over SSH

Repo assets now available:

- `.github/workflows/publish-ecr.yml`
- `deploy/ec2/deploy-image.sh`

### 11a. Create an ECR repository

In AWS Console:

1. Go to `ECR` -> `Create repository`
2. Name: `family-tree`
3. Visibility: `Private`
4. Create

### 11b. Create a GitHub Actions IAM role for OIDC

This is the cleanest path because it avoids long-lived AWS access keys in GitHub.

In AWS:

1. Go to `IAM` -> `Identity providers`
2. Add provider:
   - provider type: `OpenID Connect`
   - provider URL: `https://token.actions.githubusercontent.com`
   - audience: `sts.amazonaws.com`
3. Go to `IAM` -> `Roles` -> `Create role`
4. Trusted entity type: `Web identity`
5. Identity provider: GitHub OIDC provider above
6. Audience: `sts.amazonaws.com`
7. Attach permissions:
   - start with a policy that allows ECR push/pull for the `family-tree` repository
8. Save the role ARN

### 11c. Add GitHub repo config for ECR publish

In GitHub repo:

`Settings` -> `Secrets and variables` -> `Actions`

Add secret:

- `AWS_GITHUB_ACTIONS_ROLE_ARN`
  - value: the IAM role ARN from the previous step

Add repository variables:

- `AWS_REGION`
  - value: your AWS region, for example `ap-southeast-2`
- `ECR_REPOSITORY`
  - value: `family-tree`

### 11d. Run the ECR publish workflow

In GitHub:

`Actions` -> `Publish Image to ECR` -> `Run workflow`

Expected result:

- image pushed as:
  - `<account>.dkr.ecr.<region>.amazonaws.com/family-tree:<git-sha>`
  - `<account>.dkr.ecr.<region>.amazonaws.com/family-tree:latest`

### 11e. What this does not change yet

This step does **not** remove SSH deploy yet.

For now:

- current deploy workflow is still the working fallback
- ECR publishing is being added first as a safe intermediate step
- after ECR push works, next we wire EC2 image pull, then SSM, then remove GitHub SSH deploy

---

## Step 12: Prepare SSM-based deploys

This is the step that removes GitHub's deploy dependence on inbound SSH.

Goal:

- GitHub uses AWS OIDC
- GitHub tells AWS Systems Manager to run the deploy on the EC2 instance
- EC2 pulls the image from ECR and restarts compose
- SSH goes back to admin-only use

Repo assets now available:

- `.github/workflows/deploy-aws-ssm.yml`
- `deploy/ec2/deploy-image.sh`

### 12a. Ensure the EC2 instance role includes SSM + ECR pull

The EC2 instance role should have:

- `AmazonSSMManagedInstanceCore`
- `AmazonEC2ContainerRegistryReadOnly`

### 12b. Verify the instance is managed by Systems Manager

In AWS Console:

1. Go to `Systems Manager`
2. Go to `Fleet Manager` or `Managed nodes`
3. Confirm your EC2 instance appears there

If it does not appear:

- confirm the instance role is attached
- confirm the instance can reach AWS public endpoints
- wait a few minutes and refresh

### 12c. Add one more GitHub repository variable

In GitHub repo:

`Settings` -> `Secrets and variables` -> `Actions` -> `Variables`

Add:

- `AWS_EC2_INSTANCE_ID`
  - value: the EC2 instance ID, for example `i-0123456789abcdef0`

### 12d. Run the SSM deploy workflow

In GitHub:

`Actions` -> `Deploy to AWS EC2 via SSM` -> `Run workflow`

What it does:

- builds and pushes the image to ECR
- sends an SSM Run Command to the EC2 instance
- uploads `deploy-image.sh` to the instance through SSM itself
- runs the deploy script on the instance
- waits for command completion and prints stdout/stderr

### 12e. Exit criteria

This step is successful when:

- the workflow completes without SSH
- the EC2 instance restarts using the new ECR image
- `/health` remains OK
- you can tighten SSH back to your admin IP and leave it there

---

## Common issues

## 1) GitHub deploy fails with SSH error
- verify `AWS_EC2_HOST`, `AWS_EC2_USER`, `AWS_EC2_SSH_KEY`
- ensure the instance has a public IP or Elastic IP and `AWS_EC2_HOST` uses that public address or DNS
- ensure instance security group allows SSH from GitHub Actions IP ranges, or temporarily open `22` to `0.0.0.0/0` for testing
- if the workflow says it cannot reach `<host>:22`, this is a network reachability problem, not an SSH key problem

## 2) Container runs but app unreachable
- check security group inbound 80/443
- check compose status/logs:
  ```bash
  docker compose -f docker-compose.prod.yml logs --tail=200
  ```

## 3) Caddy TLS issues on IP
- expected if using IP instead of domain
- use HTTP temporarily; switch to real domain for proper HTTPS cert

---

## Related files

- `docs/DEPLOY_AWS_CHEAP.md`
- `docs/TEMP_WORKAROUNDS_AND_PROD_UPGRADE.md`
- `.github/workflows/ci.yml`
- `.github/workflows/deploy-aws-ec2.yml`
- `.github/workflows/publish-ecr.yml`
- `.github/workflows/deploy-aws-ssm.yml`
- `deploy/ec2/deploy-image.sh`
