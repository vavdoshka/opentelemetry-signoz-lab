FROM python:3.13-slim
WORKDIR /app
# journalctl, for k8s/journal-log.yaml. Debian only ships it in the systemd package.
RUN apt-get update && apt-get install -y --no-install-recommends systemd && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY workload.py kernel_log.py index.html ./
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "workload:app", "--host", "0.0.0.0", "--port", "8000"]
