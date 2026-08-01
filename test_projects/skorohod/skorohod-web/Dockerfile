# Образ для локального запуска витрины (dev-режим Next.js).
FROM node:20-alpine

WORKDIR /app

COPY package.json ./
RUN npm install --no-audit --no-fund

COPY . .

EXPOSE 3020

CMD ["npx", "next", "dev", "-p", "3020", "-H", "0.0.0.0"]
