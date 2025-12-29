-- 删除执行中的工作流任务脚本
-- 此脚本会删除所有状态为 'queued' 或 'running' 的工作流运行记录
-- 以及相关的节点任务和运行日志

-- 1. 查看当前执行中的任务数量
SELECT 
    status,
    COUNT(*) as count
FROM workflow_runs
WHERE status IN ('queued', 'running')
GROUP BY status;

-- 2. 查看将要删除的任务详情（可选，用于确认）
SELECT 
    id,
    workflow_id,
    status,
    created_at,
    started_at,
    heartbeat_at
FROM workflow_runs
WHERE status IN ('queued', 'running')
ORDER BY created_at DESC;

-- 3. 删除相关的节点任务（node_tasks）
-- 注意：如果表有外键约束，可能需要先删除子表数据
DELETE FROM node_tasks
WHERE run_id IN (
    SELECT id FROM workflow_runs
    WHERE status IN ('queued', 'running')
);

-- 4. 删除相关的运行日志（run_logs）
DELETE FROM run_logs
WHERE run_id IN (
    SELECT id FROM workflow_runs
    WHERE status IN ('queued', 'running')
);

-- 5. 删除执行中的工作流运行记录
DELETE FROM workflow_runs
WHERE status IN ('queued', 'running');

-- 6. 验证删除结果
SELECT 
    status,
    COUNT(*) as count
FROM workflow_runs
GROUP BY status
ORDER BY status;

