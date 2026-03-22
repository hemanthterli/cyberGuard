# import os
# import requests
# import numpy as np

# from PIL import Image
# import cv2

# import easyocr

# from faster_whisper import WhisperModel

# from youtube_transcript_api import YouTubeTranscriptApi

# from bs4 import BeautifulSoup
# import trafilatura


# reader = easyocr.Reader(['en'])

# def load_image_ocr(path):
#     result = reader.readtext(path, detail=0)
#     text = " ".join(result)
#     return text


# img_path = r"H:\PGAGI\cyberGuard\test_data\cyberGuard_test1.jpeg"  # put image here

# text = load_image_ocr(img_path)
# print(text)

import requests

API_KEY = "K87392776488957"

image_path = r"H:\PGAGI\cyberGuard\test_data\cyberGuard_test1.jpeg"

url = "https://api.ocr.space/parse/image"

with open(image_path, "rb") as f:
    response = requests.post(
        url,
        files={"file": f},
        data={
            "apikey": API_KEY,
            "language": "eng"
        }
    )

result = response.json()

print(result)

# Extract text
if result["IsErroredOnProcessing"] == False:
    text = result["ParsedResults"][0]["ParsedText"]
    print("Detected text:\n", text)
else:
    print("Error:", result)