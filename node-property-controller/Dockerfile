FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

COPY main.py .

EXPOSE 9090

ENTRYPOINT ["kopf", "run", "main.py", "--all-namespaces", "--standalone", "--liveness=http://0.0.0.0:9090/healthz"]