-- ============================================================================
-- 螺丝钉-电商智能体矩阵 — 数据库初始化脚本
-- 来源: 从生产库 dump (PostgreSQL 17.10 + pgvector 0.8.3)
-- 数据量: materials 153,877 行 / frames 66,935 行
-- ============================================================================

-- 1. 建扩展
CREATE EXTENSION IF NOT EXISTS vector;       -- pgvector 0.8.3: embedding 向量存储/HNSW 搜索

-- 2. 素材主表
CREATE TABLE IF NOT EXISTS materials (
    id                   BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    path                 TEXT NOT NULL,                  -- 相对路径
    media_type           TEXT NOT NULL,                  -- 'video' | 'image'
    filename             TEXT,
    duration_s           REAL,                           -- 视频时长 (秒)
    width                INTEGER,
    height               INTEGER,
    created_at           TIMESTAMPTZ DEFAULT now(),      -- 入库时间
    file_hash            VARCHAR,                        -- SHA-256 去重
    brand                TEXT,                           -- 品牌
    product              TEXT,                           -- 产品类目
    model                TEXT,                           -- 型号
    category             TEXT,                           -- 分类
    ai_status            TEXT DEFAULT 'pending',         -- pending | analyzing | analyzed | failed
    audio_script         TEXT,                           -- 音频转写
    ai_confidence        REAL,                           -- 置信度 0.0-1.0
    scene_desc_primary   TEXT,                           -- 第一画面描述
    scene_desc_secondary TEXT,                           -- 第二画面描述
    file_size            BIGINT,                         -- 字节
    mtime                DOUBLE PRECISION                -- 文件修改时间
);

-- 2b. 索引
CREATE UNIQUE INDEX IF NOT EXISTS idx_materials_file_hash ON materials (file_hash);

-- 3. 向量帧表
CREATE TABLE IF NOT EXISTS frames (
    id           BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    material_id  BIGINT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    ts_s         REAL NOT NULL DEFAULT 0,
    brand        TEXT,
    product      TEXT,
    model        TEXT,
    category     TEXT,
    confidence   REAL,
    embedding    vector(512),                            -- Chinese-CLIP ViT-B-16
    thumb_path   TEXT
);

-- 3b. 帧表索引
CREATE INDEX IF NOT EXISTS idx_frames_brand     ON frames (brand);
CREATE INDEX IF NOT EXISTS idx_frames_category  ON frames (category);
CREATE INDEX IF NOT EXISTS idx_frames_model     ON frames (model);
CREATE INDEX IF NOT EXISTS idx_frames_brand_cat ON frames (brand, category);

-- HNSW 向量索引（pgvector 0.5+ 支持；插入数据后再建）
-- cos: CREATE INDEX idx_frames_embedding ON frames USING hnsw (embedding vector_cosine_ops);
-- l2:  CREATE INDEX idx_frames_embedding ON frames USING hnsw (embedding vector_l2_ops);
