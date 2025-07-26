import os
import json
import requests
from flask import Flask, render_template, jsonify

app = Flask(__name__)

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GNEWS_API_KEY = os.getenv("GNEWS_API_KEY")

# Translation function with fix
def translate_to_french(text: str) -> str:
    if not text:
        return ""
    url = "https://translation.googleapis.com/language/translate/v2"
    params = {
        "q": text,
        "target": "fr",
        "format": "text",
        "key": GOOGLE_API_KEY
    }

    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }

    try:
        response = requests.post(url, data=params, headers=headers)
        if response.status_code == 200:
            return response.json()["data"]["translations"][0]["translatedText"]
        else:
            print(f"Translation error {response.status_code}: {response.text}")
            return text  # fallback to English
    except requests.exceptions.RequestException as e:
        print(f"Translation exception: {e}")
        return text  # fallback to English

# Example route — replace with your actual one
@app.route("/")
def home():
    return render_template("index.html")

# Your other functions and routes here...

if __name__ == "__main__":
    app.run(debug=True)
