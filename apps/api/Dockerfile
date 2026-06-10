FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
COPY packages/schema ./packages/schema
COPY apps/api ./apps/api
RUN npm ci --workspace=@scorevault/api --workspace=@scorevault/schema
EXPOSE 4000
CMD ["node", "apps/api/src/index.js"]
