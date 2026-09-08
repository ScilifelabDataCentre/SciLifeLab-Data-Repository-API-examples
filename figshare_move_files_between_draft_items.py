#!/usr/bin/env python3
"""
figshare_move_files_between_draft_items.py — move all files from one draft Figshare article to another.

The Figshare API has no server-side "move" operation, so this script
downloads each file from the source article and re-uploads it to the
destination article, then deletes the original.

Usage:
    python3 figshare_move_files_between_draft_items.py --from 33453301 --to 33339309

Flags:
    --from          Source article ID (required)
    --to            Destination article ID (required)
    --dry-run       List files that would be moved without touching anything
    --token         Override token from token.txt / FIGSHARE_TOKEN env var
    --token-file    Path to token file (default: token.txt, next to this script)
    --base-url      API base URL (default: https://api.figshare.com/v2)
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
from pathlib import Path

import requests

DEFAULT_BASE = "https://api.figshare.com/v2"
DEFAULT_TOKEN_FILE = Path(__file__).resolve().parent / "token.txt"


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _load_token(explicit: str | None, token_file: Path) -> str:
    if explicit:
        return explicit.strip()
    env = os.environ.get("FIGSHARE_TOKEN", "").strip()
    if env:
        return env
    if token_file.is_file():
        for line in token_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line
    return ""


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"token {token}"}


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _get(token: str, url: str) -> dict:
    r = requests.get(url, headers=_auth(token), timeout=60)
    r.raise_for_status()
    return r.json()


def list_files(token: str, base: str, article_id: int) -> list[dict]:
    return _get(token, f"{base}/account/articles/{article_id}/files")


def get_file_info(token: str, base: str, article_id: int, file_id: int) -> dict:
    return _get(token, f"{base}/account/articles/{article_id}/files/{file_id}")


# ---------------------------------------------------------------------------
# Move one file
# ---------------------------------------------------------------------------

def move_file(
    token: str,
    base: str,
    src: int,
    dest: int,
    file_info: dict,
    dry_run: bool,
) -> None:
    name = file_info["name"]
    size = file_info["size"]
    file_id = file_info["id"]

    print(f"  {name}  ({size:,} bytes, id={file_id})")

    if dry_run:
        print("    [dry-run] skipping download/upload/delete")
        return

    # ── Step 1: download to a temp file ────────────────────────────────────
    download_url = file_info.get("download_url") or file_info.get("preview_url")
    if not download_url:
        print("    ERROR: no download_url in file info — skipping")
        return

    print("    Downloading...")
    r = requests.get(download_url, headers=_auth(token), stream=True, timeout=300)
    r.raise_for_status()

    md5 = hashlib.md5()
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp_path = Path(tmp.name)
    try:
        with tmp:
            downloaded = 0
            for chunk in r.iter_content(chunk_size=4 * 1024 * 1024):
                tmp.write(chunk)
                md5.update(chunk)
                downloaded += len(chunk)
                pct = downloaded / size * 100 if size else 0
                print(f"\r      {downloaded / 1e9:.2f} GB / {size / 1e9:.2f} GB  ({pct:.1f}%)", end="", flush=True)
        print()
        actual_md5 = md5.hexdigest()
        print(f"    Download complete (md5={actual_md5})")

        # ── Step 2: initiate upload on destination ──────────────────────────
        print("    Initiating upload...", end=" ", flush=True)
        r2 = requests.post(
            f"{base}/account/articles/{dest}/files",
            headers=_auth(token),
            json={"name": name, "size": size, "md5": actual_md5},
            timeout=30,
        )
        if not r2.ok:
            print(f"\n    ERROR {r2.status_code}: {r2.text}")
        r2.raise_for_status()
        location = r2.json()["location"]

        # ── Step 3: get upload URL and new file ID ──────────────────────────
        r3 = requests.get(location, headers=_auth(token), timeout=30)
        r3.raise_for_status()
        file_obj = r3.json()
        upload_url = file_obj["upload_url"]
        new_file_id = file_obj["id"]
        print(f"done (new file_id={new_file_id})")

        # ── Step 4: get upload parts ────────────────────────────────────────
        r4 = requests.get(upload_url, headers=_auth(token), timeout=30)
        r4.raise_for_status()
        parts = r4.json()["parts"]

        # ── Step 5: upload each part ────────────────────────────────────────
        print(f"    Uploading {len(parts)} part(s)...")
        with open(tmp_path, "rb") as fh:
            for part in parts:
                pnum  = part["partNo"]
                start = part["startOffset"]
                end   = part["endOffset"]
                fh.seek(start)
                data = fh.read(end - start + 1)
                r5 = requests.put(
                    f"{upload_url}/{pnum}",
                    headers=_auth(token),
                    data=data,
                    timeout=300,
                )
                r5.raise_for_status()
                print(f"      part {pnum}: {len(data):,} bytes uploaded")

        # ── Step 6: complete the upload ─────────────────────────────────────
        print("    Completing upload...", end=" ", flush=True)
        r6 = requests.post(
            f"{base}/account/articles/{dest}/files/{new_file_id}",
            headers=_auth(token),
            timeout=30,
        )
        r6.raise_for_status()
        print("done")

        # ── Step 7: delete from source ──────────────────────────────────────
        print("    Deleting from source...", end=" ", flush=True)
        r7 = requests.delete(
            f"{base}/account/articles/{src}/files/{file_id}",
            headers=_auth(token),
            timeout=30,
        )
        r7.raise_for_status()
        print("done")
        print(f"    ✓ {name} moved successfully")

    finally:
        tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Move all files from one draft Figshare article to another.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 figshare_move_files_between_draft_items.py --from 33453301 --to 33339309\n"
            "  python3 figshare_move_files_between_draft_items.py --from 33453301 --to 33339309 --dry-run\n"
        ),
    )
    parser.add_argument("--from", dest="src", type=int, required=True, help="Source article ID")
    parser.add_argument("--to", dest="dest", type=int, required=True, help="Destination article ID")
    parser.add_argument("--dry-run", action="store_true", help="List files without moving them")
    parser.add_argument("--token", default=None, help="Personal access token")
    parser.add_argument("--token-file", type=Path, default=DEFAULT_TOKEN_FILE, help=f"Token file path (default: {DEFAULT_TOKEN_FILE})")
    parser.add_argument("--base-url", default=DEFAULT_BASE, help=f"API base URL (default: {DEFAULT_BASE})")

    args = parser.parse_args()

    token = _load_token(args.token, args.token_file)
    if not token:
        sys.exit(
            "No token found. Use --token, set FIGSHARE_TOKEN, or put the token in\n"
            f"  {args.token_file}"
        )

    base = args.base_url.rstrip("/")

    print(f"Source article:      {args.src}")
    print(f"Destination article: {args.dest}")
    if args.dry_run:
        print("Mode:                dry-run (no changes will be made)")
    print()

    # List files on source
    print(f"Fetching file list from article {args.src}...")
    files = list_files(token, base, args.src)

    if not files:
        print("No files found on source article. Nothing to do.")
        return

    print(f"Found {len(files)} file(s):\n")
    for i, f in enumerate(files, 1):
        print(f"  [{i}/{len(files)}]", end=" ")
        # Get full file info (includes download_url)
        file_info = get_file_info(token, base, args.src, f["id"])
        move_file(token, base, args.src, args.dest, file_info, args.dry_run)
        print()

    print("All done.")


if __name__ == "__main__":
    main()
