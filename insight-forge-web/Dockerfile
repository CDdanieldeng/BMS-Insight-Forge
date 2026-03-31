# syntax=docker/dockerfile:1

FROM node:22-alpine AS build
WORKDIR /app/insight-forge-web

COPY insight-forge-web/package.json insight-forge-web/package-lock.json ./
RUN npm ci

COPY insight-forge-web/ ./

ARG VITE_BACKEND_URL=http://localhost:8001
ENV VITE_BACKEND_URL=$VITE_BACKEND_URL
ARG VITE_TEMPLATE_FETCH_URL
ENV VITE_TEMPLATE_FETCH_URL=$VITE_TEMPLATE_FETCH_URL
ARG VITE_VOICE_INPUT_LANGUAGE
ENV VITE_VOICE_INPUT_LANGUAGE=$VITE_VOICE_INPUT_LANGUAGE
ARG VITE_ENTRA_AUTH_ENABLED
ENV VITE_ENTRA_AUTH_ENABLED=$VITE_ENTRA_AUTH_ENABLED
ARG VITE_ENTRA_CLIENT_ID
ENV VITE_ENTRA_CLIENT_ID=$VITE_ENTRA_CLIENT_ID
ARG VITE_ENTRA_TENANT_ID
ENV VITE_ENTRA_TENANT_ID=$VITE_ENTRA_TENANT_ID
ARG VITE_ENTRA_API_SCOPE
ENV VITE_ENTRA_API_SCOPE=$VITE_ENTRA_API_SCOPE

RUN npm run build

FROM nginx:alpine
COPY --from=build /app/insight-forge-web/dist /usr/share/nginx/html
COPY insight-forge-web/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
