FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first so this layer is reused until requirements.txt / constraints.txt change.
# constraints.txt pins the verified versions (reproducible builds, no surprise upgrades).
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt

# .dockerignore keeps every .env* file, the dev database and the virtualenv out of the image
COPY . .

# Non-root user; /data holds the SQLite database (mounted as a volume)
RUN adduser --system --uid 10001 app && mkdir -p /data && chown app /data
USER app

EXPOSE 8000

# Database migrations are NOT run here. The deployment script (deploy.sh) runs them explicitly,
# exactly once, after a backup, so a container restart can never change the database.
#
# One worker with threads: the login/delete rate limits use an in-process cache, so several
# worker processes would each count separately.
# --no-control-socket: gunicorn 27's optional admin socket cannot be created for this non-root user
# (home is /nonexistent) and logged a harmless but noisy error on every start; the app does not use it.
# The access-log format logs the URL path only (%(U)s), never the query string, so the webhook
# verify token in "/webhook?hub.verify_token=..." does not end up in the logs.
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--timeout", "60", \
     "--no-control-socket", \
     "--access-logfile", "-", \
     "--access-logformat", "%(h)s %(l)s %(u)s %(t)s \"%(m)s %(U)s %(H)s\" %(s)s %(b)s \"%(a)s\""]
