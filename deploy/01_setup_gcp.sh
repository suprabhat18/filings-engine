#!/usr/bin/env bash
# One-time GCP setup: APIs, Firestore, bucket, service accounts, permissions, budget.
# Safe to re-run: existing resources are left as they are.
set -euo pipefail
cd "$(dirname "$0")"
source ./config.sh

say() { printf '\n== %s\n' "$*"; }

gcloud config set project "$PROJECT_ID" >/dev/null
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')

say "Enabling APIs (takes a minute or two)"
gcloud services enable \
  discoveryengine.googleapis.com aiplatform.googleapis.com firestore.googleapis.com \
  storage.googleapis.com run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com iam.googleapis.com

say "Firestore database"
if gcloud firestore databases describe --database="(default)" >/dev/null 2>&1; then
  echo "already exists"
else
  gcloud firestore databases create --location="$FIRESTORE_LOCATION" --type=firestore-native
fi

say "Firestore index for the watchlist feed (ticker + newest filing date)"
gcloud firestore indexes composite create --collection-group=filings \
  --field-config=field-path=ticker,order=ascending \
  --field-config=field-path=filing_date,order=descending --async 2>/dev/null \
  || echo "already exists"

say "Cloud Storage bucket gs://$BUCKET"
if gcloud storage buckets describe "gs://$BUCKET" >/dev/null 2>&1; then
  echo "already exists"
else
  gcloud storage buckets create "gs://$BUCKET" --location="$REGION" --uniform-bucket-level-access
fi

say "Service accounts"
for sa in filings-api filings-ingest; do
  if gcloud iam service-accounts describe "$sa@$PROJECT_ID.iam.gserviceaccount.com" >/dev/null 2>&1; then
    echo "$sa already exists"
  else
    gcloud iam service-accounts create "$sa" --display-name="Filings engine: $sa"
  fi
done
API_SA="filings-api@$PROJECT_ID.iam.gserviceaccount.com"
INGEST_SA="filings-ingest@$PROJECT_ID.iam.gserviceaccount.com"

retry() {  # new service accounts take a little while to become visible to IAM
  for i in 1 2 3 4 5 6; do
    "$@" >/dev/null 2>&1 && return 0
    echo "  (not ready yet, retrying in 10s)"; sleep 10
  done
  "$@" >/dev/null  # last try shows the real error
}

grant() {  # grant <member> <role>
  retry gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="$1" --role="$2" \
    --condition=None --quiet
  echo "  $2 -> $1"
}

say "Permissions (each service gets only what it needs)"
# Cloud Build runs source deploys as the default compute account, which new projects
# create without permissions; Cloud Run Builder lets it read sources and push images.
grant "serviceAccount:$PROJECT_NUMBER-compute@developer.gserviceaccount.com" roles/run.builder
# Backend: search the index, call Gemini, read/write user data
grant "serviceAccount:$API_SA" roles/discoveryengine.viewer
grant "serviceAccount:$API_SA" roles/aiplatform.user
grant "serviceAccount:$API_SA" roles/datastore.user
# Daily job: import into the index, write the catalog, upload to the bucket
grant "serviceAccount:$INGEST_SA" roles/discoveryengine.editor
grant "serviceAccount:$INGEST_SA" roles/datastore.user
retry gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member="serviceAccount:$INGEST_SA" --role=roles/storage.objectAdmin
echo "  roles/storage.objectAdmin on gs://$BUCKET -> $INGEST_SA"

# Vertex AI Search's own service agent reads the documents from the bucket during import.
# It can already read buckets in its own project; this grant is a belt-and-braces extra
# and is skipped if Google hasn't created the agent yet (it appears after first use).
if gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member="serviceAccount:service-$PROJECT_NUMBER@gcp-sa-discoveryengine.iam.gserviceaccount.com" \
  --role=roles/storage.objectViewer >/dev/null 2>&1; then
  echo "  roles/storage.objectViewer on gs://$BUCKET -> Vertex AI Search service agent"
else
  echo "  (Vertex AI Search service agent not created yet; same-project access works without it)"
fi

if [[ -n "${BILLING_ACCOUNT}" ]]; then
  say "Budget alert at \$$BUDGET_USD (emails at 50%, 90%, 100%)"
  gcloud services enable billingbudgets.googleapis.com
  gcloud billing budgets create --billing-account="$BILLING_ACCOUNT" \
    --display-name="filings-engine" --budget-amount="${BUDGET_USD}USD" \
    --filter-projects="projects/$PROJECT_ID" \
    --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0 \
    || echo "  (skipped: create it in Billing > Budgets & alerts instead)"
fi

say "Done. Next: create the search index (see docs/SETUP.md, step 4)."
