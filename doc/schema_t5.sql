-- 数据库架构脚本 (Database Schema Script)
-- Generated based on doc/sql_t5.md

-- 1. 资产分类 (assets_category)
CREATE TABLE IF NOT EXISTS assets_category (
    class_id BIGSERIAL PRIMARY KEY,
    asset_class VARCHAR(255),
    parent_id BIGINT,
    CONSTRAINT fk_assets_category_parent FOREIGN KEY (parent_id) REFERENCES assets_category(class_id)
);

CREATE INDEX IF NOT EXISTS idx_assets_category_class ON assets_category(asset_class);
CREATE INDEX IF NOT EXISTS idx_assets_category_parent ON assets_category(parent_id);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_parent_class 
    ON assets_category (asset_class) 
    WHERE parent_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uniq_child_class 
    ON assets_category (parent_id, asset_class) 
    WHERE parent_id IS NOT NULL;

-- 2. 资产主数据 (assets)
CREATE TABLE IF NOT EXISTS assets (
    asset_id BIGSERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    user_id BIGINT,
    class_id BIGINT,
    status BOOLEAN NOT NULL,
    code_value VARCHAR(128) NOT NULL,
    image VARCHAR(1024) NOT NULL,
    purpose VARCHAR(255),
    unit_value NUMERIC(14,2),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_assets_class FOREIGN KEY (class_id) REFERENCES assets_category(class_id)
);

CREATE INDEX IF NOT EXISTS idx_assets_class_status ON assets(class_id, status);
CREATE INDEX IF NOT EXISTS idx_assets_user_id ON assets(user_id);
CREATE INDEX IF NOT EXISTS idx_assets_code_value ON assets(code_value);
CREATE INDEX IF NOT EXISTS idx_assets_status ON assets(status);

-- 3. 人员流动记录 (presence_logs)
CREATE TABLE IF NOT EXISTS presence_logs (
    log_id BIGSERIAL PRIMARY KEY,
    user_id BIGINT,
    event_id BIGINT,
    person_image VARCHAR(1024),
    zone VARCHAR(64),
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_presence_logs_user_start ON presence_logs(user_id, start_time);
CREATE INDEX IF NOT EXISTS idx_presence_logs_event_id ON presence_logs(event_id);
CREATE INDEX IF NOT EXISTS idx_presence_logs_start_time ON presence_logs(start_time);

-- 4. 事件集合 (event_set)
CREATE TABLE IF NOT EXISTS event_set (
    event_id BIGSERIAL PRIMARY KEY,
    candidate_asset_ids JSONB,
    candidate_user_ids JSONB,
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_event_set_start_time ON event_set(start_time);

-- 5. 资产变动事实 (assets_event)
CREATE TABLE IF NOT EXISTS assets_event (
    confirm_id BIGSERIAL PRIMARY KEY,
    asset_id BIGINT,
    event_id BIGINT,
    event_type BOOLEAN NOT NULL,
    status VARCHAR(64),
    zone VARCHAR(64),
    remark VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_assets_event_asset FOREIGN KEY (asset_id) REFERENCES assets(asset_id)
);

CREATE INDEX IF NOT EXISTS idx_assets_event_asset_id ON assets_event(asset_id);
CREATE INDEX IF NOT EXISTS idx_assets_event_status ON assets_event(status);
CREATE INDEX IF NOT EXISTS idx_assets_event_id ON assets_event(event_id);
