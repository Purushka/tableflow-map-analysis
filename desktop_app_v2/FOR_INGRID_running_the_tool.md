# RGSSA Catalog Tool — Quick Start

Hi Ingrid — here's how to get the tool running. It takes about two minutes.

---

## Why your computer warns you

The app is brand-new and **not yet code-signed**, so McAfee and Windows
SmartScreen don't recognise it yet and may block it the first time. This is a
false alarm, not a virus.

> **A proper code-signing certificate is being set up now. It takes about one
> week to be approved.** Once it's done, you'll get a signed version and these
> warnings will disappear. Until then, please use the two one-time steps below.

---

## Step 1 — Let McAfee trust the app (one time)

1. Open **McAfee**.
2. Go to **My Protection → Real-Time Scanning** (or **Settings → Excluded Files**).
3. Click **Add file** / **Exclude a file**.
4. Select **`RGSSA Catalog Tool.exe`** (wherever you saved it).
5. Save. McAfee will now leave it alone.

*If McAfee already quarantined it:* open McAfee → **Quarantined items**, select
the app, and choose **Restore**, then do the exclusion above.

---

## Step 2 — Get past the blue SmartScreen box (one time)

When you double-click the app, Windows may show a blue box:
**"Windows protected your PC"**.

1. Click the small **More info** link.
2. A **Run anyway** button appears at the bottom — click it.

That's it. Windows remembers your choice, so it won't ask again.

---

## Step 3 — Use the tool

1. **First run:** paste in the **API key** and **Workspace ID** I gave you,
   then click **Save**.
2. **Region:** choose the node closest to you (leave the default if unsure).
3. **Folders:** pick the folder with your map scans (Input), and where the
   results should go (Output).
4. Click **Start processing**.
5. When it finishes, the **Review** screen shows any items the AI wasn't sure
   about — confirm, correct, or remove each one.
6. Export when done. You'll get an Excel file with three tabs (Review Queue,
   Full Catalog, AI Reasoning).

You can close and reopen the app any time — it remembers your progress and you
can continue the review later.

---

## Good to know

- Your original map files (the big 400 MB TIFs) **never leave your computer** —
  only a small resized copy is sent for analysis.
- Nothing needs to be installed. The app is a single file you just double-click.
- If anything looks stuck, the on-screen log shows exactly what it's doing.

Any problems, just send me a screenshot of the log. — Thanks!
