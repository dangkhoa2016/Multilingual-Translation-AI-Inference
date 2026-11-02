"""uvicorn multilingual_translation_ai_inference.local:app --reload"""
from .api import create_api

app = create_api()
