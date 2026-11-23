# Stage 1: build frontend (Vite + Svelte + Tailwind)
FROM node:24-alpine@sha256:a34ab6d7f6f4813f4d0c5469d74685604b962fbdbf5793a7bc7b4998ecb867c8 AS assets
WORKDIR /assets
ARG MUSIC_APP_NAME=Armonia
ENV VITE_APP_NAME=$MUSIC_APP_NAME

# Install exactly what the lockfile pins (the versions Dependabot audits),
# rather than re-resolving the semver ranges at image build time.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts --no-fund --no-audit

COPY frontend/ ./frontend/
RUN cd frontend && npm run build

# Stage 2: Python runtime
#
# Debian slim (glibc) rather than Alpine (musl): yt-dlp now needs an external
# JavaScript runtime to solve YouTube's player-signature ("nsig") challenge, and
# the Deno binary is glibc-only. slim also ships manylinux wheels for psutil /
# uvicorn[standard], so no compiler is needed.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

# Explicit Debian security fix; keep the chosen version reviewable.
RUN apt-get update \
    && apt-get install -y --no-install-recommends zlib1g=1:1.3.dfsg+really1.3.1-1+deb13u1 \
    && rm -rf /var/lib/apt/lists/*

# Deno — the JS runtime yt-dlp auto-detects on PATH for YouTube extraction.
COPY --from=denoland/deno:bin@sha256:b507583d3c68ba69f3ed2ce5969ae5b8b70f43421c781279c7aea06435263543 /deno /usr/local/bin/deno
COPY --from=mwader/static-ffmpeg:9.0.2@sha256:7d9bdaaf887f7e6ce6151f67325c344074b5ff1fb75316011c3376503e449a7b /ffmpeg /usr/local/bin/ffmpeg
COPY --from=mwader/static-ffmpeg:9.0.2@sha256:7d9bdaaf887f7e6ce6151f67325c344074b5ff1fb75316011c3376503e449a7b /ffprobe /usr/local/bin/ffprobe
COPY --from=mwader/static-ffmpeg:9.0.2@sha256:7d9bdaaf887f7e6ce6151f67325c344074b5ff1fb75316011c3376503e449a7b /versions.json /usr/local/share/ffmpeg-components.json

# Static FFmpeg avoids the desktop dependency tree of the old Debian package.
# This artifact still requires vulnerability scanning.

# Unprivileged user the app actually runs as (-m gives it a writable $HOME for
# yt-dlp / ytmusicapi caches).
RUN groupadd -g 1000 app \
    && useradd -u 1000 -g app -m -d /home/app -s /usr/sbin/nologin app

WORKDIR /app

COPY requirements.lock .
RUN pip install --no-cache-dir --upgrade pip==26.3 \
    && pip install --no-cache-dir -r requirements.lock \
    && python -m pip uninstall --yes pip

COPY . .
COPY --from=assets /assets/frontend/dist/ ./frontend/dist/

# Prepare dedicated paths at build time. Runtime never changes host ownership.
RUN mkdir -p /app/data /app/secrets /music \
    && chown app:app /app/data /music \
    && cp /app/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

ARG ARMONIA_COMMIT
LABEL org.opencontainers.image.revision=$ARMONIA_COMMIT

EXPOSE 8000
USER 1000:1000
ENV PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "serve.py"]
