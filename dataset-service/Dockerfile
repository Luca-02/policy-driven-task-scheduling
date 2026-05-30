FROM python:3.12-slim

RUN groupadd -g 1000 app && useradd -u 1000 -g app -m -s /bin/bash app

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY main.py .
COPY data/seed.json ./data/

RUN chown -R app:app /app

USER 1000

EXPOSE 8443

ENTRYPOINT ["python", "-m", "main"]