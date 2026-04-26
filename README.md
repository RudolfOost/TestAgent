# Meal Calorie Tracker (ChatGPT Vision)

Kleine Flask-app waarmee je op je telefoon een foto van een maaltijd maakt, waarna ChatGPT de calorieën schat en opslaat met datum/tijd.

## Features
- Foto upload (met `capture="environment"` voor mobiele camera)
- Calorie-inschatting via OpenAI vision model
- Opslag in SQLite (`meals.db`) met ISO timestamp
- Overzicht van alle eerdere maaltijden

## Installatie
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuratie
Stel je OpenAI API key in:

```bash
export OPENAI_API_KEY="jouw_api_key"
```

## Starten
```bash
python app.py
```

Open daarna: `http://localhost:5000`

## Database
De app maakt automatisch een SQLite database aan in:
- `meals.db`

Tabel: `meals`
- `id`
- `created_at`
- `photo_name`
- `total_calories`
- `breakdown_json`

## Let op
Calorieën zijn een schatting en kunnen afwijken van de werkelijkheid.
