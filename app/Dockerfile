FROM python:3.13-slim
WORKDIR /app
# requirements.lock.txt = exact versions resolved from requirements.txt.
COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY telemetry.py frontend.py backend.py index.html ./
# Which service runs is chosen by the k8s Deployment (frontend:app or backend:app).
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "frontend:app", "--host", "0.0.0.0", "--port", "8000"]
