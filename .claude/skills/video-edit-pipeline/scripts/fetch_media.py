#!/usr/bin/env python3
"""Move media between SharePoint / OneDrive and the session's projects directory.

A cloud session has no access to anyone's hard drive, so footage arrives as a link and
renders leave as a link. This script is the whole bridge (python3 stdlib only).

  # footage in: a SharePoint or OneDrive sharing link (or any direct https URL) → a verified local file
  python3 fetch_media.py fetch "<share link>" --dest <projects dir>/<slug> [--name source.mp4]

  # renders out: a local file → a SharePoint document library / OneDrive folder, plus a view link
  python3 fetch_media.py push <projects dir>/<slug>/output-v2.mp4 --drive-id <driveId> \
      [--folder-id <itemId>] [--name output-v2.mp4] [--link organization|anonymous]

  # what is this link? (no download)
  python3 fetch_media.py inspect "<share link>"

How links are resolved
  * "Anyone with the link" sharing links download without credentials:
      - SharePoint / OneDrive for Business (…sharepoint.com/:v:/…, /:f:/, /:u:/) → the same URL with
        `download=1` added.
      - OneDrive personal (1drv.ms, onedrive.live.com) → the public shares API
        `https://api.onedrive.com/v1.0/shares/u!<base64url(link)>/root/content`.
  * Links restricted to the organisation need a Microsoft Graph bearer token in MS_GRAPH_TOKEN
    (Files.Read / Files.ReadWrite; Sites.ReadWrite.All for team libraries). Then:
      `https://graph.microsoft.com/v1.0/shares/u!<base64url(link)>/driveItem/content`.
    Without the token an org-only link comes back as an HTML sign-in page — this script detects
    that and says so instead of saving HTML as "source.mp4".
  * A direct https URL to a file is downloaded as-is.
  * `push` always needs MS_GRAPH_TOKEN: it opens a Graph upload session and PUTs 10 MiB chunks,
    so files far past the 4 MB simple-upload limit (and the connector's 1 MB cap) work. The
    driveId / folder itemId come from the Microsoft 365 connector's sharepoint_folder_search or
    from a file:///<driveId>/<itemId> resource URI.

Every fetched file is probed with ffprobe (FFPROBE env, the npm-bundled build, or PATH) and the
result printed as JSON; a download that does not probe as media is deleted and reported.
Small text artefacts (specs, notes, MASTER_CONTEXT) do not need this script — the connector's
read_resource / sharepoint_upload_file handle files under 1 MB directly.
"""
import argparse
import base64
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

GRAPH = "https://graph.microsoft.com/v1.0"
CHUNK = 10 * 1024 * 1024  # multiple of 320 KiB, as Graph requires
UA = "video-editor-agent/1.0"


def die(msg, code=1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def ffprobe_bin():
    for cand in (os.environ.get("FFPROBE"), os.environ.get("FFPROBE_PATH")):
        if cand and os.path.exists(cand):
            return cand
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "package.json").exists() and (parent / "node_modules" / "ffprobe-static").exists():
            try:
                out = subprocess.run(["node", "-p", "require('ffprobe-static').path"], cwd=parent,
                                     capture_output=True, text=True, check=True).stdout.strip()
                if out and os.path.exists(out):
                    return out
            except Exception:
                pass
            break
    return shutil.which("ffprobe") or "ffprobe"


def encode_share(url):
    """Graph / OneDrive 'sharing URL' encoding: u! + base64url without padding."""
    b = base64.b64encode(url.encode()).decode().rstrip("=").replace("/", "_").replace("+", "-")
    return "u!" + b


def token():
    return os.environ.get("MS_GRAPH_TOKEN", "").strip()


def classify(url):
    u = urllib.parse.urlparse(url)
    host = u.netloc.lower()
    if host.endswith("sharepoint.com") or host.endswith("sharepoint.us") or host.endswith("sharepoint.de"):
        return "sharepoint"
    if host in ("1drv.ms", "onedrive.live.com") or host.endswith(".1drv.ms"):
        return "onedrive"
    return "direct"


def candidates(url):
    """Ordered (label, download URL, headers) attempts for a link."""
    kind = classify(url)
    out = []
    tok = token()
    if kind in ("sharepoint", "onedrive") and tok:
        out.append(("graph shares API (MS_GRAPH_TOKEN)",
                    f"{GRAPH}/shares/{encode_share(url)}/driveItem/content",
                    {"Authorization": f"Bearer {tok}"}))
    if kind == "sharepoint":
        u = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        q["download"] = "1"
        out.append(("sharepoint link + download=1",
                    urllib.parse.urlunparse(u._replace(query=urllib.parse.urlencode(q))), {}))
    if kind == "onedrive":
        out.append(("onedrive public shares API",
                    f"https://api.onedrive.com/v1.0/shares/{encode_share(url)}/root/content", {}))
    if kind == "direct":
        out.append(("direct URL", url, {}))
    return kind, out


def open_url(url, headers=None, method="GET", data=None, timeout=120):
    r = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": UA, **(headers or {})})
    return urllib.request.urlopen(r, timeout=timeout)


def filename_from(resp, fallback):
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd)
    if m:
        return urllib.parse.unquote(m.group(1)).strip()
    path = urllib.parse.urlparse(resp.geturl()).path
    base = pathlib.Path(path).name
    return base if "." in base else fallback


def probe(path):
    r = subprocess.run([ffprobe_bin(), "-v", "error", "-show_entries",
                        "format=duration,size,format_name:stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
                        "-of", "json", str(path)], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except Exception:
        return None


# ----------------------------------------------------------------------------- commands

def cmd_inspect(a):
    kind, tries = candidates(a.url)
    print(json.dumps({"kind": kind, "graphToken": bool(token()),
                      "attempts": [{"via": t[0], "url": t[1]} for t in tries]}, indent=2))


def cmd_fetch(a):
    dest = pathlib.Path(a.dest).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    kind, tries = candidates(a.url)
    if not tries:
        die("could not build a download URL for that link")
    last_err = None
    for via, url, headers in tries:
        print(f"  trying {via}", file=sys.stderr)
        try:
            resp = open_url(url, headers)
        except urllib.error.HTTPError as e:
            last_err = f"{via}: HTTP {e.code}"
            print(f"  {last_err}", file=sys.stderr)
            continue
        except urllib.error.URLError as e:
            last_err = f"{via}: {e.reason}"
            print(f"  {last_err}", file=sys.stderr)
            continue
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "text/html" in ctype:
            last_err = (f"{via}: got an HTML page instead of a file — the link is restricted to the "
                        f"organisation (set MS_GRAPH_TOKEN) or is not a file link (a folder needs the connector)")
            print(f"  {last_err}", file=sys.stderr)
            continue
        name = a.name or filename_from(resp, "source.bin")
        path = dest / name
        if path.exists() and not a.overwrite:
            die(f"{path} exists; pass --overwrite or --name")
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(path, "wb") as f:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total and done % (50 << 20) < (1 << 20):
                    print(f"  {done / 1e6:.0f}/{total / 1e6:.0f} MB", file=sys.stderr)
        info = probe(path)
        if not info or not info.get("streams"):
            path.unlink(missing_ok=True)
            die(f"downloaded {done} bytes via {via} but ffprobe does not read it as media; removed. "
                f"Check the link points at a video/audio file.")
        fmt = info.get("format", {})
        print(json.dumps({"path": str(path), "bytes": done, "via": via, "kind": kind,
                          "duration": float(fmt.get("duration") or 0), "format": fmt.get("format_name"),
                          "streams": [{k: v for k, v in s.items()} for s in info["streams"]]}, indent=2))
        return
    die(f"every route failed — last: {last_err}")


def graph(method, url, tok, body=None, headers=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = {"Authorization": f"Bearer {tok}", **(headers or {})}
    if body is not None:
        h["Content-Type"] = "application/json"
    try:
        with open_url(url, h, method=method, data=data, timeout=600) as resp:
            payload = resp.read()
            return resp.status, (json.loads(payload) if payload else {})
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:600]


def cmd_push(a):
    tok = token()
    if not tok:
        die("push needs MS_GRAPH_TOKEN (a Microsoft Graph bearer token with Files.ReadWrite / Sites.ReadWrite.All)")
    src = pathlib.Path(a.file).expanduser()
    if not src.is_file():
        die(f"file not found: {src}")
    name = a.name or src.name
    size = src.stat().st_size
    parent = f"items/{a.folder_id}" if a.folder_id else "root"
    st, js = graph("POST", f"{GRAPH}/drives/{a.drive_id}/{parent}:/{urllib.parse.quote(name)}:/createUploadSession", tok,
                   body={"item": {"@microsoft.graph.conflictBehavior": a.conflict, "name": name}})
    if st >= 300 or not isinstance(js, dict) or "uploadUrl" not in js:
        die(f"createUploadSession failed ({st}): {str(js)[:400]}")
    upload_url = js["uploadUrl"]
    item = None
    with open(src, "rb") as f:
        off = 0
        while off < size:
            chunk = f.read(CHUNK)
            end = off + len(chunk) - 1
            r = urllib.request.Request(upload_url, data=chunk, method="PUT", headers={
                "User-Agent": UA, "Content-Length": str(len(chunk)),
                "Content-Range": f"bytes {off}-{end}/{size}"})
            try:
                with urllib.request.urlopen(r, timeout=600) as resp:
                    body = resp.read()
                    if resp.status in (200, 201):
                        item = json.loads(body)
            except urllib.error.HTTPError as e:
                die(f"chunk {off}-{end} failed: HTTP {e.code} {e.read().decode(errors='replace')[:300]}")
            off = end + 1
            print(f"  {off / 1e6:.0f}/{size / 1e6:.0f} MB", file=sys.stderr)
    if not item:
        die("upload finished without an item response")
    out = {"name": item.get("name"), "id": item.get("id"), "size": item.get("size"),
           "webUrl": item.get("webUrl"), "driveId": a.drive_id}
    if a.link:
        st, link = graph("POST", f"{GRAPH}/drives/{a.drive_id}/items/{item['id']}/createLink", tok,
                         body={"type": "view", "scope": a.link})
        if st < 300 and isinstance(link, dict):
            out["shareLink"] = (link.get("link") or {}).get("webUrl")
        else:
            out["shareLinkError"] = f"{st}: {str(link)[:200]}"
    print(json.dumps(out, indent=2))


def build_parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("inspect", help="show how a link would be resolved (no download)")
    i.add_argument("url")
    i.set_defaults(fn=cmd_inspect)
    f = sub.add_parser("fetch", help="download a shared file into the projects directory and ffprobe it")
    f.add_argument("url")
    f.add_argument("--dest", required=True, help="target directory, e.g. <projects dir>/<slug>")
    f.add_argument("--name", help="filename to save as (default: from the server)")
    f.add_argument("--overwrite", action="store_true")
    f.set_defaults(fn=cmd_fetch)
    u = sub.add_parser("push", help="upload a local file to SharePoint/OneDrive via a Graph upload session")
    u.add_argument("file")
    u.add_argument("--drive-id", required=True, help="Graph driveId of the library / OneDrive")
    u.add_argument("--folder-id", help="itemId of the target folder (default: drive root)")
    u.add_argument("--name")
    u.add_argument("--conflict", default="rename", choices=["rename", "replace", "fail"],
                   help="if the name exists (default rename — delivered files are never overwritten)")
    u.add_argument("--link", choices=["organization", "anonymous"],
                   help="also create a view-only sharing link with this scope")
    u.set_defaults(fn=cmd_push)
    return p


if __name__ == "__main__":
    args = build_parser().parse_args()
    args.fn(args)
