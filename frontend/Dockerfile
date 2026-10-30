# ---- 构建阶段 ----
FROM node:20-alpine AS build
WORKDIR /app

COPY package*.json ./
RUN npm install
COPY . .

# 生产构建：将 VITE_API_BASE 置空，前端改用同源相对路径 /api、/files，
# 由运行阶段的 nginx 反代到后端服务。
ENV VITE_API_BASE=
RUN npm run build

# ---- 运行阶段 ----
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
