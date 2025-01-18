FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY config.py .
COPY templates templates/

# 创建数据目录
RUN mkdir -p data && \
    chown -R 1000:1000 data

EXPOSE 8000

CMD ["python", "main.py"] 