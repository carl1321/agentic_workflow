-- 为 node_tasks 表添加超时和重试相关列
-- 此脚本用于支持节点级别的超时检测和重试机制

-- 1. 添加 timeout_seconds 列（节点超时时间，单位：秒）
ALTER TABLE node_tasks 
ADD COLUMN IF NOT EXISTS timeout_seconds INTEGER;

-- 2. 添加 retry_delay_seconds 列（重试延迟时间，单位：秒）
ALTER TABLE node_tasks 
ADD COLUMN IF NOT EXISTS retry_delay_seconds INTEGER;

-- 3. 添加注释
COMMENT ON COLUMN node_tasks.timeout_seconds IS '节点超时时间（秒），从节点配置中获取，如果为空则使用默认值';
COMMENT ON COLUMN node_tasks.retry_delay_seconds IS '重试延迟时间（秒），用于控制重试间隔';

-- 4. 验证列是否添加成功
SELECT 
    column_name, 
    data_type, 
    is_nullable
FROM information_schema.columns 
WHERE table_name = 'node_tasks' 
    AND column_name IN ('timeout_seconds', 'retry_delay_seconds')
ORDER BY column_name;

