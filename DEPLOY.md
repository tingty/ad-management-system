# 广告管理系统 · 部署文档（Docker 一键）

面向技术部署人员。本文档描述如何把本项目部署到一台云服务器（Linux），通过 Docker 一键起前后端。

---

## 1. 环境要求

- 一台云服务器（2 vCPU / 4 GB 内存起步即可，SQLite + 轻量并发）
- 操作系统：Ubuntu 22.04 / 24.04 或其他主流 Linux
- 已安装 **Docker (≥24)** 与 **Docker Compose v2**
  - 安装参考：`curl -fsSL https://get.docker.com | sh` 然后 `sudo usermod -aG docker $USER`（重新登录生效）
  - 验证：`docker --version`、`docker compose version`

---

## 2. 获取代码

方式 A（推荐，私有 Git 仓库）：
```bash
git clone <你的私有仓库地址> ad-material-platform
cd ad-material-platform
```

方式 B（压缩包）：将仓库根目录（含 `backend/`、`frontend/`、`docker-compose.yml`）打包后上传解压。

> 注意：仓库已通过 `.gitignore` 排除了 `node_modules/`、`frontend/dist/`、`*.db`、`uploads/` 等，
> 无需手动清理，直接拿源码即可。

---

## 3. 一键构建并启动

```bash
# 在仓库根目录执行（含 docker-compose.yml 的那一层）
docker compose up -d --build
```

这条命令会：
1. 构建 `backend` 镜像（Python + FastAPI + uvicorn）
2. 构建 `frontend` 镜像（Node 构建前端 → nginx 提供静态服务）
3. 启动两个容器：`backend`（内部 8033）、`web`（对外 80）
4. 创建两个持久化卷：`admb_data`（数据库）、`admb_uploads`（上传素材）

启动后访问：**http://<服务器公网IP>**（默认 80 端口）

### 常用命令
```bash
docker compose ps                 # 查看容器状态
docker compose logs -f            # 实时日志
docker compose logs -f backend    # 只看后端日志
docker compose down               # 停止并移除容器（数据卷保留）
docker compose up -d --build      # 代码更新后重新构建启动
```

---

## 4. 默认账号

应用首次启动会在 `on_startup` 自动建表并初始化默认账号：

| 用户名   | 密码         | 角色         |
|----------|--------------|--------------|
| admin    | Admin@123    | 系统管理员   |
| manager  | Manager@123  | 投放经理     |
| editor   | Editor@123   | 投放执行     |
| viewer   | Viewer@123   | 只读账号     |

> 生产环境请登录后及时修改密码 / 停用演示账号。

---

## 5. 数据持久化

- 数据库：`admb_data` 卷挂载到容器 `/app/data`，对应 `DATABASE_URL=sqlite:////app/data/ad_material.db`
- 上传文件：`admb_uploads` 卷挂载到容器 `/app/uploads`
- 容器重建、镜像更新都不会丢失数据（卷独立于容器生命周期）

查看卷位置：`docker volume ls`、`docker volume inspect ad-material-platform_admb_data`

### （可选）迁移现有本地数据
若要把本地开发库的数据带到服务器：把本地 `backend/ad_material.db*` 复制到服务器的卷目录后重启 `backend` 容器即可。
迁移前请先备份本地数据库。

---

## 6. 生产 HTTPS（推荐）

`docker-compose.yml` 仅暴露 80 端口。对外建议再加一层反向代理提供 HTTPS。
可复用你现有的 **Cloudflare Tunnel + Caddy** 模式（与 RM BI System 一致）：

- 在服务器上用 Caddy 反代 `http://127.0.0.1:80`，并自动申请证书：
  ```
  your-domain.example  {
      reverse_proxy 127.0.0.1:80
  }
  ```
- 通过 Cloudflare Tunnel 将域名安全地暴露到公网，无需开放服务器入站端口。

---

## 7. 配置说明（技术向）

| 项 | 位置 | 说明 |
|----|------|------|
| 后端端口 | `backend/main.py` `uvicorn ... port=8033`；compose 内部 `expose 8033` | 已统一为 8033 |
| 数据库路径 | `backend/database.py` 读 `DATABASE_URL` 环境变量 | 容器内默认 `sqlite:////app/data/ad_material.db` |
| 上传目录 | `backend/main.py` `UPLOAD_DIR = <backend>/uploads` | 容器内 `/app/uploads`，由卷持久化 |
| 前端 API 地址 | `frontend/src/api.ts` `VITE_API_BASE` | Docker 构建时置空 → 同源相对路径，由 nginx 反代 `/api`、`/files` 到后端 |
| CORS | `backend/main.py` `allow_origins=["*"]` | 同源部署下不触发跨域；若前后端分离域名需收紧 |

---

## 8. 排障

- **页面能打开但接口 401/连不上**：确认 `web` 容器能访问 `backend:8033`（同 compose 网络内，服务名即主机名）。
- **上传/下载文件 404**：确认 `admb_uploads` 卷已挂载且后端已 `mkdir /app/uploads`。
- **数据库 locked**：SQLite 已开启 WAL + busy_timeout；高并发写入建议后续迁移到 PostgreSQL（改 `DATABASE_URL` 即可，代码无需改动）。
- **修改前端 API 地址后未生效**：`VITE_API_BASE` 是**构建期**变量，需重新 `docker compose up -d --build`。

---

## 9. 后续可扩展

- 高并发 / 多实例：将 `DATABASE_URL` 指向 PostgreSQL，`uploads` 改用对象存储（S3/OSS）或共享卷。
- 多副本：当前 SQLite 不适合多写实例，迁移数据库后即可横向扩展 `backend`。
