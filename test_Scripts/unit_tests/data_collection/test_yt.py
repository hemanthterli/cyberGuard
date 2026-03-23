from urllib.parse import parse_qs, urlparse

from youtube_transcript_api import YouTubeTranscriptApi


def extract_video_id(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if "youtu.be" in host:
        return parsed.path.lstrip("/")
    if "youtube.com" in host:
        if parsed.path == "/watch":
            return parse_qs(parsed.query).get("v", [""])[0]
        if parsed.path.startswith("/shorts/"):
            parts = parsed.path.split("/")
            return parts[2] if len(parts) > 2 else ""
        if parsed.path.startswith("/embed/"):
            parts = parsed.path.split("/")
            return parts[2] if len(parts) > 2 else ""
    return ""


def get_youtube_transcript(url: str) -> str:
    video_id = extract_video_id(url)
    api = YouTubeTranscriptApi()
    transcript = api.fetch(video_id)
    data = transcript.to_raw_data()
    return " ".join([t["text"] for t in data if t.get("text")])


url = "https://www.youtube.com/shorts/wGBbCAbLjus"

print(get_youtube_transcript(url))
