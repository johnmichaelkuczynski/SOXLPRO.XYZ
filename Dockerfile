FROM --platform=$BUILDPLATFORM node:20-bookworm-slim AS browser-build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY scripts/build.js ./scripts/build.js
COPY components ./components
COPY preview_recovery.js ./
RUN npm run build

FROM --platform=$BUILDPLATFORM python:3.11-slim AS python-deps
WORKDIR /src
COPY requirements.txt ./
ARG TARGETARCH
RUN if [ "$TARGETARCH" = "arm64" ]; then \
      python -m pip install --no-cache-dir --target=/python-packages \
        --platform manylinux_2_17_aarch64 \
        --platform manylinux_2_24_aarch64 \
        --platform manylinux_2_27_aarch64 \
        --platform manylinux_2_28_aarch64 \
        --platform manylinux2014_aarch64 \
        --platform linux_aarch64 --python-version 3.11 \
        --implementation cp --abi cp311 --only-binary=:all: -r requirements.txt; \
    else \
      python -m pip install --no-cache-dir --target=/python-packages -r requirements.txt; \
    fi

FROM python:3.11-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production \
    PORT=5000
WORKDIR /app
COPY --from=python-deps /python-packages /usr/local/lib/python3.11/site-packages
COPY --from=browser-build /tmp/soxl-js-build-manifest.json /usr/local/share/soxl/js-build-manifest.json
COPY . .
EXPOSE 5000
CMD ["python", "seo_server.py"]
