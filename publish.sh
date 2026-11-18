#!/usr/bin/env bash
# April Daily — auto-update: build data → push GitHub → redeploy Netlify.
# Token dibaca dari ~/.hermes/.env, nilai TIDAK pernah diprint.
set -u
APP="$HOME/.hermes/apps/april-daily"
cd "$APP" || exit 1

T=$(grep "^GITHUB_TOKEN=" "$HOME/.hermes/.env" | head -1 | cut -d= -f2- | tr -d '\n\r')
N=$(grep "^NETLIFY_AUTH_TOKEN=" "$HOME/.hermes/.env" | head -1 | cut -d= -f2- | tr -d '\n\r')
SITE_ID=$(cat /tmp/site2_id.txt 2>/dev/null)
[ -z "$SITE_ID" ] && SITE_ID="fb094866-625c-43b6-b3ca-70392a741775"

echo "=== 1. build_data.py ==="
python3 build_data.py || exit 1

echo "=== 2. git commit + push (jika ada perubahan) ==="
git add -A
if git diff --cached --quiet; then
  echo "tiada perubahan untuk commit"
else
  git commit -q -m "chore: auto-update data harian $(date '+%Y-%m-%d %H:%M')"
  git push -q origin main && echo "pushed OK"
fi

echo "=== 3. Netlify redeploy ==="
python3 - <<'EOF'
import hashlib, json, os
files = {}
for path in ["index.html", "data.json", "assets/card-1.jpg", "assets/card-2.jpg", "assets/card-3.jpg"]:
    if os.path.exists(path):
        files["/" + path] = hashlib.sha1(open(path, 'rb').read()).hexdigest()
json.dump({"files": files}, open('/tmp/april_daily_digest.json', 'w'))
print("digest map:", list(files.keys()))
EOF
curl -s -X POST -H "Authorization: Bearer $N" -H "Content-Type: application/json" \
  -d @/tmp/april_daily_digest.json "https://api.netlify.com/api/v1/sites/${SITE_ID}/deploys" \
  -o /tmp/april_daily_deploy.json -w "create deploy: HTTP %{http_code}\n"
python3 - <<'EOF'
import json
d = json.load(open('/tmp/april_daily_deploy.json'))
open('/tmp/april_daily_deploy_id.txt', 'w').write(d.get('id', ''))
req = d.get('required', [])
open('/tmp/april_daily_required.txt', 'w').write("\n".join(req))
print("deploy id:", d.get('id'), "| state:", d.get('state'), "| required:", len(req))
EOF
DEPLOY_ID=$(cat /tmp/april_daily_deploy_id.txt)

# upload hanya fail yang Netlify minta (required = sha1 digest)
python3 - "$DEPLOY_ID" "$N" <<'EOF'
import hashlib, json, os, subprocess, sys
deploy_id, token = sys.argv[1], sys.argv[2]
required = set(open('/tmp/april_daily_required.txt').read().split())
paths = ["index.html", "data.json", "assets/card-1.jpg", "assets/card-2.jpg", "assets/card-3.jpg"]
ct = {".html": "text/html", ".json": "application/json", ".jpg": "image/jpeg"}
for p in paths:
    if not os.path.exists(p):
        continue
    digest = hashlib.sha1(open(p, 'rb').read()).hexdigest()
    if digest not in required:
        continue  # Netlify dah ada fail ni
    ext = os.path.splitext(p)[1]
    r = subprocess.run([
        "curl", "-s", "-X", "PUT", "-H", f"Authorization: Bearer {token}",
        "-H", f"Content-Type: {ct.get(ext, 'application/octet-stream')}",
        "--data-binary", "@" + os.path.abspath(p),
        f"https://api.netlify.com/api/v1/deploys/{deploy_id}/files/{p}",
        "-o", "/dev/null", "-w", "%{http_code}"
    ], capture_output=True, text=True)
    print(f"upload {p}: HTTP {r.stdout.strip()}")
EOF

sleep 3
curl -s -H "Authorization: Bearer $N" "https://api.netlify.com/api/v1/deploys/${DEPLOY_ID}" \
  | python3 -c "import json,sys;print('deploy state:',json.load(sys.stdin).get('state'))"

echo "=== 4. verify live ==="
curl -s "https://april-daily-0508.netlify.app/data.json" \
  | python3 -c "import json,sys;d=json.load(sys.stdin);print('live updated:',d.get('updated'),'| tabs:',list(d.get('tabs',{}).keys()))"
echo "=== PUBLISH SELESAI ==="
