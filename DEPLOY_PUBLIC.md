# Make LogicGate work on OTHER devices

Right now Flask runs at `http://localhost:5000` — only YOUR computer can see
that. To let your phone, your friend's laptop, or anyone else on the internet
use it, the app needs to live on a **public URL**.

You have three good options. Pick one — total time 5–15 minutes.

---

## Option 1: Render.com (easiest, free, recommended)

**You get a URL like `https://logicgate-xyz.onrender.com` that anyone can visit.**

### Steps (5 minutes)

1. **Push your code to GitHub**
   ```bash
   git init -b main          # if not already a git repo
   git add .
   git commit -m "Initial commit"
   gh repo create logicgate --public --source=. --push
   # or: create a repo on github.com and `git push -u origin main`
   ```

2. **Sign in to Render**
   Go to https://render.com and click "Get Started" → sign in with GitHub.

3. **Create the service**
   Click **New → Blueprint** → select your `logicgate` repo.
   Render reads `render.yaml` (already in the repo) and provisions everything.

4. **Wait ~3 minutes for the first build** (subsequent deploys take ~30 seconds).

5. **Done.** Your URL is shown at the top of the Render dashboard.

**Free tier caveats:**
- Sleeps after 15 minutes of inactivity; next request takes ~30 s to wake up.
- Persistent disk is 1 GB (plenty for SQLite + retrained models).
- Upgrade to Starter ($7/mo) for always-on, no code changes needed.

---

## Option 2: Fly.io (free, always-on, faster worldwide)

**Same idea but no cold starts.**

```bash
# 1. Install flyctl
curl -L https://fly.io/install.sh | sh         # macOS/Linux
# Windows: iwr https://fly.io/install.ps1 -useb | iex

# 2. Sign up + auth (free, requires credit card but $0 charged on free tier)
fly auth signup

# 3. From the project directory:
fly launch --no-deploy       # picks a unique app name; reads fly.toml
fly secrets set FLASK_SECRET_KEY=$(openssl rand -hex 32)
fly deploy
```

Your URL: `https://<your-app-name>.fly.dev`. Live in ~2 minutes.

---

## Option 3: Railway (also free, GitHub-driven)

1. Push to GitHub
2. https://railway.app → Sign in with GitHub → "Deploy from GitHub repo"
3. Pick the repo, Railway auto-detects the Dockerfile
4. Add an environment variable `FLASK_SECRET_KEY` with a random hex string
5. Click "Generate Domain" → that's your public URL

Free $5/month credit — covers this app forever for personal use.

---

## After you deploy

### Test from any device

1. Open the public URL on your **phone's browser**
2. Sign up → make a circuit → save it
3. Open the SAME URL on your laptop / friend's PC → log in with the same username
4. Your circuit is there.

### Share a collaboration room

1. On any device, click the **Users icon** in the toolbar → **"✨ Create new room"**
2. URL becomes `https://your-site.com/?room=A7F2KQ`
3. Send that URL to anyone
4. They open it → they're instantly in the same room
5. Gates you add appear on their screen in real-time (WebSocket)

### Enable "Sign in with Google" (optional)

1. Create OAuth credentials at https://console.cloud.google.com/apis/credentials
   - Application type: **Web application**
   - Authorized redirect URI: `https://your-site.com/api/auth/google/callback`
2. On Render: dashboard → your service → Environment → add
   `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`
3. Trigger a redeploy. The Google button appears on the sign-in page.

---

## Common deployment problems

### "Application failed to start"
- Check the build logs. Most common cause: a missing env var. `FLASK_SECRET_KEY`
  is required for production sessions.

### "Cookies don't persist after sign-in"
- This is a SameSite / Secure cookie issue. The code already sets
  `SESSION_COOKIE_SECURE` based on `FLASK_ENV`. Make sure your deployment
  sets `FLASK_ENV=production` (Render does it via render.yaml; Fly via fly.toml).

### "WebSocket connection failed"
- Production needs eventlet-based gunicorn. The Dockerfile already does this.
  If using a different start command, make sure it's `gunicorn -k eventlet -w 1`.

### "Saved circuits disappear after redeploy"
- Make sure the platform has a persistent volume mounted at `/app/data`.
  The `render.yaml` and `fly.toml` in this repo do this.

---

## My recommendation

**For now: Render.** Free, single button, no credit card. Cold start is the only
annoyance — when you're not using it for 15 minutes, the next visitor waits
30 seconds. For sharing a portfolio link or class demo, that's fine.

**When you're ready for a "real" site: Fly.io.** Always-on, $0 within free tier,
URL like `logicgate.fly.dev`. The deploy is one command after the initial
`fly launch`.

Once your URL is live, **share it on GitHub, LinkedIn, your portfolio** — it
becomes a real website anyone in the world can use.
