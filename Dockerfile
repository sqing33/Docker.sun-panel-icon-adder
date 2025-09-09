FROM python:3.12-alpine

WORKDIR /app

# 安装必要的系统依赖
RUN apk add --no-cache gcc musl-dev linux-headers

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY app.py .
COPY templates/ templates/

EXPOSE 3003

CMD ["python", "app.py"]
