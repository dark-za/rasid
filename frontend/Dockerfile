# مرحلة البناء: تجميع Vite إلى dist
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# مرحلة التشغيل: nginx يقدّم dist ويمرّر /api إلى الباكند على شبكة compose
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
