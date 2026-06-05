# ---- Stage 1: build the React frontend ----
FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python runtime serving API + built frontend ----
FROM python:3.12-slim AS runtime

# Hugging Face Spaces runs containers as uid 1000; set up a writable home.
RUN useradd -m -u 1000 user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    FRONTEND_DIST=/home/user/app/frontend/dist \
    PORT=7860

WORKDIR /home/user/app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY --from=frontend /build/dist ./frontend/dist

RUN chmod +x ./backend/entrypoint.sh && chown -R user:user /home/user
USER user

WORKDIR /home/user/app/backend
EXPOSE 7860
CMD ["./entrypoint.sh"]
