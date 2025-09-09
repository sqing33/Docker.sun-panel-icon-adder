# 多阶段构建：构建阶段
FROM python:3.12-alpine as builder

WORKDIR /app

RUN apk add --no-cache gcc musl-dev linux-headers

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


FROM python:3.12-alpine

WORKDIR /app

# 从构建阶段复制已安装的包
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY app.py .
COPY templates/ templates/
COPY static/ static/

EXPOSE 3003

CMD ["python", "app.py"]
