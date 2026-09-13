FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir boto3
COPY scripts/backup_s3_bucket.py /app/scripts/backup_s3_bucket.py
ENTRYPOINT ["python", "scripts/backup_s3_bucket.py"]
