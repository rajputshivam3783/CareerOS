FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
# NEXT_PUBLIC_* variables are inlined into the client bundle at build
# time by Next.js — a runtime `environment:` entry in docker-compose
# has no effect on them (the value in the already-built JS is fixed).
# Must be passed as a build ARG, not a runtime env var.
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
# V25.6: next.config.ts bakes the security headers into the build, so CSP_ENFORCE is a build ARG
# too. Leave unset/false to ship the CSP as Report-Only until you have checked the browser console.
ARG CSP_ENFORCE=false
ENV CSP_ENFORCE=$CSP_ENFORCE
RUN npm run build
FROM node:22-alpine
WORKDIR /app
COPY --from=build /app ./
RUN chown -R node:node /app
USER node
EXPOSE 3000
# V25.6: liveness probe (no extra packages needed).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "require('http').get('http://127.0.0.1:3000/',r=>process.exit(r.statusCode<500?0:1)).on('error',()=>process.exit(1))"
CMD ["npm","start"]
