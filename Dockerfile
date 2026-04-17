FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	PIP_NO_CACHE_DIR=1 \
	PYTHONPATH=/app/src \
	FLASK_APP=app \
	FLASK_ENV=production \
	FLASK_RUN_HOST=0.0.0.0 \
	FLASK_RUN_PORT=5000

WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt && pip install psycopg2-binary

COPY . .

EXPOSE 5000

CMD ["python", "-m", "flask", "run"]
