# 长期计划任务验收流程设计

本文档描述长期计划（long plan）中「任务完成 → 验收 → 状态同步」的设计原则、关键技术点，以及当前实现的对齐情况。

---

## 一、关键技术点

| 技术点 | 含义 | 当前实现 |
|--------|------|----------|
| **消息队列** | 使用 Redis/Celery 等传递任务完成事件 | 单机 MVP：调度器与 Worker 同进程，任务完成后直接函数调用协调器验收，未引入外部消息队列。扩展多 Worker 时可引入 Redis/Celery 发布「任务完成」事件。 |
| **回调注册** | 协调器向调度器注册「任务完成回调」 | 以「验收函数」形式体现：Worker 在执行器返回成功后，主动调用 `coordinator.evaluate_task_output(...)`，等价于内联的「任务完成回调」。 |
| **状态同步** | 验收后立即更新数据库，防止重复触发 | 验收通过/不通过后均立即：`update_task_status`、`append_plan_log`、`append_spec_milestone`；验收不通过时本 tick 直接 return，不推进下游，避免重复触发与状态不一致。 |
| **错误传播** | Worker 的异常必须包含足够信息供协调器决策 | 验收拒绝时，将 `reason` 写入任务 `error` 字段及日志 payload；日志中增加「影响范围」（见下文）。执行器执行失败时目前将 plan 标为 failed，未再经协调器评估，可后续扩展「执行失败」的协调器决策（如重试、调整计划）。 |

---

## 二、设计原则总结

| 原则 | 含义 | 当前实现 |
|------|------|----------|
| **事件驱动** | 验收由「任务完成」事件触发，而非定时轮询 | 验收仅在「执行器执行成功」之后、同一 tick 内触发，由任务完成这一事实驱动，无轮询。 |
| **串行保障** | 验收完成前不启动下游任务，确保状态一致性 | 验收不通过时，任务被标为 failed 且本 tick 立即 return，不会执行「推进 pending → ready」或领取下一个任务，因此下游任务不会启动。 |
| **记忆优先** | 每次验收都更新 spec.txt（或等效数据库），沉淀经验 | 每次验收（通过/不通过）均调用 `append_spec_milestone(plan_id, ...)`，将结果写入 spec 的「里程碑与经验」部分，供后续任务与规划参考。 |
| **用户透明** | 验收结果（特别是失败）需明确告知用户影响范围 | 通过 `append_plan_log` 发送 `task_accepted` / `task_rejected` 事件；`task_rejected` 的 payload 中包含 `reason`、`impactScope`（受阻塞的下游任务名称列表）及对应 bullets，便于前端展示。 |

---

## 三、实现要点索引

- **验收提示词**：`src/prompts/long_plan_accept.md`
- **协调器验收**：`src/server/plan/coordinator.py::evaluate_task_output`
- **Spec 里程碑**：`src/server/plan/spec.py::append_spec_milestone`
- **Worker 集成**：`src/server/plan/worker.py::tick`（执行 → 验收 → 状态更新 → 日志 / spec 写入）
- **终止与取消**：`src/server/plan/routes.py::terminate_plan_endpoint`（终止计划并取消未执行任务，写日志/spec；任务验收失败时在 `worker.py` 对下游未启动任务置为 `canceled`）

---

## 四、后续可扩展

- 引入 Redis/Celery：将「任务完成」作为事件发布，多个 Worker 消费，协调器以订阅者身份验收。
- 执行失败时的协调器决策：对「执行器抛错」也调用协调器（如 `evaluate_task_failure`），返回是否重试、是否调整计划等，再写回状态与 spec。
