# Tumia image rasmi ya Python
FROM python:3.11-slim

# Weka environment variables kwa usalama
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Tengeneza directory ya app
WORKDIR /app

# Nakili faili za mahitaji
COPY requirements.txt .

# Sakinisha dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Nakili code ya bot
COPY . .

# Weka port (kwa deployment kama Heroku au Render)
EXPOSE 10000

# Anzisha bot
CMD ["python", "bot.py"]
