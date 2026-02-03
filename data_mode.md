
# 仓储资产数据模型

## 设计目标
- 统一资产主数据与出入库事件记录
- 采用时间戳与状态字段以满足审计与追溯
- 关键业务字段建立唯一约束与索引

## 表结构

### assets
资产主数据表，记录资产的基础信息与状态。

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | BIGINT | PK | 资产主键 |
| name | VARCHAR(255) | NOT NULL | 资产名称 |
| model | VARCHAR(255) |  | 型号 |
| spec | VARCHAR(255) |  | 规格 |
| category_id | BIGINT | FK | 分类维度 |
| supplier | VARCHAR(255) |  | 供应商 |
| serial_number | VARCHAR(128) |  | 出厂序列号 |
| location | VARCHAR(255) |  | 存放位置 |
| owner_department | VARCHAR(255) |  | 归属部门 |
| status | VARCHAR(32) | NOT NULL | 当前状态 |
| purchase_date | DATE |  | 采购日期 |
| warranty_expire_date | DATE |  | 质保到期 |
| purpose | VARCHAR(255) |  | 用途 |
| unit_value | NUMERIC(14,2) |  | 单价 |
| created_at | TIMESTAMPTZ | NOT NULL | 创建时间 |
| updated_at | TIMESTAMPTZ | NOT NULL | 更新时间 |

索引
- idx_assets_category_status (category_id, status)

### access_logs
出入库事件表，记录资产进出、设备信息。

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | BIGINT | PK | 事件主键 |
| asset_code_id | BIGINT | NOT NULL, FK | 资产编码 |
| snapshot_path | VARCHAR(1024) |  | 图片路径 |
| actor_type | VARCHAR(32) |  | 记录主体类型 |
| actor_id | VARCHAR(64) |  | 记录主体标识 |
| actor_name | VARCHAR(255) |  | 记录主体名称 |
| source_system | VARCHAR(64) |  | 来源系统 |
| event_time | TIMESTAMPTZ | NOT NULL | 事件时间 |
| device_id | VARCHAR(255) |  | 设备标识 |
| created_at | TIMESTAMPTZ | NOT NULL | 创建时间 |

索引
- idx_access_logs_code_time (asset_code_id, event_time)
- idx_access_logs_event_time (event_time)

### asset_codes
资产编码表，适配RFID、二维码等多编码场景。

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | BIGINT | PK | 编码主键 |
| asset_id | BIGINT | NOT NULL, FK | 资产标识 |
| code_type | VARCHAR(64) | NOT NULL | 编码类型 |
| code_value | VARCHAR(128) | NOT NULL | 编码值 |
| is_primary | BOOLEAN | NOT NULL | 是否主编码 |
| created_at | TIMESTAMPTZ | NOT NULL | 创建时间 |
| updated_at | TIMESTAMPTZ | NOT NULL | 更新时间 |

索引
- idx_asset_codes_asset_id (asset_id)
- idx_asset_codes_type_value (code_type, code_value)
- idx_asset_codes_code_value (code_value)

### presence_logs
人员流动记录表，用于视频监控记录人员出入与出现时间。

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | BIGINT | PK | 记录主键 |
| subject_type | VARCHAR(32) |  | 主体类型 |
| subject_id | VARCHAR(64) |  | 主体标识 |
| subject_name | VARCHAR(255) |  | 主体名称 |
| source_system | VARCHAR(64) |  | 来源系统 |
| device_id | VARCHAR(255) |  | 设备标识 |
| zone | VARCHAR(255) |  | 区域 |
| snapshot_path | VARCHAR(1024) |  | 抓拍图片 |
| confidence | NUMERIC(5,2) |  | 识别置信度 |
| event_time | TIMESTAMPTZ | NOT NULL | 出现时间 |
| created_at | TIMESTAMPTZ | NOT NULL | 创建时间 |

索引
- idx_presence_logs_subject_time (subject_id, event_time)
- idx_presence_logs_device_time (device_id, event_time)

### asset_categories
分类维度表，统一资产分类层级。

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | BIGINT | PK | 分类主键 |
| code | VARCHAR(64) | NOT NULL, UNIQUE | 分类编码 |
| name | VARCHAR(255) | NOT NULL, UNIQUE | 分类名称 |
| parent_id | BIGINT | FK | 上级分类 |
| is_active | BOOLEAN | NOT NULL | 是否启用 |
| created_at | TIMESTAMPTZ | NOT NULL | 创建时间 |
| updated_at | TIMESTAMPTZ | NOT NULL | 更新时间 |

索引
- idx_asset_categories_parent_id (parent_id)

## 关系约束
- assets.category_id 外键引用 asset_categories.id
- asset_categories.parent_id 自引用 asset_categories.id
- access_logs.asset_code_id 外键引用 asset_codes.id
- asset_codes.asset_id 外键引用 assets.id

## 维护策略
- assets.updated_at 在更新时自动刷新
- asset_categories.updated_at 在更新时自动刷新
- asset_codes.updated_at 在更新时自动刷新
