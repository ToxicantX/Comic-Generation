FROM node:22-slim AS frontend-build

WORKDIR /app

COPY package.json package-lock.json vite.config.ts tsconfig.frontend.json /app/
COPY console/frontend /app/console/frontend
COPY scripts/assert_frontend_build.mjs /app/scripts/assert_frontend_build.mjs
RUN npm ci && npm run frontend:build

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    COMIC_PIPELINE_CONFIG_PATH=/app/config/.env.docker

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg apt-transport-https \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
        > /etc/apt/sources.list.d/microsoft-prod.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends powershell fonts-noto-cjk \
    && ln -sf /usr/bin/pwsh /usr/local/bin/powershell \
    && pip install --no-cache-dir -r /app/requirements.txt \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY . /app
COPY --from=frontend-build /app/console/static/vue /app/console/static/vue

EXPOSE 8199

CMD ["python", "console/server.py", "--host", "0.0.0.0", "--port", "8199"]
