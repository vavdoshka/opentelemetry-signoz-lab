FROM python:3.13-slim
WORKDIR /app
COPY sink.py ./
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "sink.py"]
