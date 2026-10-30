FROM python:3.11-slim

WORKDIR /app

# 先装依赖（利用层缓存，依赖不变时不重复安装）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 再拷贝源码
COPY . .

# 持久化目录：数据库与上传文件（运行时由 docker volume 挂载到这两个路径）
RUN mkdir -p /app/data /app/uploads

ENV DATABASE_URL=sqlite:////app/data/ad_material.db
ENV PYTHONUNBUFFERED=1

EXPOSE 8033

# 应用启动时会在 on_startup 中自动建表、初始化规格库与默认账号
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 8033"]
