FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# .dockerignore keeps every .env* file, the dev database and the virtualenv out of the image
COPY . .

# Non-root user; /data holds the SQLite database (mounted as a volume)
RUN adduser --system --uid 10001 app && mkdir -p /data && chown app /data
USER app

EXPOSE 8000

# One worker with threads: the login/delete rate limits use an in-process cache, so several
# worker processes would each count separately.
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 1 --threads 4 --timeout 60 --access-logfile -"]
