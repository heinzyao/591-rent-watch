#!/usr/bin/env bash
# 部署到 Cloud Run 並設定每日排程。
# 前置作業（只需做一次）：
#   1. 建立 LINE Messaging API channel，取得 channel secret 與 access token
#   2. gcloud services enable run.googleapis.com cloudscheduler.googleapis.com \
#        secretmanager.googleapis.com storage.googleapis.com compute.googleapis.com
#   3. gcloud storage buckets create gs://$GCS_BUCKET --location=asia-east1
#   4. 建立三個 secret（見下方 SECRETS 說明）
set -euo pipefail

PROJECT="${PROJECT:?請設定 PROJECT}"
REGION="${REGION:-asia-east1}"
SERVICE="rent591-watch"
GCS_BUCKET="${GCS_BUCKET:?請設定 GCS_BUCKET}"

# SECRETS（先手動建立）：
#   printf '%s' "<channel secret>" | gcloud secrets create RENT591_LINE_CHANNEL_SECRET --data-file=-
#   printf '%s' "<access token>"   | gcloud secrets create RENT591_LINE_CHANNEL_ACCESS_TOKEN --data-file=-
#   openssl rand -hex 32 | tr -d '\n' | gcloud secrets create RENT591_CRON_KEY --data-file=-

# 先授權再部署：--set-secrets 的 secret 是在 instance 啟動時解析的，
# runtime SA 沒有 secretAccessor 的話 revision 根本起不來，
# 授權步驟若放在 deploy 之後就永遠執行不到。
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

gcloud storage buckets add-iam-policy-binding "gs://$GCS_BUCKET" \
  --member="serviceAccount:$SA" --role=roles/storage.objectUser --project "$PROJECT"
for SECRET in RENT591_LINE_CHANNEL_SECRET RENT591_LINE_CHANNEL_ACCESS_TOKEN RENT591_CRON_KEY; do
  gcloud secrets add-iam-policy-binding "$SECRET" --member="serviceAccount:$SA" \
    --role=roles/secretmanager.secretAccessor --project "$PROJECT"
done

gcloud run deploy "$SERVICE" \
  --source . \
  --project "$PROJECT" \
  --region "$REGION" \
  --allow-unauthenticated \
  --service-account "$SA" \
  --min-instances 0 \
  --memory 512Mi \
  --timeout 600 \
  --set-env-vars "GCS_BUCKET=$GCS_BUCKET,PAGES=3" \
  --set-secrets "LINE_CHANNEL_SECRET=RENT591_LINE_CHANNEL_SECRET:latest,\
LINE_CHANNEL_ACCESS_TOKEN=RENT591_LINE_CHANNEL_ACCESS_TOKEN:latest,\
CRON_KEY=RENT591_CRON_KEY:latest"

URL=$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)')
CRON_KEY=$(gcloud secrets versions access latest --secret=RENT591_CRON_KEY --project "$PROJECT")

gcloud scheduler jobs create http "${SERVICE}-daily" \
  --project "$PROJECT" \
  --location "$REGION" \
  --schedule "0 9,13,21 * * *" \
  --time-zone "Asia/Taipei" \
  --uri "$URL/cron" \
  --http-method POST \
  --headers "X-Cron-Key=$CRON_KEY" \
  --attempt-deadline 600s \
  --max-retry-attempts 0 \
  2>/dev/null || gcloud scheduler jobs update http "${SERVICE}-daily" \
  --project "$PROJECT" \
  --location "$REGION" \
  --schedule "0 9,13,21 * * *" \
  --time-zone "Asia/Taipei" \
  --uri "$URL/cron" \
  --http-method POST \
  --update-headers "X-Cron-Key=$CRON_KEY" \
  --attempt-deadline 600s \
  --max-retry-attempts 0

echo
echo "部署完成：$URL"
echo "請到 LINE Developers Console 把 Webhook URL 設為：$URL/webhook"
echo "並確認已開啟 Use webhook、關閉「自動回應訊息」。"
