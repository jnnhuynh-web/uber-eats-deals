FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir playwright==1.52.0 flask==3.1.1

RUN playwright install --with-deps chromium

COPY . .

EXPOSE 80

CMD ["python3", "app.py"]
