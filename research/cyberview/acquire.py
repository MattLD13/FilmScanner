"""Fetch and fingerprint the PF1800 AFL package linked by Pacific Image.

This only downloads bytes and records metadata. It never runs or extracts the
installer. Keep resulting files under .artifacts (ignored by Git).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SUPPORT_URL = "https://www.scanace.com/product/all-models-driver-download-user-guide"
DRIVE_ID = "1ZO2fiBFpS6v6B5OnsnYTpDq5Qqr7T-yM"
EXPECTED = "PrimeFilm 1800AFL_Windows_SF_ENG_1.3.exe"
DEST = Path(__file__).parent / ".artifacts" / "official-pf1800afl-v1.3"


class TracingRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self) -> None:
        super().__init__()
        self.redirects: list[dict[str, object]] = []

    def redirect_request(self, request, response, code, message, headers, newurl):
        self.redirects.append({"status": code, "from": request.full_url, "to": newurl})
        return super().redirect_request(request, response, code, message, headers, newurl)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def get(url: str) -> tuple[bytes, dict[str, object]]:
    redirects = TracingRedirectHandler()
    opener = urllib.request.build_opener(redirects)
    request = urllib.request.Request(url, headers={"User-Agent": "FRAME research acquisition/1.0"})
    with opener.open(request, timeout=90) as response:
        body = response.read()
        safe_headers = {
            k: v for k, v in response.headers.items()
            if k.lower() not in {"set-cookie", "authorization", "proxy-authorization"}
        }
        return body, {
            "status": response.status,
            "requested_url": url,
            "final_url": response.geturl(),
            "redirects": redirects.redirects,
            "headers": safe_headers,
            "bytes": len(body),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="fetch the manufacturer-linked file")
    parser.add_argument("--file", type=Path, help="fingerprint an already acquired file")
    args = parser.parse_args()
    DEST.mkdir(parents=True, exist_ok=True)
    path = args.file or (DEST / EXPECTED.replace(" ", "_"))
    record: dict[str, object] = {
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
        "manufacturer_support_page": SUPPORT_URL,
        "manufacturer_linked_drive_file_id": DRIVE_ID,
        "manufacturer_linked_filename": EXPECTED,
        "execution_policy": "download/fingerprint only; no execution or extraction",
    }
    if args.download:
        page, page_meta = get(SUPPORT_URL)
        if b"PrimeFilm 1800AFL" not in page or DRIVE_ID.encode() not in page:
            raise SystemExit("The current manufacturer page no longer exposes the expected model/file ID.")
        record["support_page_response"] = page_meta
        first_url = "https://drive.google.com/uc?export=download&id=" + DRIVE_ID
        interstitial, interstitial_meta = get(first_url)
        record["drive_interstitial_response"] = interstitial_meta
        form_uuid = re.search(rb'name="uuid" value="([^"]+)"', interstitial)
        if not form_uuid or b"Virus scan warning" not in interstitial:
            raise SystemExit("Unexpected Drive response; refusing to guess a confirmation flow.")
        query = urllib.parse.urlencode({"id": DRIVE_ID, "export": "download", "confirm": "t", "uuid": form_uuid.group(1).decode()})
        data, download_meta = get("https://drive.usercontent.google.com/download?" + query)
        if not data.startswith(b"MZ"):
            raise SystemExit("Downloaded response is not a PE executable; not saving it as the expected installer.")
        path.write_bytes(data)
        record["download_response"] = download_meta
    content = path.read_bytes()
    record["file"] = str(path.resolve())
    record["bytes"] = len(content)
    record["sha256"] = sha256(content)
    (DEST / "acquisition.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
