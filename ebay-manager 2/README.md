# eBay Seller Manager (local app, runs on your Mac)

A local dashboard that:
- Pulls your **inventory from eBay** (read-only — never writes stock back)
- Imports your **orders**
- Calculates **profit per order** (sale price + postage charged, minus your item
  cost, real/estimated shipping cost, eBay fee, and your £0.54 age-verification fee)
- Detects **carrier from tracking number** and resolves a shipping cost
- Sends an **auto-reply to buyer messages** while you're marked "away"
- Lets you manage fallback shipping rates and fee assumptions

Everything runs locally on your machine (SQLite database file, no cloud
hosting). Nothing here can push inventory quantity/price changes to eBay —
that capability simply isn't implemented in this app.

---

## 1. Requirements

- macOS with Python 3.10+ (check with `python3 --version` in Terminal)
- An eBay Developer account (developer.ebay.com) — you already have this

## 2. Run it

```bash
cd ebay-manager
./run.sh
```

First run installs dependencies into a virtual environment automatically.
Then open **http://localhost:8000** in your browser. Keep the Terminal
window open — closing it stops the app.

Next time, just run `./run.sh` again (it's quick after the first install).

---

## 3. Creating your eBay App keys (Client ID / Secret)

1. Go to https://developer.ebay.com and sign in with your seller account.
2. Go to **My Account → Application Keys**.
3. If you don't have a "Keyset" yet, click **Create a keyset** — choose
   **Production** (Sandbox is for testing only, with fake data).
4. You'll get:
   - **App ID (Client ID)**
   - **Cert ID (Client Secret)**
5. You also need a **RuName** (this is eBay's stand-in for a redirect URL —
   eBay does not let you point their OAuth consent screen straight at
   `http://localhost:8000/...`). To create one:
   - Go to **User Tokens** (same Application Keys page) → **Get a Token from eBay
     via Your Application** → **Add eBay Redirect URL**.
   - Give it a display name, and for "Your auth accepted URL" /
     "Your auth declined URL" you can put any placeholder page (they're
     only shown if eBay ever redirects a browser there directly, which
     won't happen in this flow) — e.g. `https://example.com/accepted`.
   - Save it. eBay gives you a **RuName** string like
     `Your_Name-YourApp-YourApp-abcde12345`.

## 4. Enter your keys into the app

1. Open http://localhost:8000 → **Settings** tab.
2. Paste in:
   - **Client ID**
   - **Client Secret**
   - **Redirect URI** → paste the **RuName** from step 3.5 here (yes, the
     RuName goes in this field — that's what eBay's OAuth API expects as
     `redirect_uri`).
   - Choose **Production** (or Sandbox while testing).
3. Click **Save Keys**, then click **Connect to eBay**.
4. You'll be sent to eBay's real consent screen, log in and click
   **I Agree** to grant access to your inventory/orders/messages.
5. eBay redirects back into the app automatically and you're connected —
   the status badge top-right will turn green.

This one-time step gives the app a **refresh token**, stored locally in
your SQLite database (`ebay_manager.db` in the project folder). The app
uses that refresh token every time it needs a fresh short-lived access
token — you won't need to log in again unless the refresh token itself
expires (eBay's last ~18 months, and normal usage of the app keeps
renewing it).

**Keep `ebay_manager.db` and your `.env`/keys private** — they hold
credentials for your live eBay account.

---

## 5. Using it

- **Orders & Profit tab**: click **Import Orders from eBay** to pull your
  latest orders. Edit **Item Cost** inline for each order (eBay has no way
  of knowing what you paid for stock — you enter this once per order/SKU).
  Shipping cost is auto-filled from the fallback rate table if it can't
  pull a real label cost; edit it to the real figure any time and it's
  remembered as "actual" from then on.
- **Inventory tab**: click **Fetch Stock from eBay** to see live quantities.
  Read-only — there's no button anywhere in this app that changes stock on eBay.
- **Auto Messages tab**: toggle **Away mode** on before you go away, set
  your message, save. The app checks for new buyer messages every 5
  minutes and auto-replies once per buyer. You can also see eBay's own
  native version of this at **Seller Hub → Messages → Settings → Automatic
  Away Message** if you'd rather use eBay's built-in one instead of/alongside
  this.
- **Settings tab**: adjust your eBay fee % assumption (used only when eBay
  doesn't hand back an exact fee on an order), your fixed eBay fee, your
  age-verification fee (defaults to £0.54), and maintain fallback shipping
  rates per carrier/service for when a real label cost isn't available.

---

## 6. Important honesty note on shipping costs

A tracking number's format (e.g. `AB123456789GB` = Royal Mail, `1Z...` =
UPS) tells you the **carrier**, but it can never tell you **what you paid**
— no carrier encodes price into a tracking number. So the app:

1. Detects carrier from the tracking number pattern.
2. Looks for a real label cost if you connect a courier account or label
   provider export (not wired up by default — see `app/shipping.py` if you
   want to add e.g. a Royal Mail Click & Drop CSV import).
3. Otherwise falls back to the default rate you set per carrier/service in
   Settings, clearly flagged **"est."** in the Orders table so you always
   know which numbers are real vs. assumed.

## 7. What's not included (and why)

- **No stock/price push to eBay** — as requested, deliberately left out.
- **Payment/managed-payments fee breakdown** — eBay's Managed Payments fee
  is usually bundled into the same final value fee; the fee estimate
  covers both unless you tell me you want them split out.
- **Multi-account / team logins** — this is a single-seller local tool.

If you want any of the above, just ask.

---

## 8. Free cloud hosting (Render + Neon Postgres)

This lets you reach the app from your phone/anywhere, not just your Mac.
Both services below are free. Honest caveats first:

- **Render's free web service sleeps** after ~15 minutes with no traffic.
  The next request after that takes ~30-50 seconds to "wake up" - fine
  for personal use, just don't expect instant loads if you haven't
  opened it in a while.
- **Render's free disk is wiped on every restart/redeploy** - that's why
  step 2 below sets up a separate free Postgres database (Neon.tech,
  which does not expire or wipe) to actually hold your data. The app
  already supports this automatically via the `DATABASE_URL` variable.

### Step 1: Create the free database (Neon)
1. Go to https://neon.tech, sign up free, create a project.
2. Copy the connection string shown (starts with `postgresql://...`).
   Keep this tab open, you'll paste it into Render next.

### Step 2: Put the code on GitHub
Render deploys from a GitHub repo. From inside the `ebay-manager` folder:
```
git init
git add .
git commit -m "initial commit"
```
Then create a new empty repository on https://github.com/new, and push:
```
git remote add origin https://github.com/YOUR_USERNAME/ebay-manager.git
git branch -M main
git push -u origin main
```
Your `.env`, database file, and virtual environment are excluded
automatically via `.gitignore` - your eBay keys never get pushed to
GitHub, they live only in the app's database / Render's env vars.

### Step 3: Deploy on Render
1. Go to https://render.com, sign up free, click New, Web Service.
2. Connect your GitHub account and pick the ebay-manager repo.
3. Render should detect render.yaml automatically. If not, set manually:
   Build Command `pip install -r requirements.txt`, Start Command
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Choose the Free plan.
4. Under Environment, add a variable: `DATABASE_URL` = the Neon
   connection string from Step 1.
5. Click Deploy. After a couple of minutes you get a public URL like
   `https://ebay-seller-manager.onrender.com`.

### Step 4: Point eBay at your new public URL
Your RuName (from README section 3) has an "Auth accepted URL" setting in
the eBay developer portal - edit it to your real Render URL:
```
https://ebay-seller-manager.onrender.com/auth/callback
```
The RuName string itself is still what you paste into this app's
Settings, Redirect URI field (not the URL) - same as the local setup,
eBay uses the RuName internally to know where to send the browser.

### Step 5: Use it
Open your Render URL in any browser, on any device, and go through
Settings, Save Keys, Connect to eBay exactly as before. From now on all
your orders/inventory/settings live in the free Neon database, so they
survive Render restarts.

If you ever want to switch back to running it locally on your Mac,
nothing changes - just don't set DATABASE_URL and it uses the local
SQLite file again automatically.
