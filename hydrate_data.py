"""
Hydrate PowerPoint benchmark data: download source pptx files, then capture
PPT-Online-mutated copies + slide-image zips.

Stage 1 (optional, when --urls-file is given):
  Download every URL listed in the file (one per line, '#' comments allowed)
  into --local-folder.

Stage 2 (always): for every ``x.pptx`` in --local-folder:
  1. Uploads it to OneDrive at ``<onedrive-folder>/x.pptx``
  2. Creates a shareable edit link
  3. Opens it in PowerPoint Online in a local headless Chromium (Playwright)
  4. Downloads the slide images (zip) via the web app
  5. Downloads the (mutated) pptx via the web app's "Download a Copy"

Both outputs are written next to each other in --output-dir (default
``data/files/PowerPoint``) as ``x.pptx`` and ``x.zip``.

The pptx is NOT copied from the local source: PPT Online mutates the file when
it opens it, and we deliberately want to capture that mutation.

This runs Playwright directly on the host (no screenenv Sandbox / container);
the anonymous shareable edit link is opened without sign-in.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from ppteval.utils.onedrive import OneDriveClient
from ppteval.utils.powerpoint import (
    download_powerpoint_as_images_sync,
    download_powerpoint_as_pptx_sync,
    ensure_classic_ribbon_always_show,
)


@dataclass
class LocalSandbox:
    """Shim exposing the one attribute the powerpoint helpers need."""
    chromium_context: Any


# ---------------------------------------------------------------------------
# Stage 1: download source pptx files from URLs.
# ---------------------------------------------------------------------------

def read_file_urls(file_path: str) -> list[str]:
    """Read URLs from a text file, one per line (blank/'#' lines ignored)."""
    with open(file_path, "r", encoding="utf-8") as f:
        return [
            line.strip()
            for line in f
            if line.strip() and not line.startswith("#")
        ]


def extract_filename_from_url(url: str) -> str:
    """Extract the filename from a URL; ensure .pptx suffix."""
    parsed = urlparse(url)
    filename = unquote(os.path.basename(parsed.path))
    if not filename or filename == "/":
        parts = [p for p in parsed.path.split("/") if p]
        if parts:
            filename = unquote(parts[-1])
    if not filename.lower().endswith(".pptx"):
        filename += ".pptx"
    return filename


def download_file(url: str, filename: str, download_dir: str) -> bool:
    """Stream-download a single URL to ``download_dir/filename``. Skips if present."""
    os.makedirs(download_dir, exist_ok=True)
    file_path = os.path.join(download_dir, filename)
    if file_path.endswith(".pptx.pptx"):
        file_path = file_path[:-5]
    if os.path.exists(file_path):
        print(f"  ✓ {filename} already exists, skipping")
        return True
    try:
        print(f"  downloading {filename}...")
        response = requests.get(url, stream=True, timeout=60)
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0))
        done = 0
        with open(file_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if total > 0:
                    print(f"\r    progress: {done / total * 100:.1f}%",
                          end="", flush=True)
        print(f"\n  ✓ downloaded {filename}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"\n  ✗ failed to download {filename}: {e}")
        return False


def _with_retries(label: str, fn, attempts: int = 8, base_delay: float = 3.0):
    """Call fn() with simple exponential-backoff retries on any exception."""
    last_exc = None
    for i in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if i == attempts:
                break
            delay = min(base_delay * (2 ** (i - 1)), 30.0)
            print(f"  [retry] {label} attempt {i}/{attempts} failed: {e}; "
                  f"sleeping {delay:.1f}s")
            time.sleep(delay)
    raise last_exc  # type: ignore[misc]


def _wait_for_wacframe(page, max_wait_s: int = 300, poll_s: float = 2.0) -> bool:
    """Block until a WacFrame_PowerPoint frame appears."""
    deadline = time.time() + max_wait_s
    while time.time() < deadline:
        try:
            for f in page.frames:
                name = ""
                try:
                    name = f.name or ""
                except Exception:
                    pass
                if "WacFrame_PowerPoint" in str(name):
                    time.sleep(3)  # let the frame settle
                    return True
        except Exception:
            pass
        time.sleep(poll_s)
    return False


def process_file(
    local_path: Path,
    onedrive_folder: str,
    output_dir: Path,
    onedrive_client: OneDriveClient,
    browser,
    skip_existing: bool,
    overwrite: bool,
) -> bool:
    name = local_path.stem
    out_pptx = output_dir / f"{name}.pptx"
    out_zip = output_dir / f"{name}.zip"

    if skip_existing and out_pptx.exists() and out_zip.exists():
        print(f"[skip] {name}: already have {out_pptx.name} and {out_zip.name}")
        return True

    # Safety: never silently clobber an existing output file.
    for existing in (out_pptx, out_zip):
        if existing.exists() and not overwrite:
            print(
                f"  [error] refusing to overwrite existing file {existing} "
                f"(pass --overwrite to allow)"
            )
            return False

    remote_path = f"{onedrive_folder.rstrip('/')}/{local_path.name}"
    print(f"\n=== {local_path.name} ===")
    context = None
    try:
        print(f"  upload   -> {remote_path}")
        _with_retries(
            "upload",
            lambda: onedrive_client.upload_file(
                str(local_path), remote_path, set_public=True
            ),
        )

        print("  link     -> getting edit link")
        edit_link = _with_retries(
            "get_edit_link",
            lambda: onedrive_client.get_edit_link(remote_path),
        )
        if not edit_link:
            print(f"  [error] no edit link returned for {remote_path}")
            return False
        print(f"  link     -> {edit_link[:80]}...")

        context = browser.new_context(
            accept_downloads=True,
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()

        print(f"  open     -> {edit_link[:80]}...")
        page.goto(edit_link, wait_until="load", timeout=180_000)

        print("  wait     -> WacFrame_PowerPoint")
        if not _wait_for_wacframe(page):
            print("  [error] WacFrame never appeared")
            # Dump diagnostics so we can see what's on the page.
            try:
                print(f"  [diag] url={page.url}")
                print(f"  [diag] title={page.title()}")
                frame_names = []
                for f in page.frames:
                    try:
                        frame_names.append(f.name or "<no-name>")
                    except Exception:
                        frame_names.append("<error>")
                print(f"  [diag] frames={frame_names}")
                debug_png = output_dir / f"_debug_wacframe_{name}.png"
                page.screenshot(path=str(debug_png), full_page=True)
                print(f"  [diag] screenshot -> {debug_png}")
            except Exception as diag_e:
                print(f"  [diag] dump failed: {diag_e}")
            return False

        sandbox = LocalSandbox(chromium_context=context)

        print("  ribbon   -> ensure classic ribbon / always show")
        try:
            ensure_classic_ribbon_always_show(sandbox=sandbox, verbose=False)
        except Exception as e:
            print(f"  [warn] ribbon setup failed: {e}")

        # 4. Slide images zip via web app.
        print("  images   -> downloading slide images zip")
        tmp_img_dir = output_dir / "_tmp_images"
        tmp_img_dir.mkdir(parents=True, exist_ok=True)
        zip_path = download_powerpoint_as_images_sync(
            sandbox=sandbox,
            download_dir=str(tmp_img_dir),
            verbose=False,
        )
        if not zip_path or not Path(zip_path).exists():
            print("  [error] image zip download failed")
            return False
        if out_zip.exists():
            out_zip.unlink()
        shutil.move(zip_path, out_zip)
        print(f"  images   -> {out_zip}")

        # 5. Mutated pptx via web app (Download a Copy).
        print("  pptx     -> downloading mutated pptx from web app")
        tmp_pptx_dir = output_dir / "_tmp_pptx"
        tmp_pptx_dir.mkdir(parents=True, exist_ok=True)
        dl_path = download_powerpoint_as_pptx_sync(
            sandbox=sandbox,
            download_dir=str(tmp_pptx_dir),
            verbose=True,
        )
        if not dl_path or not Path(dl_path).exists():
            print("  [error] pptx download failed")
            return False
        if out_pptx.exists():
            out_pptx.unlink()
        shutil.move(dl_path, out_pptx)
        print(f"  pptx     -> {out_pptx}")

        return True

    except Exception as e:
        print(f"  [error] {e}")
        traceback.print_exc()
        return False
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        for tmp in (output_dir / "_tmp_images", output_dir / "_tmp_pptx"):
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--local-folder",
        required=True,
        type=Path,
        help="Local folder containing .pptx files to process. When "
             "--urls-file is given, files are downloaded into this folder first.",
    )
    parser.add_argument(
        "--urls-file",
        type=Path,
        default=None,
        help="Optional path to a text file with one PowerPoint URL per line "
             "(e.g. files.txt). Files are downloaded into --local-folder before "
             "the capture pipeline runs.",
    )
    parser.add_argument(
        "--onedrive-folder",
        default="/PPTEval",
        help="OneDrive folder (relative to drive root) to upload files into.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/files/PowerPoint"),
        help="Local folder for <name>.pptx and <name>.zip outputs.",
    )
    parser.add_argument(
        "--client-id",
        default=os.environ.get("CLIENT_ID"),
        help="Entra app client id (defaults to $CLIENT_ID).",
    )
    parser.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run Chromium headless (default: true).",
    )
    parser.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="Re-process files even when both outputs already exist.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow overwriting existing <name>.pptx / <name>.zip outputs.",
    )
    parser.add_argument(
        "--allow-data-dir",
        action="store_true",
        help="Allow writing under a 'data/' directory (refused by default to "
             "protect curated datasets).",
    )
    parser.add_argument(
        "--cleanup-local-folder",
        action="store_true",
        help="After processing, delete --local-folder (useful when it's a "
             "throwaway temp folder populated by --urls-file).",
    )
    args = parser.parse_args()

    # Safety: refuse to write into a 'data/' directory unless explicitly allowed.
    try:
        resolved_out = args.output_dir.resolve()
    except Exception:
        resolved_out = args.output_dir
    if not args.allow_data_dir and any(
        part.lower() == "data" for part in resolved_out.parts
    ):
        print(
            f"error: --output-dir {args.output_dir} is under a 'data/' folder. "
            "Pass --allow-data-dir to confirm you want to write there.",
            file=sys.stderr,
        )
        return 2

    if not args.client_id:
        print("error: --client-id or env CLIENT_ID is required", file=sys.stderr)
        return 2

    # Optionally download source pptx files into --local-folder first.
    if args.urls_file is not None:
        if not args.urls_file.is_file():
            print(
                f"error: --urls-file {args.urls_file} not found",
                file=sys.stderr,
            )
            return 2
        args.local_folder.mkdir(parents=True, exist_ok=True)
        urls = read_file_urls(str(args.urls_file))
        print(
            f"Downloading {len(urls)} file(s) from {args.urls_file} "
            f"into {args.local_folder}"
        )
        n_dl_ok = 0
        n_dl_fail = 0
        for i, url in enumerate(urls, 1):
            filename = extract_filename_from_url(url)
            print(f"[{i}/{len(urls)}] {filename}")
            if download_file(url, filename, download_dir=str(args.local_folder)):
                n_dl_ok += 1
            else:
                n_dl_fail += 1
        print(f"Download summary: ok={n_dl_ok} fail={n_dl_fail}")
        if n_dl_ok == 0:
            print("error: no files downloaded; aborting", file=sys.stderr)
            return 1

    if not args.local_folder.is_dir():
        print(
            f"error: --local-folder {args.local_folder} is not a directory",
            file=sys.stderr,
        )
        return 2

    args.output_dir.mkdir(parents=True, exist_ok=True)

    pptx_files = sorted(
        p for p in args.local_folder.iterdir() if p.suffix.lower() == ".pptx"
    )
    if not pptx_files:
        print(f"No .pptx files found in {args.local_folder}")
        return 0

    print(f"Found {len(pptx_files)} pptx file(s) to process.")
    print(f"OneDrive folder: {args.onedrive_folder}")
    print(f"Output dir:      {args.output_dir}")

    onedrive_client = OneDriveClient(client_id=args.client_id)

    n_ok = 0
    n_fail = 0
    failures: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        try:
            for f in pptx_files:
                ok = process_file(
                    local_path=f,
                    onedrive_folder=args.onedrive_folder,
                    output_dir=args.output_dir,
                    onedrive_client=onedrive_client,
                    browser=browser,
                    skip_existing=not args.no_skip_existing,
                    overwrite=args.overwrite,
                )
                if ok:
                    n_ok += 1
                else:
                    n_fail += 1
                    failures.append(f.name)
        finally:
            try:
                browser.close()
            except Exception:
                pass

    print(f"\nDone. ok={n_ok} fail={n_fail}")
    if failures:
        print("Failed files:")
        for f in failures:
            print(f"  - {f}")

    if args.cleanup_local_folder:
        try:
            shutil.rmtree(args.local_folder)
            print(f"Cleaned up {args.local_folder}")
        except Exception as e:
            print(f"warning: failed to clean up {args.local_folder}: {e}",
                  file=sys.stderr)

    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
