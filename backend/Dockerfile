FROM python:3.10-slim

ENV TZ=Asia/Riyadh \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN useradd -u 1000 -m -s /bin/sh rasid && \
    mkdir -p /var/lib/rasid /app/data && \
    chown -R rasid:rasid /var/lib/rasid /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chown -R rasid:rasid /app

USER rasid

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
