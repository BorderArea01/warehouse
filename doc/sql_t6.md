# 数据库设计文档 (Database Design)

### 1. 资产分类 (assets_category)
记录资产的分类信息，支持层级结构。

| 字段 | 类型 | 约束 | 说明 |
| :--- | :--- | :--- | :--- |
| class_id | BIGSERIAL | PK | 资产分类主键 (自增) |
| asset_class | VARCHAR(255) | | 资产分类名称 |
| parent_id | BIGINT | FK, Nullable | 父分类 ID |

**索引 (Indexes)**:
- `idx_assets_category_class` (`asset_class`)
- `idx_assets_category_parent` (`parent_id`)

---

### 2. 资产主数据 (assets)
记录资产的基础信息与状态。

| 字段 | 类型 | 约束 | 说明 |
| :--- | :--- | :--- | :--- |
| asset_id | BIGSERIAL | PK | 资产主键 (自增) |
| name | VARCHAR(255) | NOT NULL | 资产名称 |
| user_id | BIGINT | | 持有者 ID |
| class_id | BIGINT | FK | 分类维度 ID |
| status | VARCHAR(32) | NOT NULL | 当前状态 |
| code_value | VARCHAR(128) | NOT NULL | 码值 (RFID/条码) |
| image | VARCHAR(1024) | NOT NULL | 图片快照 URL |
| purpose | VARCHAR(255) | | 用途 |
| unit_value | NUMERIC(14,2) | | 单价 |
| updated_at | TIMESTAMPTZ | NOT NULL | 更新时间 |

**索引 (Indexes)**:
- `idx_assets_class_status` (`class_id`, `status`)
- `idx_assets_user_id` (`user_id`)
- `idx_assets_code_value` (`code_value`)
- `idx_assets_status` (`status`)

---

### 3. 出入库记录 (access_logs)
记录资产进出、设备信息。

| 字段 | 类型 | 约束 | 说明 |
| :--- | :--- | :--- | :--- |
| log_id | BIGSERIAL | PK | 记录主键 (自增) |
| asset_id | BIGINT | FK, NOT NULL | 资产主键 |
| event_id | BIGINT | | 关联事件主键 |
| event_time | TIMESTAMPTZ | NOT NULL | 事件发生时间 |
| event_type | BOOLEAN | NOT NULL | 出入库标识 (TRUE: 在库/入库, FALSE: 出库) |
| created_at | TIMESTAMPTZ | NOT NULL | 创建时间 |

**索引 (Indexes)**:
- `idx_access_logs_asset_time` (`asset_id`, `event_time`)
- `idx_access_logs_event_time` (`event_time`)
- `idx_access_logs_event_id` (`event_id`)

---

### 4. 人员流动记录 (presence_logs)
用于视频监控记录人员出入与出现时间。

| 字段 | 类型 | 约束 | 说明 |
| :--- | :--- | :--- | :--- |
| log_id | BIGSERIAL | PK | 记录主键 (自增) |
| user_id | BIGINT | | 用户主键 |
| event_id | BIGINT | | 关联事件主键 |
| person_image | VARCHAR(1024) | | 用户快照 URL |
| zone | VARCHAR(64) | | 出现区域 |
| start_time | TIMESTAMPTZ | | 开始时间 |
| end_time | TIMESTAMPTZ | | 结束时间 |
| created_at | TIMESTAMPTZ | NOT NULL | 创建时间 |

**索引 (Indexes)**:
- `idx_presence_logs_user_start` (`user_id`, `start_time`)
- `idx_presence_logs_event_id` (`event_id`)
- `idx_presence_logs_start_time` (`start_time`)

---

### 5. 事件集合 (event_set)
用于各个日志的汇总事件。

| 字段 | 类型 | 约束 | 说明 |
| :--- | :--- | :--- | :--- |
| event_id | BIGSERIAL | PK | 事实主键 (自增) |
| candidate_asset_ids | JSONB | | 候选资产 IDs |
| candidate_user_ids | JSONB | | 候选人员 IDs |
| start_time | TIMESTAMPTZ | | 开始时间 |
| end_time | TIMESTAMPTZ | | 结束时间 |
| created_at | TIMESTAMPTZ | NOT NULL | 创建时间 |

**索引 (Indexes)**:
- `idx_event_set_start_time` (`start_time`)

---

### 6. 确认事件 (confirm_event)
用于记录人工确认或系统自动确认的事件状态。

| 字段 | 类型 | 约束 | 说明 |
| :--- | :--- | :--- | :--- |
| confirm_id | BIGSERIAL | PK | 确认事件主键 (自增) |
| asset_id | BIGINT | FK | 资产主键 |
| user_id | BIGINT | | 用户主键 |
| event_time | TIMESTAMPTZ | | 事件时间 |
| status | VARCHAR(64) | | 确认单状态 (完成、待确认、异常) |
| zone | VARCHAR(64) | | 发生地点 |
| remark | VARCHAR(64) | | 备注 |
| created_at | TIMESTAMPTZ | NOT NULL | 创建时间 |

**索引 (Indexes)**:
- `idx_confirm_event_asset_time` (`asset_id`, `event_time`)
- `idx_confirm_event_user` (`user_id`)
- `idx_confirm_event_status` (`status`)
- `idx_confirm_event_time` (`event_time`)
