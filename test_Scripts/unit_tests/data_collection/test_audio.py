from faster_whisper import WhisperModel

model = WhisperModel(
    "base",
    device="cpu",   # or "cuda"
    compute_type="int8"
)

audio_file = r"H:\PGAGI\cyberGuard\test_data\test1.mp3"

segments, info = model.transcribe(audio_file)

text = ""

for segment in segments:
    text += segment.text + " "

print(text)