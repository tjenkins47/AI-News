from flask import Flask, render_template, jsonify
from flask_cors import CORS
import os, json
from datetime import datetime

app = Flask(__name__)
CORS(app)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/api/news")
def api_news():
    story = {
        "timestamp": datetime.utcnow().isoformat(),
        "title": {"en": "Example AI Story", "fr": "Exemple d'article IA"},
        "summary": {"en": "This is an AI news summary.", "fr": "Ceci est un résumé de l'actualité IA."},
        "url": "https://example.com",
        "categories": ["Model"]
    }
    return jsonify([story])

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
