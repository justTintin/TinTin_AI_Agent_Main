# 数据库部署指南 — 云服务器独立部署

## 前提

- Ubuntu 24.04 / Debian 12 云服务器
- PostgreSQL 17 + pgvector 0.8+
- 至少 2GB 内存，20GB 磁盘
- 安全组开放目标端口（如 5432）

## 1. 安装 PostgreSQL 17 + pgvector

```bash
# PostgreSQL 17
sudo apt update
sudo apt install -y postgresql-17 postgresql-client-17

# pgvector（从官方 apt 源或源码）
sudo apt install -y postgresql-17-pgvector
# 如果没有 apt 包：
# cd /tmp && git clone --branch v0.8.3 https://github.com/pgvector/pgvector.git
# cd pgvector && make && sudo make install
```

## 2. 基础配置

```bash
# 设置数据库用户密码
sudo -u postgres psql -c "ALTER USER postgres PASSWORD '你的强密码';"

# 允许远程连接
sudo sed -i "s/#listen_addresses = 'localhost'/listen_addresses = '*'/" \
    /etc/postgresql/17/main/postgresql.conf

# 认证（生产环境建议 scram-sha-256 + SSL）
echo "host  material_index  all  0.0.0.0/0  md5" \
    | sudo tee -a /etc/postgresql/17/main/pg_hba.conf

sudo systemctl restart postgresql
```

## 3. 建库 + 导入 schema

```bash
sudo -u postgres createdb -E UTF8 material_index
sudo -u postgres psql -d material_index -f docs/schema.sql
```

## 4. 建向量索引（插入数据后）

```sql
-- HNSW 比 IVFFlat 准确度更高，无需训练步骤
CREATE INDEX idx_frames_embedding ON frames
    USING hnsw (embedding vector_cosine_ops);
```

## 5. 客户端配置

在客户机器 `studio/config/` 下创建 `material_index_config.json`：

```json
{
  "db_host": "你的服务器IP",
  "db_port": 5432,
  "db_name": "material_index",
  "db_user": "postgres",
  "db_password": "你的密码",

  "tag_depth_product": 0,
  "tag_depth_brand": 1,
  "tag_depth_model": 2,
  "tag_depth_category": -1,

  "fps": 1,
  "clip_model": "ViT-B-16",
  "device": "auto",
  "batch_size": 8,
  "ffmpeg_path": null,
  "save_thumbs": false,
  "thumb_dir": null,

  "nas_root": null,
  "index_directories": [],
  "local_directories": [],
  "default_storage": "local"
}
```

## 6. 验证

```bash
psql -h 服务器IP -U postgres -d material_index -c "
SELECT table_name, 
       (SELECT COUNT(*) FROM information_schema.columns WHERE table_name=t.table_name) AS cols
FROM information_schema.tables t
WHERE table_schema='public'
ORDER BY table_name;
"

# 预期: materials (20 columns), frames (10 columns)
```

## 安全建议

- 生产环境用 SSL（`sslmode='require'`）
- 白名单客户 IP 而非 `0.0.0.0/0`
- 创建专用角色，不用 postgres 超级用户
- 定期 `pg_dump` 备份到对象存储
