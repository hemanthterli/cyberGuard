import yt_dlp
import webvtt
import os


def get_youtube_captions(url):

    out = "subs"
    os.makedirs(out, exist_ok=True)

    ydl_opts = {
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en"],
        "outtmpl": f"{out}/%(id)s.%(ext)s",
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        vid = info["id"]

    file = f"{out}/{vid}.en.vtt"

    text = ""

    for c in webvtt.read(file):
        text += c.text + " "

    return text


url = "https://www.youtube.com/shorts/wGBbCAbLjus"

print(get_youtube_captions(url))