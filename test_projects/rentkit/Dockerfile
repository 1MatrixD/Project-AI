# Один образ на весь монорепо: API и веб отличаются только командой запуска.
FROM node:20-alpine

WORKDIR /repo

# Сначала манифесты — слой с зависимостями переиспользуется между сборками.
COPY package.json ./
COPY packages/core/package.json packages/core/
COPY apps/api/package.json apps/api/
COPY apps/web/package.json apps/web/
RUN npm install --no-audit --no-fund

COPY . .

# API и веб импортируют @rentkit/core как собранный пакет.
RUN npm run build --workspace @rentkit/core

EXPOSE 8030 5173

CMD ["npm", "run", "dev:api"]
