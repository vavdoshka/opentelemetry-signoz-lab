FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY frontend.py backend.py index.html ./
# Which service runs is chosen by the k8s Deployment.
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "frontend:app", "--host", "0.0.0.0", "--port", "8000"]
