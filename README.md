# @billimindst → Substack Notes Bot

Automatically cross-posts every new @billimindst tweet to Substack Notes.
Runs 24/7 on Railway for ~$5/month. Zero ongoing maintenance.

---

## How It Works

1. Every 10 minutes, the bot checks the @billimindst RSS feed
2. Detects any new original posts (ignores retweets and replies)
3. Posts the tweet text directly to your Substack Notes
4. Logs the post ID so it's never double-posted

---

## Deploy to Railway (one-time setup ~15 minutes)

### Step 1 — Put this code on GitHub

1. Go to github.com → sign in (or create free account)
2. Click **New repository** → name it `billimindst-bot` → set to **Private** → Create
3. On your computer, open Terminal and run:

```bash
cd ~/Desktop
git clone https://github.com/YOUR_USERNAME/billimindst-bot
# Copy all files from this folder into the cloned repo folder
git add .
git commit -m "Initial bot setup"
git push
```

Or use GitHub Desktop app if you prefer no command line.

### Step 2 — Create Railway account

1. Go to **railway.app** → Sign up with GitHub
2. Click **New Project** → **Deploy from GitHub repo**
3. Select `billimindst-bot`
4. Railway will detect the Python project automatically

### Step 3 — Add Environment Variables

In Railway → your project → **Variables** tab, add these:

| Variable | Value |
|----------|-------|
| `X_USERNAME` | `billimindst` |
| `SUBSTACK_SID` | *(your connect.sid value — see below)* |
| `SUBSTACK_HANDLE` | `billionairemindset` |
| `POLL_INTERVAL_SEC` | `600` |

### Step 4 — Deploy

Railway auto-deploys when you push to GitHub. Click **Deploy** if it hasn't started.

Check the **Logs** tab — you should see:
```
✅ Substack auth OK — logged in as: Billionaire Mindset
First run — seeded X existing tweet IDs. Will post NEW tweets only from now on.
```

That's it. The bot is live.

---

## Getting Your Substack SID Cookie

The bot needs this to post as you. Here's how to get it:

1. Open **Chrome** on your computer (not phone)
2. Go to **substack.com** — make sure you're logged in
3. Press **F12** to open Developer Tools
4. Click the **Application** tab
5. In the left sidebar: **Storage → Cookies → https://substack.com**
6. Find the row named **`connect.sid`**
7. Copy the entire **Value** column

⚠️ **This cookie expires periodically** (usually every few weeks to months).
When the bot logs `Substack auth failed`, just re-extract the cookie and
update the Railway environment variable. The bot will restart automatically.

---

## Monitoring

- **Railway Logs tab** — shows every post attempt in real time
- Green `✅` = successfully posted to Substack
- Red `❌` = check the error message (usually expired cookie)

---

## Updating the Bot

Any time you want to change how the bot works, edit `bot.py` and push to GitHub.
Railway redeploys automatically within 60 seconds.

To change check frequency: update `POLL_INTERVAL_SEC` in Railway Variables.
`600` = 10 min, `300` = 5 min, `1800` = 30 min.

---

## Adding Instagram Later

When ready to add Instagram cross-posting:
- Sign up for Later.com (has an API)
- Add `LATER_API_KEY` to Railway Variables
- Claude Code can add the Instagram posting function to `bot.py`

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Substack auth failed` | Re-extract `connect.sid` from browser, update Railway variable |
| `All RSS mirrors failed` | X RSS is temporarily down — wait 30 min, it auto-retries |
| Posts not appearing on Substack | Check Railway logs for error details |
| Old tweets being posted | This shouldn't happen — bot seeds existing IDs on first run |

---

*Built for @billimindst. Maintained with Claude Code.*
