import base64
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, url_for
from openai import OpenAI

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "meals.db"

app = Flask(__name__)


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                photo_name TEXT NOT NULL,
                total_calories INTEGER NOT NULL,
                breakdown_json TEXT NOT NULL
            )
            """
        )


def image_to_base64(file_bytes: bytes) -> str:
    return base64.b64encode(file_bytes).decode("utf-8")


def estimate_calories_with_gpt(image_bytes: bytes, filename: str) -> dict:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY ontbreekt. Voeg deze toe als environment variable.")

    client = OpenAI(api_key=api_key)
    image_base64 = image_to_base64(image_bytes)

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Analyseer deze maaltijdfoto en schat het aantal calorieën. "
                            "Geef ALLEEN JSON terug met dit schema: "
                            '{"total_calories": number, "items": [{"name": string, "estimated_calories": number}]}. '
                            "Rond af op hele getallen."
                        ),
                    },
                    {
                        "type": "input_image",
                        "image_url": f"data:image/{filename.split('.')[-1]};base64,{image_base64}",
                    },
                ],
            }
        ],
        temperature=0,
    )

    raw = response.output_text.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Ongeldig modelantwoord: {raw}") from exc

    if "total_calories" not in data:
        raise RuntimeError("Modelantwoord mist 'total_calories'.")
    if "items" not in data or not isinstance(data["items"], list):
        raise RuntimeError("Modelantwoord mist geldige 'items'.")

    return {
        "total_calories": int(round(float(data["total_calories"]))),
        "items": [
            {
                "name": str(item.get("name", "Onbekend")),
                "estimated_calories": int(round(float(item.get("estimated_calories", 0)))),
            }
            for item in data["items"]
        ],
    }


@app.route("/", methods=["GET"])
def index():
    with get_db_connection() as conn:
        meals = conn.execute(
            "SELECT id, created_at, photo_name, total_calories, breakdown_json FROM meals ORDER BY created_at DESC"
        ).fetchall()

    parsed_meals = []
    for meal in meals:
        parsed_meals.append(
            {
                "id": meal["id"],
                "created_at": meal["created_at"],
                "photo_name": meal["photo_name"],
                "total_calories": meal["total_calories"],
                "items": json.loads(meal["breakdown_json"]),
            }
        )

    return render_template("index.html", meals=parsed_meals)


@app.route("/analyze", methods=["POST"])
def analyze_photo():
    if "photo" not in request.files:
        return jsonify({"error": "Geen foto ontvangen."}), 400

    photo = request.files["photo"]
    if not photo.filename:
        return jsonify({"error": "Bestandsnaam ontbreekt."}), 400

    image_bytes = photo.read()
    if not image_bytes:
        return jsonify({"error": "Lege foto ontvangen."}), 400

    try:
        result = estimate_calories_with_gpt(image_bytes, photo.filename)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    created_at = datetime.now(timezone.utc).isoformat()

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO meals (created_at, photo_name, total_calories, breakdown_json) VALUES (?, ?, ?, ?)",
            (created_at, photo.filename, result["total_calories"], json.dumps(result["items"])),
        )

    return redirect(url_for("index"))


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
