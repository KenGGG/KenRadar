"""Check whether a public Bilibili video's selected part can be downloaded."""

import re
from urllib.parse import parse_qs, urlsplit

import requests


def probe_download(url: str) -> dict:
    parsed = urlsplit(url)
    identity = re.fullmatch(r"/video/(BV[A-Za-z0-9]{10}|av[1-9][0-9]*)/?", parsed.path)
    if (parsed.scheme != "https" or parsed.netloc not in {"www.bilibili.com", "bilibili.com"}
            or not identity):
        raise ValueError("请填写 B 站完整视频链接（BV 或 av）")
    part = parse_qs(parsed.query).get("p", ["1"])[0]
    if not re.fullmatch(r"[1-9][0-9]{0,5}", part):
        raise ValueError("分 P 编号必须是正整数")
    part = int(part)
    video_id = identity[1]
    params = {"bvid": video_id} if video_id.startswith("BV") else {"aid": video_id[2:]}
    with requests.Session() as session:
        session.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"})

        def get_data(endpoint: str, query: dict) -> dict:
            with session.get("https://api.bilibili.com" + endpoint, params=query,
                             timeout=(5, 12), allow_redirects=False) as response:
                if response.status_code != 200:
                    raise RuntimeError(f"BILIBILI_HTTP_{response.status_code}")
                body = response.json()
                if body.get("code") != 0 or not isinstance(body.get("data"), dict):
                    raise RuntimeError(f"BILIBILI_API_{body.get('code')}")
                return body["data"]

        details = get_data("/x/web-interface/view", params)
        pages = details.get("pages") or []
        page = next((entry for entry in pages if entry.get("page") == part), None)
        if not page or not page.get("cid"):
            raise ValueError(f"找不到第 {part} 个分 P")
        streams = get_data("/x/player/playurl", {**params, "cid": page["cid"], "qn": 64, "fnval": 1})
        segments = streams.get("durl") or []
        result = {"platform": "bilibili", "video_id": details.get("bvid") or video_id,
                  "title": details.get("title"), "part": part, "part_count": len(pages),
                  "segments": len(segments), "downloadable": False}
        for segment in segments:
            for media_url in [segment.get("url"), *(segment.get("backup_url") or [])]:
                if not media_url:
                    continue
                media = urlsplit(media_url)
                if (media.scheme != "https" or media.username is not None or media.port not in (None, 443)
                        or not (media.hostname or "").endswith((".bilivideo.com", ".bilivideo.cn", ".biliapi.net"))):
                    continue
                try:
                    with session.get(media_url, headers={"Range": "bytes=0-0"}, stream=True,
                                     timeout=(5, 8), allow_redirects=False) as response:
                        if response.status_code in (200, 206) and next(response.iter_content(1), b""):
                            break
                except requests.RequestException:
                    continue
            else:
                return result | {"reason": "BILIBILI_MEDIA_UNAVAILABLE"}
        return result | ({"downloadable": True} if segments else {"reason": "BILIBILI_NO_PROGRESSIVE_STREAM"})
