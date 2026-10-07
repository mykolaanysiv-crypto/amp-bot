FROM python:3.13-slim

WORKDIR /app
COPY requirements.lock requirements.txt ./
RUN pip install --no-cache-dir -r requirements.lock
COPY . .
RUN mkdir -p /app/data
CMD ["python", "run.py"]
