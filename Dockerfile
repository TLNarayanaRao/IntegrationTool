FROM node:24-bookworm-slim AS ui
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
COPY frontend/vendor ./vendor
RUN ELECTRON_SKIP_BINARY_DOWNLOAD=1 npm ci --include=dev
COPY . /src
RUN npm run build

FROM python:3.12-slim-bookworm
WORKDIR /app
COPY backend/requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends libodbc2 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt && pip check
COPY backend/app ./backend/app
COPY --from=ui /src/frontend/dist ./frontend/dist
RUN useradd --uid 10001 --create-home mina \
    && install -d -o mina -g mina /app/backend/data
ENV PYTHONPATH=/app/backend MINA_DATA_DIR=/app/backend/data \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001
EXPOSE 8787
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8787"]
