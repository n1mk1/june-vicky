# Vik web (Next.js standalone).
#
#   docker build -t vik-web ./frontend                 # production image (last stage)
#   docker run --rm -p 3000:3000 -e PORT=3000 vik-web
#   docker build --target dev ./frontend                 # dev image used by docker-compose (next dev)
#
# API_INTERNAL_URL and API_PUBLIC_WS_URL are read at request time, so nothing is baked in here.
# Render sets PORT; the standalone server.js reads PORT and HOSTNAME.

FROM node:22-alpine AS base
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1 \
    NPM_CONFIG_UPDATE_NOTIFIER=false

# ---- deps: install from the lockfile (cached until package*.json changes) ----
# package-lock.json is written by npm 11; the npm 10 bundled with node 22 rejects it
# ("Missing: @emnapi/... from lock file"), so pin the same npm major as the lockfile's author.
FROM base AS deps
ARG NPM_VERSION=11.6.2
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
RUN npm install -g "npm@${NPM_VERSION}" --no-audit --no-fund
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# ---- dev: `next dev` with the source bind-mounted by docker-compose ----
FROM deps AS dev
COPY . .
EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", "3000"]

# ---- build ----
FROM base AS builder
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# ---- runtime ----
FROM base AS runner
ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0
COPY --from=builder --chown=node:node /app/public ./public
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
