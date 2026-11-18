#!/usr/bin/env python3
"""April Daily auto-update: build data.json → git push (jika berubah) → Netlify redeploy.
Deterministik, stdlib sahaja. Token dibaca dari ~/.hermes/.env, tidak pernah diprint.
Usage: python3 update_app.py [--force]"""
import subprocess, json, os, sys, hashlib, urllib.request, time, datetime

APP = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
FORCE = "--force" in sys.argv
DEPLOY_FILES = ["index.html", "data.json", "assets/card-1.jpg", "assets/card-2.jpg", "assets/card-3.jpg"]


def env(key):
    for ln in open(os.path.join(HOME, ".hermes/.env")):
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip()
    return ""


def sh(*args, check=True):
    r = subprocess.run(args, cwd=APP, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"{args[0]} gagal: {r.stderr[-300:]}")
    return r


def api(method, url, token, body=None, ctype="application/json", raw=None):
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", ("token " if "github" in url else "Bearer ") + token)
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    if data is not None:
        req.add_header("Content-Type", ctype)
    with urllib.request.urlopen(req, data=data, timeout=45) as resp:
        return resp.status, resp.read()


def main():
    log = {"ts": datetime.datetime.now().isoformat(timespec="seconds")}
    old = None
    if os.path.exists(os.path.join(APP, "data.json")):
        try:
            old = json.load(open(os.path.join(APP, "data.json"))).get("tabs")
        except Exception:
            pass
    sh("python3", os.path.join(APP, "build_data.py"))
    new = json.load(open(os.path.join(APP, "data.json")))
    changed = FORCE or (old != new.get("tabs"))
    log["tabs"] = {k: v.get("date") for k, v in new["tabs"].items()}
    log["changed"] = changed

    def emit():
        line = json.dumps(log, ensure_ascii=False)
        with open(os.path.join(APP, "update.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return line

    if not changed:
        log["action"] = "tiada perubahan kandungan — skip push & deploy"
        emit()
        return  # senyap untuk cron no_agent (empty stdout = tiada delivery)

    # git commit + push
    gh = env("GITHUB_TOKEN")
    sh("git", "add", "data.json", "assets", "index.html")
    msg = "chore: auto-update data " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    r = sh("git", "commit", "-q", "-m", msg, check=False)
    if r.returncode == 0:
        sh("git", "push", "-q", "origin", "main")
        log["git"] = "pushed: " + msg
    else:
        log["git"] = "tiada perubahan git (skip)"

    # Netlify redeploy
    nl = env("NETLIFY_AUTH_TOKEN")
    site = open(os.path.join(APP, ".netlify-site-id")).read().strip()
    files = {"/" + f: hashlib.sha1(open(os.path.join(APP, f), "rb").read()).hexdigest() for f in DEPLOY_FILES if os.path.exists(os.path.join(APP, f))}
    st, raw = api("POST", f"https://api.netlify.com/api/v1/sites/{site}/deploys", nl, {"files": files})
    dep = json.loads(raw)
    did = dep["id"]
    by_hash = {v: k.lstrip("/") for k, v in files.items()}
    uploaded = []
    for digest in dep.get("required", []):
        path = by_hash.get(digest)
        if not path:
            continue
        ct = "application/json" if path.endswith(".json") else "image/jpeg" if path.endswith(".jpg") else "text/html"
        api("PUT", f"https://api.netlify.com/api/v1/deploys/{did}/files/{path}", nl, ctype=ct, raw=open(os.path.join(APP, path), "rb").read())
        uploaded.append(path)
    state = dep.get("state")
    for _ in range(12):
        if state == "ready":
            break
        time.sleep(5)
        _, raw = api("GET", f"https://api.netlify.com/api/v1/deploys/{did}", nl)
        state = json.loads(raw).get("state")
    log["netlify"] = {"deploy": did, "state": state, "uploaded": uploaded}
    print(emit())


if __name__ == "__main__":
    main()
