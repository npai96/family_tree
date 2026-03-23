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
   - SSH (22) from your IP
   - HTTP (80) from `0.0.0.0/0`
   - HTTPS (443) from `0.0.0.0/0`
7. Launch

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

## Common issues

## 1) GitHub deploy fails with SSH error
- verify `AWS_EC2_HOST`, `AWS_EC2_USER`, `AWS_EC2_SSH_KEY`
- ensure instance security group allows SSH from GitHub Actions IP ranges (or temporarily open for testing)

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

