# 多阶段构建：Node 构建前端 → Python 运行后端（单端口同时托管前端）
FROM node:20-alpine AS web
WORKDIR /web
ARG NPM_REGISTRY=https://registry.npmjs.org
COPY frontend/package*.json ./
RUN npm install --no-fund --no-audit --registry=$NPM_REGISTRY
COPY frontend/ ./
RUN npm run build && rm -rf public && cp -r dist public

FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY --from=web /web/public ./frontend/public

ENV PORT=8000
EXPOSE 8000
CMD ["python", "backend/main.py"]
