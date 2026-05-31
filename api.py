"""
Kiwi Stream REST API
====================
Run: uvicorn api:app --host 0.0.0.0 --port 8000

Endpoints:
  GET /                          → homepage
  GET /health                    → status
  GET /streams/{mal_id}/{episode}
  GET /streams/{mal_id}/{episode}?audio=sub&quality=720p
"""

import time
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import uvicorn

from extractor import get_stream_urls, check_flaresolverr, FLARESOLVERR_URL
import os

app = FastAPI(
    title="Kiwi Stream API",
    description="Extract m3u8 and mp4 URLs from Kiwi-Stream using MAL ID",
    version="2.0.0",
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

_cache: dict = {}
CACHE_TTL = 3600  # 1 hour


@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <html><head><title>Kiwi Stream API</title></head>
    <body style="font-family:monospace;padding:40px;background:#111;color:#eee">
    <h1>🎬 Kiwi Stream API v2</h1>
    <h3>Endpoints:</h3>
    <ul>
      <li><a href="/docs" style="color:#4af">/docs</a> — Swagger UI</li>
      <li><a href="/health" style="color:#4af">/health</a> — Status</li>
      <li><a href="/streams/1535/1" style="color:#4af">/streams/{mal_id}/{episode}</a></li>
      <li><a href="/streams/1535/1?audio=sub&quality=720p" style="color:#4af">/streams/1535/1?audio=sub&quality=720p</a></li>
    </ul>
    <h3>How it works:</h3>
    <pre style="background:#222;padding:20px;border-radius:8px">
1. mapper.nekostream.site API  →  pahe short URLs
2. curl-cffi proxy             →  kwik.cx/f/&lt;id&gt;
3. FlareSolverr GET /f/        →  extract /e/&lt;id&gt; from JS
4. curl-cffi GET /e/           →  extract hash (NO Cloudflare)
5. Build mp4 + m3u8 URLs
    </pre>
    </body></html>
    """


@app.get("/health")
def health():
    fs_ok = check_flaresolverr()
    return {
        "status": "ok" if fs_ok else "degraded",
        "flaresolverr": "running" if fs_ok else "not running",
        "cache_entries": len(_cache),
    }


@app.get("/streams/{mal_id}/{episode}")
def get_streams(
    mal_id: int,
    episode: int,
    audio: Optional[str] = Query(None, description="'sub' or 'dub'"),
    quality: Optional[str] = Query(None, description="'360p', '720p', or '1080p'"),
):
    cache_key = f"{mal_id}:{episode}"
    now = time.time()

    if cache_key in _cache:
        result, cached_at = _cache[cache_key]
        if now - cached_at < CACHE_TTL:
            return _build(mal_id, episode, result, audio, quality, cached=True,
                          age=int(now - cached_at))

    try:
        result = get_stream_urls(mal_id, episode, verbose=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    _cache[cache_key] = (result, now)
    return _build(mal_id, episode, result, audio, quality, cached=False, age=0)


def _build(mal_id, episode, result, audio, quality, cached, age):
    streams = result

    if audio:
        audio = audio.lower()
        if audio not in streams:
            raise HTTPException(404, f"Audio '{audio}' not found. Options: {list(streams.keys())}")
        streams = {audio: streams[audio]}

    if quality:
        filtered = {}
        for a, qs in streams.items():
            if quality not in qs:
                raise HTTPException(404, f"Quality '{quality}' not found. Options: {list(qs.keys())}")
            filtered[a] = {quality: qs[quality]}
        streams = filtered

    return {
        "mal_id": mal_id,
        "episode": episode,
        "cached": cached,
        "cache_age_seconds": age,
        "streams": streams,
    }


if __name__ == "__main__":
    import os
    fs_url = os.environ.get("FLARESOLVERR_URL", "http://localhost:8191/v1")
    import extractor
    extractor.FLARESOLVERR_URL = fs_url
    print(f"FlareSolverr: {fs_url}")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
