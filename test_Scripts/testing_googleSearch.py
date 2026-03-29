from google import genai
from google.genai import types
from dotenv import load_dotenv
import os
import time

# Load env
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise ValueError("Missing GEMINI_API_KEY in .env")

client = genai.Client(api_key=api_key)

# 🔥 Start timer
total_start = time.time()

print("\n🚀 Sending request...\n")

response = client.models.generate_content(
    model="gemini-3-flash-preview",
    contents="Latest news about Cyber laws in 2026",
    config=types.GenerateContentConfig(
        tools=[{"google_search": {}}]
    ),
)

total_end = time.time()

# =========================
# ✅ TEXT OUTPUT
# =========================
print("📄 Answer:\n" + "-"*50)

final_text = ""
for part in response.candidates[0].content.parts:
    if hasattr(part, "text") and part.text:
        final_text += part.text

print(final_text)

# =========================
# ✅ TOKENS
# =========================
print("\n📊 Token Usage:\n" + "-"*50)

usage = getattr(response, "usage_metadata", None)

if usage:
    print(f"Prompt Tokens: {usage.prompt_token_count}")
    print(f"Response Tokens: {usage.candidates_token_count}")
    print(f"Total Tokens: {usage.total_token_count}")
else:
    print("No token metadata available")

# =========================
# ✅ GROUNDING (STRUCTURED DATA)
# =========================
print("\n🌐 Grounding Data:\n" + "-"*50)

candidate = response.candidates[0]
grounding = getattr(candidate, "grounding_metadata", None)

if grounding:
    # 🔹 Search Queries
    print("\n🔍 Search Queries:")
    for q in grounding.web_search_queries:
        print("-", q)

    # 🔹 Sources
    print("\n📚 Sources:")
    for i, chunk in enumerate(grounding.grounding_chunks):
        if chunk.web:
            print(f"[{i+1}] {chunk.web.title}")
            print(f"     {chunk.web.uri}")

else:
    print("No grounding metadata found")

# =========================
# ✅ TIME
# =========================
print("\n⏱ Performance:\n" + "-"*50)
print(f"Total Time: {total_end - total_start:.2f} seconds\n")