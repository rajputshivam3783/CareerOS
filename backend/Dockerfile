FROM python:3.13-slim

# V25.6: no .pyc litter, unbuffered logs (so nothing is lost if the container is killed).
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# V10: don't run the app as root inside the container.
RUN useradd --create-home --uid 1000 careeros && chown -R careeros:careeros /app
USER careeros

ENTRYPOINT ["/app/docker-entrypoint.sh"]

EXPOSE 8000

# WEB_CONCURRENCY controls how many worker processes handle requests.
# Defaults to 1 because the in-process background scheduler
# (app/scheduler.py) isn't safe to run in more than one process
# without extra config — see its docstring and SCHEDULER_ENABLED in
# app/core/config.py. Raise this only after setting SCHEDULER_ENABLED=false
# on every worker except one, or you'll get duplicate ingestion runs
# and a real risk of duplicate notifications.
ENV WEB_CONCURRENCY=1
# V25.6: client IPs come from X-Forwarded-For ONLY when the immediate peer is in this list.
# Behind a reverse proxy set it to the proxy's address/network (e.g. FORWARDED_ALLOW_IPS=10.0.0.5);
# leaving the default means every request appears to come from the proxy and shares ONE rate-limit
# bucket. Never set it to "*" unless the backend port is reachable only from the proxy - anyone who
# can reach it directly could forge their IP and evade rate limits/lockouts.
ENV FORWARDED_ALLOW_IPS=127.0.0.1
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY}"]
