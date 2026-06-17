FROM node:26-slim

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY index.html tsconfig.json vite.config.ts ./
COPY src ./src

EXPOSE 3737
