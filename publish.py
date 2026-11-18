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


def main():
    log = [f"=== {datetime.datetime.now().isoformat(timespec='seconds')} ==="]
    os.chdir(APP)

    # 1. Rebuild data.json + assets dari output harian terbaru
    out = sh("python3 build_data.py")
    log.append(out.splitlines()[0] if out else "build: ok")

    # 2. Commit + push kalau ada perubahan
    if sh("git status --porcelain"):
        sh("git add -A")
        msg = "chore: auto-update data " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        sh(f'git commit -q -m "{msg}"')
        sh("git push -q origin main")
        log.append("git: pushed")
    else:
        log.append("git: tiada perubahan")

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
    print("\n".join(log))
    return 0 if st == "ready" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
