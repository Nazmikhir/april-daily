#!/usr/bin/env python3
"""April Daily auto-publish: build_data.py → git push → Netlify deploy.
Dipanggil oleh system crontab selepas setiap pipeline harian. Tiada token dicetak."""
import subprocess, os, json, hashlib, urllib.request, datetime, glob, time, sys

APP = os.path.expanduser("~/.hermes/apps/april-daily")
ENV = os.path.expanduser("~/.hermes/.env")
FILES = ["index.html", "data.json"]  # + semua assets/*.jpg


def env(key):
    if not os.path.exists(ENV):
        return ""
    for line in open(ENV):
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return ""


def sh(cmd, check=True):
    r = subprocess.run(cmd, cwd=APP, shell=True, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"{cmd[:80]} -> rc={r.returncode}: {(r.stderr or r.stdout)[-300:]}")
    return r.stdout.strip()


def api(method, url, token, payload=None, raw=None, ctype="application/json"):
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if raw is not None:
        req.data = raw
        req.add_header("Content-Type", ctype)
    elif payload is not None:
        req.data = json.dumps(payload).encode()
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=90) as resp:
        body = resp.read()
        return json.loads(body) if body else {}


def notify_telegram(text):
    """Hantar mesej pendek 'selesai' ke Telegram Boss selepas app berjaya update."""
    token = env("TELEGRAM_BOT_TOKEN")
    if not token:
        return "telegram: tiada token"
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps({"chat_id": "670763478", "text": text}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return "telegram: hantar" if resp.status == 200 else f"telegram: HTTP {resp.status}"
    except Exception as e:
        return f"telegram: gagal ({e})"


def fingerprint():
    """Hash kandungan sebenar (abai 'updated') + assets — untuk skip bila tiada perubahan."""
    d = json.load(open(os.path.join(APP, "data.json")))
    d.pop("updated", None)
    h = hashlib.sha256(json.dumps(d, sort_keys=True, ensure_ascii=False).encode())
    for p in sorted(glob.glob(os.path.join(APP, "assets/*.jpg"))):
        h.update(hashlib.sha256(open(p, "rb").read()).digest())
    return h.hexdigest()


def main():
    log = [f"=== {datetime.datetime.now().isoformat(timespec='seconds')} ==="]
    os.chdir(APP)

    # 1. Rebuild data.json + assets dari output harian terbaru
    out = sh("python3 build_data.py")
    log.append(out.splitlines()[0] if out else "build: ok")

    # 2. Skip kalau kandungan sebenar tak berubah (jimat deploy & senyap)
    fp = fingerprint()
    state_p = os.path.join(APP, ".publish_state.json")
    last = json.load(open(state_p)).get("fp") if os.path.exists(state_p) else None
    if fp == last:
        log.append("tiada perubahan kandungan — skip push/deploy/notify")
        print("\n".join(log))
        return 0

    # 3. Commit + push
    if sh("git status --porcelain"):
        sh("git add -A")
        msg = "chore: auto-update data " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        sh(f'git commit -q -m "{msg}"')
        sh("git push -q origin main")
        log.append("git: pushed")
    else:
        log.append("git: tiada perubahan fail")

    # 3. Netlify deploy (hanya fail berubah diminta oleh API)
    token = env("NETLIFY_AUTH_TOKEN")
    conf = json.load(open(os.path.join(APP, "netlify.json")))
    site_id = conf["site_id"]
    paths = FILES + sorted(os.path.relpath(p, APP) for p in glob.glob(os.path.join(APP, "assets/*.jpg")))
    digest = {}
    for p in paths:
        digest["/" + p] = hashlib.sha1(open(p, "rb").read()).hexdigest()
    dep = api("POST", f"https://api.netlify.com/api/v1/sites/{site_id}/deploys", token, {"files": digest})
    dep_id = dep["id"]
    required = set(dep.get("required", []))
    by_hash = {v: k for k, v in digest.items()}
    for h in required:
        p = by_hash.get(h)
        if not p:
            continue
        ctype = "application/json" if p.endswith(".json") else "image/jpeg" if p.endswith(".jpg") else "text/html"
        api("PUT", f"https://api.netlify.com/api/v1/deploys/{dep_id}/files{p}", token,
            raw=open(p.lstrip("/"), "rb").read(), ctype=ctype)
    for _ in range(12):
        time.sleep(5)
        st = api("GET", f"https://api.netlify.com/api/v1/deploys/{dep_id}", token).get("state")
        if st in ("ready", "error"):
            break
    log.append(f"netlify: deploy {dep_id[:12]} state={st} (uploaded {len(required)} file)")
    if st == "ready":
        json.dump({"fp": fp}, open(state_p, "w"))
        d = json.load(open(os.path.join(APP, "data.json")))
        tabs = d.get("tabs", {})
        ringkas = " · ".join(f"{k} ({v.get('date', '?')})" for k, v in tabs.items())
        log.append(notify_telegram(
            f"✅ April Daily selesai update — data dah masuk app:\n{ringkas}\n{conf['url']}"))
    print("\n".join(log))
    return 0 if st == "ready" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
