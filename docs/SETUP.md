# Setup guide

Everything you need to do, in order. Total hands-on time is about 1½–2 hours, plus
waiting for downloads and indexing. Commands are run from the project folder
(`filings-engine/`) unless a step says otherwise.

---

## 0. Tools (one time, ~15 min)

Install on your computer:

- **Google Cloud CLI** (`gcloud`): https://cloud.google.com/sdk/docs/install
- **Python 3.11+** and **Node.js 20+**
- A **GitHub** account (to host the code) and a **Vercel** account (free, sign in with GitHub)

Then sign in to Google Cloud twice: once for the command line, once for scripts.

```bash
gcloud auth login
gcloud auth application-default login
```

## 1. Pick the GCP project (~5 min)

In the Cloud Console, use the project that has your $300 credit, or create one and link
the billing account that holds the credit. Note the **project ID** (not the name).

## 2. Fill in the deploy settings and run the GCP setup (~10 min)

```bash
cp deploy/config.example.sh deploy/config.sh
```

Edit `deploy/config.sh`: set `PROJECT_ID` and `SEC_USER_AGENT` (your name and email).
Leave `GOOGLE_OAUTH_CLIENT_ID` and `FRONTEND_URL` for now. To get a budget alert email,
set `BILLING_ACCOUNT` (find it with `gcloud billing accounts list`).

```bash
bash deploy/01_setup_gcp.sh
```

This turns on the APIs, creates Firestore, the storage bucket, the service accounts and
their permissions. It's safe to run again if anything fails halfway.

## 3. Download the filings (~30–60 min, mostly waiting)

Skip this if you already ran it from the step 2 instructions.

```bash
cd ingestion
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `ingestion/.env`: set `SEC_USER_AGENT`, `GCP_PROJECT_ID`, and
`GCS_BUCKET` (your project ID followed by `-filings`).

```bash
python -m pytest                     # should end with "18 passed"
python -m edgar.run                  # prints filing counts at the end
```

**Write down the totals it prints.** That's the real number for your resume bullet.

## 4. Build the search index (~5 min of work, 20–60 min waiting)

Still in `ingestion/` with the virtual environment active:

```bash
python -m edgar.search_index setup   # creates the Vertex AI Search data store and app
python -m edgar.publish              # uploads filings and imports them; waits until done
python -m edgar.search_index test "supply chain risk"
```

The last command should print five filing excerpts. If it prints nothing right after the
import, wait 5–10 minutes and try again.

## 5. Create the Google sign-in credentials (~10 min, in the Cloud Console)

1. **APIs & Services → OAuth consent screen** (may be called "Google Auth Platform").
   - User type: **External**. App name: *Filings Research*. Add your email as support and
     developer contact. Keep the default scopes (email, profile, openid).
   - Under **Audience / Publishing status**, click **Publish app**. With only these basic
     scopes no Google review is needed, anyone can sign in, and sign-ins don't expire
     after 7 days the way they do in "Testing" mode.
2. **APIs & Services → Credentials → Create credentials → OAuth client ID**
   - Type: **Web application**
   - Authorized JavaScript origins: `http://localhost:3000`
   - Authorized redirect URIs: `http://localhost:3000/api/auth/callback/google`
   - Create, then copy the **Client ID** and **Client secret**.

Put the Client ID in `deploy/config.sh` as `GOOGLE_OAUTH_CLIENT_ID`. Keep the secret for
step 7; it never goes in the backend.

## 6. Deploy the backend (~5–10 min)

```bash
bash deploy/02_deploy_backend.sh
```

It builds the container on Google's side and prints the **backend URL** and a health
check that should say `{"status":"ok"}`.

## 7. Deploy the frontend on Vercel (~15 min)

1. Push the project to a new GitHub repository.
2. In Vercel: **Add New → Project →** import the repository. Set **Root Directory** to
   `frontend`. The framework (Next.js) is detected automatically.
3. Add these **Environment Variables**:

   | Name | Value |
   |---|---|
   | `GOOGLE_CLIENT_ID` | the Client ID from step 5 |
   | `GOOGLE_CLIENT_SECRET` | the Client secret from step 5 |
   | `NEXTAUTH_SECRET` | a random string: run `openssl rand -base64 32` |
   | `NEXTAUTH_URL` | your Vercel URL, e.g. `https://filings-research.vercel.app` |
   | `BACKEND_URL` | the backend URL from step 6 |

4. Deploy. Then finish the wiring with your Vercel URL:
   - In the OAuth client (step 5), add the URL to **Authorized JavaScript origins** and
     `https://<your-vercel-url>/api/auth/callback/google` to **Authorized redirect URIs**.
   - Set `FRONTEND_URL` in `deploy/config.sh` and run `bash deploy/02_deploy_backend.sh` again.
   - If you set `NEXTAUTH_URL` before you knew the final URL, fix it in Vercel and redeploy.

Open the site, sign in, and try a search.

## 8. Turn on the daily updates (~10 min)

```bash
bash deploy/03_deploy_daily_job.sh
gcloud run jobs execute filings-daily --region=us-central1 --wait
```

The test run should finish with a line like `Done: 3 new filings ...`. From now on it
runs every morning at 6:17 ET. Each run is recorded in Firestore under `ingestion_runs`,
which is your evidence that the incremental pipeline really runs daily.

---

## Running everything locally (optional)

```bash
# Backend (terminal 1)
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && cp .env.example .env   # fill in project + OAuth client ID
uvicorn app.main:app --reload --port 8000

# Frontend (terminal 2)
cd frontend && npm install && cp .env.example .env.local  # fill in the values
npm run dev                                               # http://localhost:3000
```

The local backend uses your own Google login (from `gcloud auth application-default login`).

## Costs

At demo traffic this should cost a few dollars a month, well inside the $300 credit. The
main items are Vertex AI Search (index storage and per-query charges), Gemini 3.8 Flash
(two short calls per search) and Cloud Run (scales to zero when idle). Check the current
prices on Google's pricing pages for Vertex AI Search and Vertex AI before sharing the
link widely. The backend caps usage at 50 searches per user and 1,000 in total per day
(change `DAILY_USER_QUOTA` and `DAILY_GLOBAL_QUOTA`), and the budget alert from step 2
emails you before spending gets close to your limit.

To shut everything down: delete the Cloud Run service and job, the Scheduler job, the
Vertex AI Search app and data store, and the bucket, or simply delete the GCP project.

## If something goes wrong

| Symptom | Likely cause and fix |
|---|---|
| `edgar.run` prints 403 errors | `SEC_USER_AGENT` is missing or isn't a real name and email. |
| `search_index setup` says permission denied | Run `gcloud auth application-default login` again with the account that owns the project. |
| Import finishes with failures | Details are in `gs://<bucket>/import-errors/`. Re-run `python -m edgar.search_index import <manifest uri>`. |
| Search returns "temporarily unavailable" | Backend logs: Cloud Console → Cloud Run → filings-api → Logs. Often the Gemini model name or region; check `GEMINI_MODEL`. |
| Sign-in loops or "redirect_uri_mismatch" | The redirect URI in the OAuth client must exactly match `<site>/api/auth/callback/google`. |
| Watchlist feed errors with "requires an index" | The Firestore index from step 2 is still building; wait a few minutes. |
