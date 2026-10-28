# NGSIRS CRM web console. Build from the repository root:
#   docker build -f infra/docker/web.Dockerfile --build-arg NEXT_PUBLIC_API_URL=https://api.example -t ngsirs-crm-web .
FROM node:22-alpine AS build
RUN corepack enable
WORKDIR /repo
COPY . .
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_TELEMETRY_DISABLED=1
RUN pnpm install --frozen-lockfile && pnpm --filter ./apps/web build

FROM node:22-alpine
RUN corepack enable && addgroup -S ngsirs && adduser -S ngsirs -G ngsirs
WORKDIR /repo
COPY --from=build /repo /repo
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
USER ngsirs
EXPOSE 3000
CMD ["pnpm", "--filter", "./apps/web", "start", "--port", "3000"]
