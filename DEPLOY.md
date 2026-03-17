# Drill News Scanner — Deployment Guide

A mobile-friendly web app that scans Investegate daily for drilling-related 
RNS announcements from resource sector companies, summarised by Claude.

## What you'll need

- A **GitHub account** (free) — https://github.com
- A **Render account** (free) — https://render.com
- Your **Anthropic API key** (the same one you use for rns-summary)

## Step 1 — Create a GitHub repository

1. Go to https://github.com/new
2. Name it `drill-news` (or whatever you like)
3. Set it to **Private**
4. Click **Create repository**
5. On the next screen, click **"uploading an existing file"**
6. Drag and drop ALL the files from this folder:
   - `app.py`
   - `requirements.txt`
   - `render.yaml`
   - `templates/index.html`
7. Click **Commit changes**

> **Important**: Make sure the `templates` folder structure is preserved. 
> GitHub should show `templates/index.html` as a subfolder.

## Step 2 — Deploy on Render

1. Go to https://render.com and sign up (use "Sign in with GitHub")
2. Click **New** → **Web Service**
3. Connect your GitHub account if prompted
4. Find and select your `drill-news` repository
5. Render should auto-detect the settings from `render.yaml`. Verify:
   - **Name**: drill-news
   - **Runtime**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
6. Scroll down to **Environment Variables** and add:
   - Key: `ANTHROPIC_API_KEY`  Value: *(paste your API key)*
   - Key: `ANTHROPIC_MODEL`    Value: `claude-sonnet-4-20250514`
7. Select the **Free** plan
8. Click **Create Web Service**

Render will build and deploy. This takes 2-3 minutes the first time.

## Step 3 — Access on your phone

Once deployed, Render gives you a URL like:
`https://drill-news-xxxx.onrender.com`

1. Open that URL in Safari on your iPhone
2. Tap the **Share** button (square with arrow)
3. Tap **Add to Home Screen**
4. Name it "Drill News" and tap **Add**

You now have an app icon on your home screen.

## How it works

- **First visit each day**: The app scrapes Investegate, filters for 
  drilling-related announcements, and calls Claude for summaries. 
  This takes 30-60 seconds.
- **Subsequent visits same day**: Returns cached results instantly.
- **Refresh button**: Forces a fresh scan (useful if you visit early 
  morning before all RNS are published).

## Notes

- **Free tier cold starts**: Render's free tier spins down after 15 
  minutes of inactivity. The first load after that takes ~30 seconds 
  to wake up, plus the scan time. Subsequent loads are fast.
- **API costs**: Each scan uses one Claude API call. At ~$0.01-0.05 
  per call on Sonnet, daily use costs pennies.
- **To update**: Push changes to GitHub and Render auto-redeploys.

## Upgrading (optional)

If the cold start delay bothers you, Render's paid tier ($7/month) 
keeps the service always-on. But try the free tier first — it works 
fine, just has that initial wake-up delay.
