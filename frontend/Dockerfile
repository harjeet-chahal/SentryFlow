# Build stage
FROM node:18-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
# Baked into the bundle at build time. Empty means same-origin: nginx (or the
# Kubernetes ingress) routes the API paths to the gateway.
ARG REACT_APP_API_URL=""
ENV REACT_APP_API_URL=$REACT_APP_API_URL
RUN npm run build

# Production stage
# nginx-unprivileged listens on 8080 and runs as a non-root user, which is
# what lets the Kubernetes securityContext enforce runAsNonRoot.
FROM nginxinc/nginx-unprivileged:alpine

COPY --from=build /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 8080
