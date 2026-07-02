#!/usr/bin/env bash
set -euo pipefail

PROJECT="${PROJECT:-musial-medusa}"
DOMAIN="${DOMAIN:-assets.medusa.evan.engineer}"
BUCKET="${BUCKET:-musial-medusa-assets}"

BACKEND_BUCKET="${BACKEND_BUCKET:-medusa-assets-backend}"
URL_MAP="${URL_MAP:-medusa-assets-url-map}"
CERTIFICATE="${CERTIFICATE:-medusa-assets-cert-20260702b}"
TARGET_PROXY="${TARGET_PROXY:-medusa-assets-https-proxy}"
IPV4_ADDRESS="${IPV4_ADDRESS:-medusa-assets-ipv4}"
IPV6_ADDRESS="${IPV6_ADDRESS:-medusa-assets-ipv6}"
IPV4_RULE="${IPV4_RULE:-medusa-assets-https-ipv4}"
IPV6_RULE="${IPV6_RULE:-medusa-assets-https-ipv6}"

SIGNED_URL_KEY_NAME="${SIGNED_URL_KEY_NAME:-medusa-assets-$(date +%Y%m%d)}"
SIGNED_URL_KEY_FILE="${SIGNED_URL_KEY_FILE:-data/secrets/medusa-assets-cdn-key.b64}"

LE_CERTIFICATE_FILE="${LE_CERTIFICATE_FILE:-}"
LE_PRIVATE_KEY_FILE="${LE_PRIVATE_KEY_FILE:-}"

gcloud_project=(gcloud --project "$PROJECT")

resource_exists() {
  local collection="$1"
  local name="$2"
  "${gcloud_project[@]}" compute "$collection" describe "$name" --global >/dev/null 2>&1
}

address_exists() {
  local name="$1"
  "${gcloud_project[@]}" compute addresses describe "$name" --global >/dev/null 2>&1
}

if ! address_exists "$IPV4_ADDRESS"; then
  "${gcloud_project[@]}" compute addresses create "$IPV4_ADDRESS" \
    --global \
    --ip-version=IPV4 \
    --network-tier=PREMIUM
fi

if ! address_exists "$IPV6_ADDRESS"; then
  "${gcloud_project[@]}" compute addresses create "$IPV6_ADDRESS" \
    --global \
    --ip-version=IPV6 \
    --network-tier=PREMIUM
fi

if resource_exists backend-buckets "$BACKEND_BUCKET"; then
  "${gcloud_project[@]}" compute backend-buckets update "$BACKEND_BUCKET" \
    --enable-cdn \
    --cache-mode=CACHE_ALL_STATIC \
    --default-ttl=3600 \
    --max-ttl=86400 \
    --signed-url-cache-max-age=3600
else
  "${gcloud_project[@]}" compute backend-buckets create "$BACKEND_BUCKET" \
    --gcs-bucket-name="$BUCKET" \
    --enable-cdn \
    --cache-mode=CACHE_ALL_STATIC \
    --default-ttl=3600 \
    --max-ttl=86400 \
    --signed-url-cache-max-age=3600 \
    --global
fi

mkdir -p "$(dirname "$SIGNED_URL_KEY_FILE")"
if [[ ! -s "$SIGNED_URL_KEY_FILE" ]]; then
  head -c 16 /dev/urandom | base64 | tr '+/' '-_' > "$SIGNED_URL_KEY_FILE"
fi
chmod 600 "$SIGNED_URL_KEY_FILE"

signed_key_names="$("${gcloud_project[@]}" compute backend-buckets describe "$BACKEND_BUCKET" --global --format='value(cdnPolicy.signedUrlKeyNames)' || true)"
if [[ " $signed_key_names " != *" $SIGNED_URL_KEY_NAME "* ]]; then
  "${gcloud_project[@]}" compute backend-buckets add-signed-url-key "$BACKEND_BUCKET" \
    --key-name="$SIGNED_URL_KEY_NAME" \
    --key-file="$SIGNED_URL_KEY_FILE"
fi

project_number="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
cdn_fill_member="serviceAccount:service-${project_number}@cloud-cdn-fill.iam.gserviceaccount.com"
if ! gcloud storage buckets get-iam-policy "gs://$BUCKET" \
  --format='flattened(bindings[].members)' | grep -Fq "$cdn_fill_member"; then
  gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
    --member="$cdn_fill_member" \
    --role=roles/storage.objectViewer \
    >/dev/null
fi

if resource_exists url-maps "$URL_MAP"; then
  "${gcloud_project[@]}" compute url-maps set-default-service "$URL_MAP" \
    --default-backend-bucket="$BACKEND_BUCKET" \
    --global
else
  "${gcloud_project[@]}" compute url-maps create "$URL_MAP" \
    --default-backend-bucket="$BACKEND_BUCKET" \
    --global
fi

if [[ -n "$LE_CERTIFICATE_FILE" || -n "$LE_PRIVATE_KEY_FILE" ]]; then
  if [[ ! -s "$LE_CERTIFICATE_FILE" || ! -s "$LE_PRIVATE_KEY_FILE" ]]; then
    echo "LE_CERTIFICATE_FILE and LE_PRIVATE_KEY_FILE must both point at readable PEM files." >&2
    exit 1
  fi
  if ! resource_exists ssl-certificates "$CERTIFICATE"; then
    "${gcloud_project[@]}" compute ssl-certificates create "$CERTIFICATE" \
      --certificate="$LE_CERTIFICATE_FILE" \
      --private-key="$LE_PRIVATE_KEY_FILE" \
      --global
  fi
else
  if ! resource_exists ssl-certificates "$CERTIFICATE"; then
    "${gcloud_project[@]}" compute ssl-certificates create "$CERTIFICATE" \
      --domains="$DOMAIN" \
      --global
  fi
fi

if resource_exists target-https-proxies "$TARGET_PROXY"; then
  "${gcloud_project[@]}" compute target-https-proxies update "$TARGET_PROXY" \
    --ssl-certificates="$CERTIFICATE" \
    --url-map="$URL_MAP" \
    --global
else
  "${gcloud_project[@]}" compute target-https-proxies create "$TARGET_PROXY" \
    --ssl-certificates="$CERTIFICATE" \
    --url-map="$URL_MAP" \
    --global
fi

ipv4="$(gcloud --project "$PROJECT" compute addresses describe "$IPV4_ADDRESS" --global --format='value(address)')"
ipv6="$(gcloud --project "$PROJECT" compute addresses describe "$IPV6_ADDRESS" --global --format='value(address)')"

if ! resource_exists forwarding-rules "$IPV4_RULE"; then
  "${gcloud_project[@]}" compute forwarding-rules create "$IPV4_RULE" \
    --global \
    --address="$IPV4_ADDRESS" \
    --target-https-proxy="$TARGET_PROXY" \
    --ports=443 \
    --network-tier=PREMIUM
fi

if ! resource_exists forwarding-rules "$IPV6_RULE"; then
  "${gcloud_project[@]}" compute forwarding-rules create "$IPV6_RULE" \
    --global \
    --address="$IPV6_ADDRESS" \
    --target-https-proxy="$TARGET_PROXY" \
    --ports=443 \
    --network-tier=PREMIUM
fi

cat <<EOF
Asset CDN resources are ready or already existed.

Create DNS records for:
  $DOMAIN A     $ipv4
  $DOMAIN AAAA  $ipv6

Set these Medusa env vars after the DNS/certificate path is ready:
  MEDUSA_ASSET_CDN_BASE_URL=https://$DOMAIN
  MEDUSA_ASSET_CDN_SIGNED_URL_KEY_NAME=$SIGNED_URL_KEY_NAME
  MEDUSA_ASSET_CDN_SIGNED_URL_KEY=<contents of $SIGNED_URL_KEY_FILE>
  MEDUSA_ASSET_CDN_PROJECT=$PROJECT
  MEDUSA_ASSET_CDN_URL_MAP=$URL_MAP
EOF
