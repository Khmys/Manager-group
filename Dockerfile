FROM mcr.microsoft.com/playwright/python:v1.59.0-jammy

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Anzisha bot
CMD ["python", "bot.py"]
