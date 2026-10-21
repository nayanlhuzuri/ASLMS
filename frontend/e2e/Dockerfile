# The browser check of the portal (design portal-ui-polish, decisions 18-22): Playwright with Chromium, run by the
# Compose service `uicheck` (profile `uicheck`, compose.dev.yml) against the real `web` service. Build context is
# ./frontend; its own ignore file is e2e/Dockerfile.dockerignore. The image's Playwright and the package's must be
# the same version, or the browsers do not match: the build stops when they differ.
ARG PLAYWRIGHT_VERSION=1.64.1
FROM mcr.microsoft.com/playwright:v${PLAYWRIGHT_VERSION}-noble
ARG PLAYWRIGHT_VERSION
WORKDIR /work
# the page list and the API types (import type only), and the OpenAPI document the synthetic answers come from
COPY src ./src
COPY openapi.json ./openapi.json
COPY e2e/package.json e2e/package-lock.json ./e2e/
RUN node -e "const v=require('/work/e2e/package.json').devDependencies['@playwright/test']; if (v !== process.env.PLAYWRIGHT_VERSION) { console.error('@playwright/test ' + v + ' in e2e/package.json, image ' + process.env.PLAYWRIGHT_VERSION + ': make them equal'); process.exit(1); }"
WORKDIR /work/e2e
RUN npm ci --no-audit --no-fund
COPY e2e ./
# a fixture that no longer matches the API's generated types breaks the build
RUN npx tsc --noEmit
RUN mkdir -p /out && chown pwuser:pwuser /out
USER pwuser
ENV UICHECK_OUT=/out UICHECK_BASE_URL=http://web:3000
CMD ["npx", "playwright", "test"]
