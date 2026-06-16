#!/usr/bin/env python
"""Upload a built submission zip to the TPC Phase-1 portal.

box.nju.edu.cn ("NJU Box") is a Seafile server, not Box.com. Its anonymous upload
links use a two-step API:

  1. GET  <server>/api/v2.1/upload-links/<token>/upload/?p=<portal path>
          -> {"upload_link": "<seafhttp url>"}
  2. POST <seafhttp url>?ret-json=1   (multipart/form-data: parent_dir=<portal path>, file=<zip>)

The seafhttp upload token from step 1 is short-lived, so it is fetched immediately
before uploading. Pure stdlib, matching assemble_submission.py.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PORTAL = "https://box.nju.edu.cn/u/d/998d62d9bd8747ea8659/"


def latest_zip():
    """Path of the highest-version submissions/fabiundstefan_v<N>.zip, or None."""
    sub = os.path.join(ROOT, "submissions")
    if not os.path.isdir(sub):
        return None
    best = None
    for fname in os.listdir(sub):
        m = re.fullmatch(r"fabiundstefan_v(\d+)\.zip", fname)
        if m:
            n = int(m.group(1))
            if best is None or n > best[0]:
                best = (n, os.path.join(sub, fname))
    return best[1] if best else None


def get_upload_target(portal_url):
    """Resolve a portal /u/d/<token>/ link to a fresh seafhttp URL and parent dir."""
    base = re.match(r"https?://[^/]+", portal_url).group(0)
    m = re.search(r"/u/d/([0-9A-Za-z]+)", portal_url)
    if not m:
        raise SystemExit("no /u/d/<token>/ upload-link token in URL: {}".format(portal_url))

    with urllib.request.urlopen(portal_url, timeout=30) as r:
        page = r.read().decode("utf-8", "replace")
    path_match = re.search(r'\bpath:\s*"([^"]+)"', page)
    if not path_match:
        raise SystemExit("no upload path found in portal page: {}".format(portal_url))
    parent_dir = path_match.group(1)

    api = "{}/api/v2.1/upload-links/{}/upload/?{}".format(
        base, m.group(1), urllib.parse.urlencode({"p": parent_dir})
    )
    with urllib.request.urlopen(api, timeout=30) as r:
        return json.load(r)["upload_link"], parent_dir


def encode_multipart(zip_path, parent_dir):
    """multipart/form-data body: parent_dir part, then the file part."""
    boundary = uuid.uuid4().hex
    with open(zip_path, "rb") as f:
        content = f.read()
    head = "\r\n".join([
        "--" + boundary,
        'Content-Disposition: form-data; name="parent_dir"',
        "",
        parent_dir,
        "--" + boundary,
        'Content-Disposition: form-data; name="file"; filename="{}"'.format(os.path.basename(zip_path)),
        "Content-Type: application/zip",
        "",
        "",
    ]).encode()
    tail = ("\r\n--" + boundary + "--\r\n").encode()
    return boundary, head + content + tail


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--url", default=os.environ.get("TPC_SUBMIT_URL", DEFAULT_PORTAL),
                    help="portal upload-link URL (default: the TPC Phase-1 portal)")
    ap.add_argument("--version", help="upload submissions/fabiundstefan_v<N>.zip")
    ap.add_argument("--zip", help="upload this exact zip path (overrides --version)")
    ap.add_argument("--dry-run", action="store_true",
                    help="resolve the link and show the target, but do not upload")
    args = ap.parse_args()

    if args.zip:
        zip_path = args.zip
    elif args.version:
        if not re.fullmatch(r"v\d+", args.version):
            ap.error("version must look like v<number>, for example v6")
        zip_path = os.path.join(ROOT, "submissions", "fabiundstefan_{}.zip".format(args.version))
    else:
        zip_path = latest_zip()
        if zip_path is None:
            ap.error("no submissions/fabiundstefan_v*.zip found; run `make submission` first")
    if not os.path.isfile(zip_path):
        ap.error("zip not found: {} (run `make submission`)".format(zip_path))

    upload_link, parent_dir = get_upload_target(args.url)
    size = os.path.getsize(zip_path)
    print("portal:    {}".format(args.url))
    print("parent:    {}".format(parent_dir))
    print("upload to: {}".format(upload_link))
    print("zip:       {} ({:,} bytes)".format(zip_path, size))
    if args.dry_run:
        print("dry run: not uploading")
        return 0

    boundary, body = encode_multipart(zip_path, parent_dir)
    req = urllib.request.Request(
        upload_link + "?ret-json=1",
        data=body,
        method="POST",
        headers={
            "Content-Type": "multipart/form-data; boundary=" + boundary,
            "Referer": args.url,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            resp = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        sys.stderr.write(
            "upload failed: HTTP {}\n{}\n".format(e.code, e.read().decode("utf-8", "replace"))
        )
        return 1
    print("uploaded {} -> {}".format(os.path.basename(zip_path), resp))
    return 0


if __name__ == "__main__":
    sys.exit(main())
