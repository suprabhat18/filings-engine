#!/usr/bin/env bash
# Build and deploy the FastAPI backend to Cloud Run. Re-run to ship updates.
set -euo pipefail
cd "$(dirname "$0")"
source ./config.sh

ENV_FILE=$(mktemp)
trap 'rm -f "$ENV_FILE"' EXIT
cat > "$ENV_FILE" <<EOF
GCP_PROJECT_ID: "$PROJECT_ID"
GCP_LOCATION: "$SEARCH_LOCATION"
VERTEX_SEARCH_ENGINE_ID: "$ENGINE_ID"
GEMINI_MODEL: "$GEMINI_MODEL"
GEMINI_LOCATION: "$GEMINI_LOCATION"
GOOGLE_OAUTH_CLIENT_ID: "$GOOGLE_OAUTH_CLIENT_ID"
ALLOWED_EMAILS: "$ALLOWED_EMAILS"
CORS_ORIGINS: "$FRONTEND_URL"
EOF

# --allow-unauthenticated: Cloud Run lets requests through, and the app itself
# checks every request's Google sign-in token. Few max instances keep the
# per-minute rate limit meaningful and costs bounded.
gcloud run deploy filings-api \
  --project="$PROJECT_ID" --region="$REGION" \
  --source=../backend \
  --service-account="filings-api@$PROJECT_ID.iam.gserviceaccount.com" \
  --env-vars-file="$ENV_FILE" \
  --allow-unauthenticated \
  --memory=1Gi --cpu=1 --min-instances=0 --max-instances=2 --timeout=120

URL=$(gcloud run services describe filings-api --project="$PROJECT_ID" --region="$REGION" --format='value(status.url)')
echo
echo "Backend URL: $URL"
echo "Health check: $(curl -s "$URL/health")"
echo "Set BACKEND_URL=$URL in Vercel (frontend) and redeploy it."
