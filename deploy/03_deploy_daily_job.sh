#!/usr/bin/env bash
# Deploy the daily ingestion job (Cloud Run Job) and schedule it (Cloud Scheduler).
set -euo pipefail
cd "$(dirname "$0")"
source ./config.sh

JOB=filings-daily
INGEST_SA="filings-ingest@$PROJECT_ID.iam.gserviceaccount.com"
SCHEDULER_SA="filings-scheduler@$PROJECT_ID.iam.gserviceaccount.com"

ENV_FILE=$(mktemp)
trap 'rm -f "$ENV_FILE"' EXIT
cat > "$ENV_FILE" <<EOF
SEC_USER_AGENT: "$SEC_USER_AGENT"
GCP_PROJECT_ID: "$PROJECT_ID"
GCS_BUCKET: "$BUCKET"
GCP_LOCATION: "$SEARCH_LOCATION"
VERTEX_SEARCH_DATA_STORE_ID: "$DATA_STORE_ID"
VERTEX_SEARCH_ENGINE_ID: "$ENGINE_ID"
FORM_TYPES: "10-K,10-Q,8-K"
DAILY_LOOKBACK_DAYS: "14"
EOF

echo "== Deploying Cloud Run Job $JOB"
gcloud run jobs deploy "$JOB" \
  --project="$PROJECT_ID" --region="$REGION" \
  --source=../ingestion \
  --service-account="$INGEST_SA" \
  --env-vars-file="$ENV_FILE" \
  --memory=1Gi --cpu=1 --task-timeout=3600 --max-retries=1

echo "== Allowing the scheduler to start the job"
gcloud run jobs add-iam-policy-binding "$JOB" --project="$PROJECT_ID" --region="$REGION" \
  --member="serviceAccount:$SCHEDULER_SA" --role=roles/run.invoker >/dev/null

echo "== Scheduling it: '$DAILY_SCHEDULE' (America/New_York)"
RUN_URI="https://run.googleapis.com/v2/projects/$PROJECT_ID/locations/$REGION/jobs/$JOB:run"
if gcloud scheduler jobs describe "$JOB-trigger" --project="$PROJECT_ID" --location="$REGION" >/dev/null 2>&1; then
  verb=update
else
  verb=create
fi
gcloud scheduler jobs "$verb" http "$JOB-trigger" \
  --project="$PROJECT_ID" --location="$REGION" \
  --schedule="$DAILY_SCHEDULE" --time-zone="America/New_York" \
  --uri="$RUN_URI" --http-method=POST \
  --oauth-service-account-email="$SCHEDULER_SA"

echo
echo "Done. Run it once now to check:"
echo "  gcloud run jobs execute $JOB --region=$REGION --wait"
echo "Logs: Cloud Console > Cloud Run > Jobs > $JOB > Logs"
