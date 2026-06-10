FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
COPY apps/bot ./apps/bot
RUN npm ci --workspace=@scorevault/bot
EXPOSE 3001
CMD ["node", "apps/bot/src/index.js"]
