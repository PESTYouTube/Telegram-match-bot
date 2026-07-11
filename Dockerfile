FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Устанавливаем git и системные зависимости
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

# Клонируем репозиторий (используем ARG для токена)

RUN git clone https://PESTYouTube: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@github.com/PESTYouTube/Telegram-match-bot.git /app

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Запускаем бота
CMD ["python", "tg_bot.py"]