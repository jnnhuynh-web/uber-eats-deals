FROM mcr.microsoft.com/playwright/python:v1.52.0-noble

WORKDIR /app

RUN pip install --no-cache-dir playwright==1.52.0 flask==3.1.1

COPY . .

EXPOSE 5000

CMD ["python3", "app.py"]
