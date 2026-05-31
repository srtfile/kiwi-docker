"""
Kiwi Stream Extractor
=====================
Extracts mp4 + m3u8 URLs from Kiwi-Stream using a MAL ID + episode.

Flow:
  1. mapper.nekostream.site API  →  pahe short URLs
  2. curl-cffi proxy request     →  kwik.cx/f/<id>
  3. FlareSolverr GET /f/<id>    →  intercept /e/<id> from page JS
  4. curl-cffi GET /e/<id>       →  extract hash (NO Cloudflare on /e/)
  5. Build mp4 + m3u8 from hash

Requirements: pip install curl-cffi requests
"""

import re, sys, time, json, argparse
import requests
from curl_cffi import requests as cffi_requests

MAPPER_API       = "https://mapper.nekostream.site/api/mal/{mal_id}/{episode}/{timestamp}"
PROXY_URL        = "https://raspy-bread-20dd.animixplaycors.workers.dev/{code}"
FLARESOLVERR_URL = "http://localhost:8191/v1"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "cross-site",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "user-agent": UA,
}


# ── FlareSolverr ──────────────────────────────────────────────────────────────

def fs_create_session():
    r = requests.post(FLARESOLVERR_URL, json={"cmd": "sessions.create"}, timeout=30)
    return r.json()["session"]

def fs_destroy_session(sid):
    requests.post(FLARESOLVERR_URL, json={"cmd": "sessions.destroy", "session": sid}, timeout=10)

def fs_get(url, session_id, max_timeout=60000):
    payload = {"cmd": "request.get", "url": url, "maxTimeout": max_timeout, "session": session_id}
    r = requests.post(FLARESOLVERR_URL, json=payload, timeout=max_timeout // 1000 + 15)
    data = r.json()
    if data.get("status") != "ok":
        raise RuntimeError(f"FlareSolverr: {data.get('message', data)}")
    sol = data["solution"]
    cookies = {c["name"]: c["value"] for c in sol.get("cookies", [])}
    return sol["url"], sol["response"], cookies

def check_flaresolverr():
    try:
        return requests.get(FLARESOLVERR_URL.replace("/v1", ""), timeout=5).status_code == 200
    except Exception:
        return False


# ── Step 1: Mapper API ────────────────────────────────────────────────────────

def call_mapper(mal_id, episode, timestamp):
    url = MAPPER_API.format(mal_id=mal_id, episode=episode, timestamp=timestamp)
    r = cffi_requests.get(url, headers={"User-Agent": UA},
                          impersonate="chrome131", verify=False, timeout=20)
    return json.loads(r.text)


# ── Step 2: pahe → kwik.cx/f/<id> ────────────────────────────────────────────

def get_kwik_f_url(pahe_url, verbose=True):
    code = pahe_url.rstrip("/").split("/")[-1]
    proxy = PROXY_URL.format(code=code)
    if verbose:
        print(f"    proxy → {proxy}")
    r = cffi_requests.get(proxy, headers={**HEADERS, "referer": "https://pahe.nekostream.site/"},
                          impersonate="chrome131", verify=False, timeout=20, allow_redirects=True)
    if "kwik.cx" in r.url:
        url = r.url
    else:
        m = re.search(r'https?://kwik\.cx/[^\s\'"<>]+', r.text)
        if not m:
            raise RuntimeError(f"No kwik URL. Final: {r.url}")
        url = m.group(0)
    return re.sub(r'kwik\.cx/[ed]/', 'kwik.cx/f/', url)


# ── Step 3: FlareSolverr GET /f/ → /e/ ID ────────────────────────────────────

def get_e_id(kwik_f_url, session_id, verbose=True):
    """
    FlareSolverr loads /f/ page (solves CF).
    The page JS sets iframe src = kwik.cx/e/<id>
    We find that /e/ ID in the rendered HTML.
    """
    if verbose:
        print(f"    FlareSolverr → {kwik_f_url}")
    _, body, _ = fs_get(kwik_f_url, session_id)

    for pattern in [
        r'kwik\.cx/e/([a-zA-Z0-9]+)',
        r'src=["\']https://kwik\.cx/e/([a-zA-Z0-9]+)',
        r'/e/([a-zA-Z0-9]{8,})',
    ]:
        m = re.search(pattern, body)
        if m:
            return m.group(1)

    raise RuntimeError(f"/e/ ID not found. Body[:300]: {body[:300]}")


# ── Step 4: GET /e/<id> → hash (NO Cloudflare) ───────────────────────────────

def get_urls_from_e(e_id, verbose=True):
    """
    GET kwik.cx/e/<id> — NO Cloudflare protection.
    Extract vault hash from obfuscated JS string array:
      Pattern: <hash>|06|stream|top|uwucdn|vault|https
    """
    url = f"https://kwik.cx/e/{e_id}"
    if verbose:
        print(f"    /e/ (no CF) → {url}")

    r = cffi_requests.get(url, headers={"User-Agent": UA, "Referer": "https://kwik.cx/"},
                          impersonate="chrome131", verify=False, timeout=20)

    if r.status_code != 200:
        raise RuntimeError(f"/e/ returned {r.status_code}")

    m = re.search(r'([a-f0-9]{60,})\|06\|stream\|top\|uwucdn\|vault\|https', r.text)
    if not m:
        raise RuntimeError("Hash not found in /e/ page")

    h = m.group(1)
    vn_match = re.search(r'vault-(\d+)\.uwucdn\.top', r.text)
    vn = vn_match.group(1) if vn_match else "11"

    return (
        f"https://vault-{vn}.uwucdn.top/mp4/11/06/{h}",
        f"https://vault-{vn}.uwucdn.top/stream/11/06/{h}/uwu.m3u8"
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def get_stream_urls(mal_id, episode, timestamp=None, verbose=True):
    if timestamp is None:
        timestamp = int(time.time())

    if not check_flaresolverr():
        raise RuntimeError(
            "FlareSolverr not running!\n"
            "Start: docker run -d --name flaresolverr -p 8191:8191 "
            "ghcr.io/flaresolverr/flaresolverr:latest"
        )

    sid = fs_create_session()
    if verbose:
        print(f"[FS] Session: {sid}")

    try:
        if verbose:
            print(f"\n[1] Mapper API: mal={mal_id} ep={episode}")

        data = call_mapper(mal_id, episode, timestamp)
        kiwi = data.get("Kiwi-Stream")
        if not kiwi:
            raise RuntimeError("No Kiwi-Stream in API response")

        results = {}

        for audio in ("sub", "dub"):
            if audio not in kiwi:
                continue
            results[audio] = {}

            for qkey, pahe_url in kiwi[audio].get("download", {}).items():
                quality = qkey.replace("Kiwi-Stream-", "")
                if verbose:
                    print(f"\n[2] {audio} {quality}: {pahe_url}")

                try:
                    kwik_f = get_kwik_f_url(pahe_url, verbose)
                    if verbose:
                        print(f"    kwik /f/: {kwik_f}")

                    e_id = get_e_id(kwik_f, sid, verbose)
                    if verbose:
                        print(f"    /e/ ID: {e_id}")

                    mp4, m3u8 = get_urls_from_e(e_id, verbose)
                    if verbose:
                        print(f"    mp4:  {mp4}")
                        print(f"    m3u8: {m3u8}")

                    results[audio][quality] = {"mp4": mp4, "m3u8": m3u8}

                except Exception as e:
                    if verbose:
                        print(f"    ERROR: {e}")
                    results[audio][quality] = {"error": str(e)}

    finally:
        fs_destroy_session(sid)
        if verbose:
            print("\n[FS] Session destroyed")

    return results


def main():
    p = argparse.ArgumentParser(description="Kiwi Stream Extractor")
    p.add_argument("--mal-id",    type=int, default=1535)
    p.add_argument("--episode",   type=int, default=1)
    p.add_argument("--timestamp", type=int, default=None)
    p.add_argument("--json",      action="store_true")
    p.add_argument("--fs-url",    default="http://localhost:8191/v1",
                   help="FlareSolverr URL")
    args = p.parse_args()

    global FLARESOLVERR_URL
    FLARESOLVERR_URL = args.fs_url

    verbose = not args.json
    try:
        urls = get_stream_urls(args.mal_id, args.episode, args.timestamp, verbose)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(urls, indent=2))
    else:
        print("\n" + "="*60)
        for audio, qs in urls.items():
            print(f"\n[{audio.upper()}]")
            for q, links in qs.items():
                print(f"  {q}:")
                if "error" in links:
                    print(f"    ERROR: {links['error']}")
                else:
                    print(f"    mp4:  {links['mp4']}")
                    print(f"    m3u8: {links['m3u8']}")

if __name__ == "__main__":
    main()
