import os

from dotenv import load_dotenv
from google import genai

load_dotenv()

_DEFAULT_MODEL = "gemini-3.1-flash-lite"
_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


def generate_content(contents, **kwargs):
    return _client.models.generate_content(
        model=_DEFAULT_MODEL,
        contents=contents,
        **kwargs,
    )
