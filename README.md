# kiwi-docker

Extract m3u8 and mp4 stream URLs from Kiwi-Stream using a MAL ID.

## Quick Start

```bash
# Start everything
docker-compose up -d

# Get stream URLs
curl http://localhost:8000/streams/1535/1
curl "http://localhost:8000/streams/1535/1?audio=sub&quality=720p"

# Interactive docs
open http://localhost:8000/docs
```

## How it works

```
MAL ID + Episode
    ↓ curl-cffi
mapper.nekostream.site API  →  pahe short URLs
    ↓ curl-cffi + Referer
animixplaycors proxy        →  kwik.cx/f/<id>
    ↓ FlareSolverr (solves Cloudflare)
kwik.cx/f/<id>              →  /e/<id> extracted from JS
    ↓ curl-cffi (NO Cloudflare on /e/)
kwik.cx/e/<id>              →  hash extracted from obfuscated JS
    ↓ build URLs
vault-11.uwucdn.top/mp4/...      ← direct download
vault-11.uwucdn.top/stream/...   ← HLS m3u8 stream
```

## API

| Endpoint | Description |
|----------|-------------|
| `GET /streams/{mal_id}/{episode}` | All qualities |
| `GET /streams/{mal_id}/{episode}?audio=sub` | Sub only |
| `GET /streams/{mal_id}/{episode}?quality=720p` | 720p only |
| `GET /streams/{mal_id}/{episode}?audio=sub&quality=720p` | Sub 720p |
| `GET /health` | Server status |
| `GET /docs` | Swagger UI |

## Response

```json
{
  "mal_id": 1535,
  "episode": 1,
  "cached": false,
  "streams": {
    "sub": {
      "360p":  {"mp4": "https://vault-11...", "m3u8": "https://vault-11..."},
      "720p":  {"mp4": "...", "m3u8": "..."},
      "1080p": {"mp4": "...", "m3u8": "..."}
    },
    "dub": { ... }
  }
}
```

## Docker Image

```bash
docker pull ghcr.io/srtfile/kiwi-docker:latest
docker run -p 8000:8000 -e FLARESOLVERR_URL=http://your-fs:8191/v1 ghcr.io/srtfile/kiwi-docker:latest
```
