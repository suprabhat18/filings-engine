# Copy to deploy/config.sh and fill in. deploy/config.sh is git-ignored.

PROJECT_ID="your-gcp-project-id"
REGION="us-central1"                 # Cloud Run, Scheduler and the bucket
FIRESTORE_LOCATION="nam5"            # multi-region US; set once, can't change later
BUCKET="${PROJECT_ID}-filings"

# Vertex AI Search (must match ingestion/.env)
SEARCH_LOCATION="global"
DATA_STORE_ID="sec-passages"
ENGINE_ID="sec-passages-search"

# Gemini
GEMINI_MODEL="gemini-3.8-flash"
GEMINI_LOCATION="global"   # Gemini 3.x is served from the global endpoint

# Google OAuth Web client ID (APIs & Services > Credentials)
GOOGLE_OAUTH_CLIENT_ID="xxxxxxxx.apps.googleusercontent.com"
# Optional: comma-separated emails allowed to sign in; empty = any Google account
ALLOWED_EMAILS=""

# Search limits. Each search costs roughly half a US cent (Vertex AI Search + Gemini),
# so 200 a day caps spending at about $1/day even if a post goes viral.
DAILY_USER_QUOTA="20"
DAILY_GLOBAL_QUOTA="200"

# Your deployed frontend URL (fill in after the first Vercel deploy)
FRONTEND_URL="https://your-app.vercel.app"

# Required by the SEC for the daily job: your name and email
SEC_USER_AGENT="Your Name your.email@example.com"

# Daily run time (America/New_York)
DAILY_SCHEDULE="17 6 * * *"

# Optional: billing account ID (gcloud billing accounts list) to create a budget alert
BILLING_ACCOUNT=""
BUDGET_USD="50"
