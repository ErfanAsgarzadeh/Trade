FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY lbank_bot.py dashboard_server.py config.json ./
RUN mkdir -p /app/runtime
CMD ["python", "-u", "lbank_bot.py"]
