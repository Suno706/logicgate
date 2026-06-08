# LogicGate → Fly.io (one-time setup, then auto-deploys forever)

After these ~10 minutes, your site is live at `https://logicgate-XYZ.fly.dev`,
always-on, with persistent data — and every `git push` here updates the live
site automatically (~90 seconds).

## Step 1 — Install flyctl (one minute)

Open **PowerShell** and paste:

```powershell
iwr https://fly.io/install.ps1 -useb | iex
```

After it finishes, **close PowerShell and open a new one** so `flyctl` is in your PATH.

## Step 2 — Sign up to Fly.io (two minutes)

```powershell
fly auth signup
```

This opens a browser. Sign up (email + credit card for verification — **$0 charged on free tier**).

## Step 3 — Initialize the app (one minute)

From the project directory:

```powershell
cd D:\p\logicgate
fly launch --no-deploy --copy-config
```

When prompted:
- **App name**: pick something unique like `logicgate-sunny` (lowercase, dashes okay). This becomes your URL: `https://logicgate-sunny.fly.dev`
- **Region**: just press Enter to accept the default closest to you
- **Postgres database?**: → **No** (we use SQLite)
- **Redis?**: → **No**

This updates `fly.toml` with your chosen name. Commit it: `git add fly.toml && git commit -m "fly app name" && git push`.

## Step 4 — Create the persistent volume (saves SQLite forever)

```powershell
fly volumes create logicgate_data --size 1 --region iad --yes
```

Replace `iad` with whatever region `fly launch` chose if different.

## Step 5 — Set the session secret

```powershell
fly secrets set FLASK_SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
```

## Step 6 — First deploy

```powershell
fly deploy
```

Takes ~3-5 minutes the first time (Docker build). When it finishes:

```
✓ Machine d8e6b9c2 is ready
You can now visit your app at: https://logicgate-sunny.fly.dev
```

**Open that URL in your phone, your laptop, send it to your friends — your real public website.**

## Step 7 — Set up auto-deploy on `git push`

```powershell
fly tokens create deploy --expiry 0
```

This prints a long token starting with `FlyV1 fm2_...`. **Copy it.**

Now go to https://github.com/Suno706/logicgate/settings/secrets/actions

Click **New repository secret**:
- **Name**: `FLY_API_TOKEN`
- **Value**: paste the token

Click **Add secret**.

**You're done.** From now on, every time you run:

```bash
git add .
git commit -m "some change"
git push
```

GitHub Actions runs `.github/workflows/deploy.yml`, which calls `flyctl deploy --remote-only` with your token. The live site updates in ~90 seconds. Watch the progress at https://github.com/Suno706/logicgate/actions.

## Verify it works

After step 7, try:

```bash
echo "auto-deploy test" >> README.md
git add README.md
git commit -m "test auto-deploy"
git push
```

Then open https://github.com/Suno706/logicgate/actions — you'll see a green check ~90 seconds later. Your live site is updated.

## Recap of what you can tell a recruiter

> *"It's a digital circuit designer with a scikit-learn ML backend — fault
> detection, gate minimization, an intent classifier for natural language
> ("build a 4-bit adder") trained on 200K rows. Real-time multiplayer over
> WebSocket, real accounts in SQLite, deployed on Fly.io with automatic
> deployment from GitHub. Live at logicgate-sunny.fly.dev."*

All true. All working. One URL.

## If something breaks

- `fly logs` — tail the live logs
- `fly status` — check the deployment status
- `fly ssh console` — SSH into the running container
- `fly volumes list` — confirm the volume is attached

Or tell me what you see and I'll diagnose.
