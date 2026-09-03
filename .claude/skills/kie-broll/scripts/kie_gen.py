#!/usr/bin/env python3
"""Generate one video clip (or still) through the kie.ai job API and download it.

    python3 kie_gen.py preflight                                   # key + host reachable, no cost
    python3 kie_gen.py generate --model bytedance/seedance-1.5-pro \
        --prompt "..." --aspect 9:16 --duration 5 --slug product-pour --out mg/gen
    python3 kie_gen.py generate --model kling-3.0/video --prompt "..." --aspect 9:16 \
        --duration 5 --ref frame.png --set mode=std --set sound=false
    python3 kie_gen.py generate --model nano-banana-pro --prompt "..." --aspect 9:16   # a still
    python3 kie_gen.py generate --dry-run ...                      # print the payload, no network
    python3 kie_gen.py status --task-id <id> [--download --out dir --slug name]

Every model on kie.ai shares two calls (Authorization: Bearer KIE_API_KEY on both):
  POST https://api.kie.ai/api/v1/jobs/createTask   {"model": "<id>", "input": {...}}
       -> {"code": 200, "data": {"taskId": "..."}}
  GET  https://api.kie.ai/api/v1/jobs/recordInfo?taskId=<id>
       -> data.state in waiting|queuing|generating|success|fail; on success data.resultJson is a
          JSON *string* holding resultUrls[]; data.creditsConsumed is the spend; on fail
          data.failCode / data.failMsg.

Model ids and INPUT FIELD NAMES differ per model family (some ids are namespaced, some are
not). This script sends the common fields — prompt, aspect_ratio, duration, resolution — and
lets --set add or override anything else; check the model's page under
https://docs.kie.ai/market before the first call and record what worked in
references/models.md. A createTask code other than 200 is almost always a field-name or
value mismatch, not an auth problem.

Cost: kie.ai has no quote endpoint. Read the per-clip price off the model page (or
references/models.md), state it, and get a yes BEFORE submitting (--yes skips the prompt).
Outputs on kie.ai's servers expire (~14 days) and result links are short-lived — this script
always downloads. Local --ref files are uploaded through kie.ai's base64 upload host
(<= 10 MB); pass an https URL for anything bigger.

Key resolution: KIE_API_KEY in the environment, then a .env from the current directory up to
the filesystem root, then ~/.config/kie/api-key (shared with the kie-image skill).
"""
import argparse
import base64
import json
import mimetypes
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("KIE_BASE_URL", "https://api.kie.ai").rstrip("/")
UPLOAD = "https://kieai.redpandaai.co/api/file-base64-upload"
UPLOAD_MAX = 10 * 1024 * 1024
KEY_FILE = pathlib.Path.home() / ".config" / "kie" / "api-key"

# Reference-media field per model family; --ref-field overrides. Video models on the market
# mostly take image_urls (first/last frame or reference stills); the image families differ.
REF_FIELD = {
    "nano-banana-pro": "image_input", "nano-banana-2": "image_input", "nano-banana-2-lite": "image_input",
    "google/nano-banana": "image_input", "google/nano-banana-edit": "image_input",
    "gpt-image-2": "input_urls", "gpt-image-2-image-to-image": "input_urls",
}
DEFAULT_REF_FIELD = "image_urls"
TERMINAL_OK, TERMINAL_FAIL = "success", "fail"


def die(msg, code=1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


# ----------------------------------------------------------------------------- key

def _read_env_file(p):
    try:
        for line in pathlib.Path(p).read_text().splitlines():
            m = re.match(r"^\s*KIE_API_KEY\s*=\s*(.+?)\s*$", line)
            if m:
                return m.group(1).strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def get_key():
    k = os.environ.get("KIE_API_KEY", "").strip()
    if k:
        return k
    d = pathlib.Path.cwd()
    while True:
        k = _read_env_file(d / ".env")
        if k:
            return k
        if d.parent == d:
            break
        d = d.parent
    if KEY_FILE.exists():
        k = KEY_FILE.read_text().strip()
        if k:
            return k
    die("No kie.ai key. Put KIE_API_KEY in .env (or the environment), or write it to "
        "~/.config/kie/api-key. Get one at https://kie.ai/api-key")


# ----------------------------------------------------------------------------- http

def req(url, key, method="GET", body=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        "Accept": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")[:600]
        try:
            return json.loads(raw)
        except Exception:
            die(f"HTTP {e.code} from {url}: {raw}")
    except urllib.error.URLError as e:
        die(f"Cannot reach {url} ({e.reason}). Hosts this script needs: api.kie.ai (jobs), "
            f"tempfile.aiquickdraw.com (finished files), kieai.redpandaai.co (reference uploads).")


def upload_local(path, key):
    p = pathlib.Path(path).expanduser()
    if not p.is_file():
        die(f"reference file not found: {p}")
    if p.stat().st_size > UPLOAD_MAX:
        die(f"{p.name} is {p.stat().st_size // 1024} KB; the base64 upload host takes <= 10 MB. "
            f"Host it and pass an https URL instead.")
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    b64 = base64.b64encode(p.read_bytes()).decode()
    out = req(UPLOAD, key, "POST", {"base64Data": f"data:{mime};base64,{b64}",
                                    "uploadPath": "video-editor/refs", "fileName": p.name})
    url = (out.get("data") or {}).get("downloadUrl")
    if not url:
        die(f"upload failed: {json.dumps(out)[:400]}")
    print(f"  uploaded {p.name} -> {url}", file=sys.stderr)
    return url


# ----------------------------------------------------------------------------- helpers

def slugify(text, limit=48):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:limit].rstrip("-")) or "clip"


def unique_dest(outdir, slug, ext):
    dest = outdir / f"{slug}{ext}"
    n = 2
    while dest.exists():
        dest = outdir / f"{slug}-v{n}{ext}"
        n += 1
    return dest


def log_event(outdir, rec):
    rec = {"ts": time.strftime("%FT%TZ", time.gmtime()), **rec}
    with (outdir / "_kie_log.jsonl").open("a") as f:
        f.write(json.dumps(rec) + "\n")


def parse_result_urls(info):
    try:
        rj = info.get("resultJson") or "{}"
        rj = json.loads(rj) if isinstance(rj, str) else rj
    except Exception:
        die(f"could not parse resultJson: {str(info.get('resultJson'))[:400]}")
    urls = rj.get("resultUrls") or rj.get("result_urls") or []
    if not urls and rj.get("resultUrl"):
        urls = [rj["resultUrl"]]
    return urls


def download_all(urls, outdir, slug, fallback_ext):
    outdir.mkdir(parents=True, exist_ok=True)
    saved = []
    for i, u in enumerate(urls, 1):
        ext = pathlib.Path(urllib.parse.urlparse(u).path).suffix or fallback_ext
        base = slug if len(urls) == 1 else f"{slug}-{i}"
        dest = unique_dest(outdir, base, ext)
        try:
            with urllib.request.urlopen(u, timeout=600) as r, open(dest, "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
        except Exception as e:
            die(f"generated OK but the download failed ({e}). Direct URL (expires): {u}")
        saved.append(str(dest))
    return saved


def poll(task_id, key, interval, timeout):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        out = req(f"{API}/api/v1/jobs/recordInfo?taskId={urllib.parse.quote(task_id)}", key)
        info = out.get("data") or {}
        state = info.get("state")
        if state != last:
            print(f"  state={state}", file=sys.stderr)
            last = state
        if state in (TERMINAL_OK, TERMINAL_FAIL):
            return info
        time.sleep(interval)
    return None


# ----------------------------------------------------------------------------- commands

def cmd_preflight(a):
    key = get_key()
    out = req(f"{API}/api/v1/jobs/recordInfo?taskId=preflight-check", key)
    code = out.get("code")
    if code == 401:
        die(f"api.kie.ai reachable but the key was rejected: {out.get('msg')}")
    print(f"OK: api.kie.ai reachable, key accepted (probe code={code} msg={out.get('msg')!r}).")


def cmd_status(a):
    key = get_key()
    out = req(f"{API}/api/v1/jobs/recordInfo?taskId={urllib.parse.quote(a.task_id)}", key)
    info = out.get("data") or {}
    if not a.download:
        print(json.dumps(out, indent=2))
        return
    if info.get("state") != TERMINAL_OK:
        die(f"task is {info.get('state')}, nothing to download yet")
    urls = parse_result_urls(info)
    saved = download_all(urls, pathlib.Path(a.out).expanduser(), a.slug or f"task-{a.task_id[:8]}", ".mp4")
    print(json.dumps({"taskId": a.task_id, "creditsConsumed": info.get("creditsConsumed"),
                      "files": saved, "sourceUrls": urls}, indent=2))


def build_input(a, key):
    inp = {"prompt": a.prompt.strip()}
    if a.aspect:
        inp["aspect_ratio"] = a.aspect
    if a.duration is not None:
        inp["duration"] = a.duration
    if a.resolution:
        inp["resolution"] = a.resolution
    if a.no_text and "no subtitles" not in inp["prompt"].lower():
        inp["prompt"] += "\n\nNo subtitles, no captions, no on-screen text, no watermark."
    refs = []
    for r in a.ref or []:
        refs.append(r if r.startswith(("http://", "https://")) else (upload_local(r, key) if key else f"<upload:{pathlib.Path(r).name}>"))
    if refs:
        inp[a.ref_field or REF_FIELD.get(a.model, DEFAULT_REF_FIELD)] = refs
    for kv in a.set or []:
        k, _, v = kv.partition("=")
        if not k:
            die(f"bad --set {kv!r}; use key=value")
        try:
            inp[k] = json.loads(v)
        except Exception:
            inp[k] = v
    return inp


def cmd_generate(a):
    if a.prompt_file:
        a.prompt = pathlib.Path(a.prompt_file).read_text()
    if not a.prompt or not a.prompt.strip():
        die("--prompt (or --prompt-file) is required")
    outdir = pathlib.Path(a.out).expanduser()
    slug = slugify(a.slug or a.prompt)

    if a.dry_run:
        payload = {"model": a.model, "input": build_input(a, key=None)}
        print("DRY RUN - payload that would be POSTed to /api/v1/jobs/createTask:")
        print(json.dumps(payload, indent=2))
        print(f"output: {outdir}/{slug}.<ext>")
        return

    key = get_key()
    print(f"model={a.model} aspect={a.aspect} duration={a.duration} resolution={a.resolution or '-'} "
          f"refs={len(a.ref or [])} -> {outdir}/{slug}.<ext>", file=sys.stderr)
    est = f"~{a.est_cost}" if a.est_cost else "see the model page (kie.ai has no quote endpoint)"
    print(f"cost per clip: {est}", file=sys.stderr)
    if not a.yes:
        ans = input("Submit and spend kie.ai credits? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("aborted")
            sys.exit(2)

    payload = {"model": a.model, "input": build_input(a, key)}
    outdir.mkdir(parents=True, exist_ok=True)
    created = req(f"{API}/api/v1/jobs/createTask", key, "POST", payload)
    if created.get("code") != 200:
        log_event(outdir, {"event": "submit-failed", "model": a.model, "slug": slug,
                           "code": created.get("code"), "msg": created.get("msg")})
        die(f"createTask rejected: code={created.get('code')} msg={created.get('msg')!r}. "
            f"Check the model id and its input field names at https://docs.kie.ai/market "
            f"(then record them in references/models.md).")
    task_id = (created.get("data") or {}).get("taskId")
    if not task_id:
        die(f"no taskId in response: {json.dumps(created)[:400]}")
    log_event(outdir, {"event": "submitted", "taskId": task_id, "model": a.model, "slug": slug,
                       "input": {k: v for k, v in payload["input"].items() if k != "prompt"},
                       "promptWordCount": len(payload["input"]["prompt"].split()),
                       "estCost": a.est_cost})
    print(f"taskId={task_id}", file=sys.stderr)
    if a.no_poll:
        print(f"resume with: python3 {pathlib.Path(__file__).name} status --task-id {task_id} --download --out {outdir} --slug {slug}")
        return

    info = poll(task_id, key, a.interval, a.timeout)
    if info is None:
        die(f"timed out after {a.timeout}s; the task may still finish. Resume with: "
            f"python3 {pathlib.Path(__file__).name} status --task-id {task_id} --download --out {outdir} --slug {slug}")
    if info.get("state") == TERMINAL_FAIL:
        log_event(outdir, {"event": "failed", "taskId": task_id, "failCode": info.get("failCode"),
                           "failMsg": info.get("failMsg"), "creditsConsumed": info.get("creditsConsumed")})
        die(f"generation failed: {info.get('failCode')} {info.get('failMsg')}")

    urls = parse_result_urls(info)
    if not urls:
        die(f"no result URLs: {json.dumps(info)[:400]}")
    saved = download_all(urls, outdir, slug, ".mp4")
    log_event(outdir, {"event": "downloaded", "taskId": task_id, "files": saved,
                       "creditsConsumed": info.get("creditsConsumed"), "costTimeMs": info.get("costTime")})
    print(json.dumps({"taskId": task_id, "model": a.model, "creditsConsumed": info.get("creditsConsumed"),
                      "costTimeMs": info.get("costTime"), "files": saved, "sourceUrls": urls}, indent=2))


# ----------------------------------------------------------------------------- cli

def build_parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("preflight", help="key + host check, no cost").set_defaults(fn=cmd_preflight)

    s = sub.add_parser("status", help="inspect (and optionally download) an existing task")
    s.add_argument("--task-id", required=True)
    s.add_argument("--download", action="store_true")
    s.add_argument("--out", default=".")
    s.add_argument("--slug")
    s.set_defaults(fn=cmd_status)

    g = sub.add_parser("generate", help="createTask, poll to completion, download")
    g.add_argument("--model", required=True, help="kie.ai model id, e.g. bytedance/seedance-1.5-pro, kling-3.0/video, nano-banana-pro")
    g.add_argument("--prompt")
    g.add_argument("--prompt-file")
    g.add_argument("--aspect", default="9:16", help="aspect_ratio (default 9:16); '' to omit")
    g.add_argument("--duration", type=int, help="seconds; omitted for stills")
    g.add_argument("--resolution", help="only if the model documents it (e.g. 720p, 1080p, 2K)")
    g.add_argument("--ref", action="append", help="reference image/video: local path (uploaded) or https URL; repeatable")
    g.add_argument("--ref-field", help=f"input field for --ref (default per family, else {DEFAULT_REF_FIELD})")
    g.add_argument("--set", action="append", metavar="KEY=VALUE", help="extra/override input field (JSON values parsed); repeatable")
    g.add_argument("--no-text", action="store_true", default=True, help="append the no-subtitles/no-watermark clause (default on)")
    g.add_argument("--allow-text", dest="no_text", action="store_false")
    g.add_argument("--slug", help="output basename (default: from the prompt)")
    g.add_argument("--out", default=".", help="output directory (also holds _kie_log.jsonl)")
    g.add_argument("--est-cost", help="the per-clip price you read off the model page, for the log and the confirmation")
    g.add_argument("--yes", action="store_true", help="skip the spend confirmation")
    g.add_argument("--no-poll", action="store_true", help="submit only; print the resume command")
    g.add_argument("--interval", type=int, default=10, help="seconds between polls (default 10)")
    g.add_argument("--timeout", type=int, default=1800, help="seconds to wait (default 1800)")
    g.add_argument("--dry-run", action="store_true", help="print the payload; no network, no cost")
    g.set_defaults(fn=cmd_generate)
    return p


if __name__ == "__main__":
    args = build_parser().parse_args()
    if getattr(args, "aspect", None) == "":
        args.aspect = None
    args.fn(args)
