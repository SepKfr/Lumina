FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json* ./
# Increase timeout for slow/flaky networks (e.g. Docker build)
RUN npm config set fetch-timeout 300000 && \
    npm config set fetch-retry-maxtimeout 120000 && \
    npm install

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev"]
