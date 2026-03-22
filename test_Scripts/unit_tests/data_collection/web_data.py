import requests

def load_url_markdown(url: str) -> str:
    api_url = f"https://markdown.new/{url}"

    response = requests.get(api_url)

    if response.status_code != 200:
        raise Exception("Failed to fetch")

    return response.text


# test
text = load_url_markdown(
    "https://www.leftviews.in/en-IN/politics-77808/views-55812/modi-india-first-myth-us-pressure-russian-oil-55956"
)

print(text)