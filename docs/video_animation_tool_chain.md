# 视频动画制作全链路工具清单

基于修仙 AI 动画项目执行经验，从剧本到成片所需的核心工具与目录规范，以及在本项目中的对应实现。

---

## 一、阶段与工具映射

### 第一阶段：策划与预生产

| 工具类别     | 具体实现               | 用途示例                     | 本项目对应 |
|--------------|------------------------|------------------------------|------------|
| 信息搜索     | 内置搜索工具           | 竞品调研、热点挖掘、素材参考 | `web_search`、`crawl_tool`、`literature_search_tool` |
| 选题库管理   | create_file / edit_file | 维护 data/选题库.txt 等      | `create_file_tool`、`edit_file_tool` |
| 分镜剧本     | Markdown 文档          | 撰写 分镜剧本.md             | `create_file_tool` 写入 `outputs/` 或 `docs/` |

### 第二阶段：视觉素材生成

| 工具类别       | 具体实现        | 用途示例                         | 本项目对应 |
|----------------|-----------------|----------------------------------|------------|
| 角色/场景设计  | 文生图（内置）  | 动漫风格角色立绘、场景背景       | 需接入文生图 API 或使用工作流节点 |
| 分镜可视化     | PPT 技能        | 分镜转 PPT 预览                  | `ppt_generate_tool`、`/api/ppt/generate` |
| 图表辅助       | drawio 等       | 剧情流程图、角色关系图           | 可通过 `python_repl_tool` 或脚本生成 |

### 第三阶段：动画片段生成

| 工具类别       | 具体实现                    | 用途示例                     | 本项目对应 |
|----------------|-----------------------------|------------------------------|------------|
| 云端视频 API   | 通义万相 wan2.6-i2v-flash   | 5 秒动画片段                 | `video_generation_tool`（可配置 endpoint） |
| 本地模型 API   | 自定义端点（如 H20 WAN2.2） | 自部署生成 .mp4              | 同上，在 conf 中配置 `VIDEO_GENERATION` |
| 请求脚本模板   | create_file 生成 Python 脚本 | 封装 API 调用、轮询、下载     | `create_file_tool` 写入 `src/` 下脚本 |

### 第四阶段：后期合成

| 工具类别     | 具体实现              | 用途示例               | 本项目对应 |
|--------------|-----------------------|------------------------|------------|
| 音频生成     | 播客/配音             | 对话片段配音           | `tts_tool`、`/api/podcast/generate` |
| 字幕制作     | SRT                   | 对话转字幕时序         | `create_file_tool` 生成 .srt |
| 视频拼接     | ffmpeg concat         | 多 MP4 合并            | `ffmpeg_tool`（concat） |
| 音画合成     | ffmpeg                | 视频轨+音频轨+背景乐   | `ffmpeg_tool`（merge_av） |

### 第五阶段：数据分析与优化

| 工具类别     | 具体实现           | 用途示例               | 本项目对应 |
|--------------|--------------------|------------------------|------------|
| 数据整理     | Excel/CSV 处理      | 成本日志、播放数据     | `python_repl_tool` 或后续 `excel_tool` |
| 可视化报告   | 图表               | 成本趋势、质量评分     | 同上或 `python_repl_tool` 调用绘图库 |
| 报告生成     | Markdown + 图表嵌入 | 周复盘、技术验证报告   | `create_file_tool` + 上述工具 |

---

## 二、文件系统与目录规范

| 目录        | 用途                     | 示例文件 |
|-------------|--------------------------|----------|
| `outputs/`  | 最终产物（主动展示）     | `outputs/第一集/废土修仙_第一集.mp4`、`outputs/plans/{plan_id}/` |
| `temp/`     | 中间文件（缓存、日志）   | `temp/第一集/subtitles.srt`、`temp/拼接测试/cost_log.txt` |
| `src/`      | 可执行脚本（Python/bash）| `src/h20_api_test.py`、`src/install_deps.py` |
| `data/`     | 结构化数据               | `data/选题库.txt`、`data/shared_state/state.db` |
| `docs/`     | 文档资料                 | `docs/API接口说明.md`、`docs/分镜剧本.md` |

计划执行器（长期计划）默认工作目录为 `outputs/plans/{plan_id}/`，shell 类型任务在该目录下执行，产物可登记为 artifact。

---

## 三、配置说明

### 视频生成 API（conf.yaml）

```yaml
# 可选。不配置则 video_generation_tool 不可用或需显式传 endpoint
VIDEO_GENERATION:
  url: "http://122.193.22.114:8888/v1/video/generations"  # 或通义万相等
  api_key: "sk-xxx"
  size: "1280*720"
  timeout: 120
  poll_interval: 5
  max_wait: 600
```

### 文件写入安全

`create_file_tool` / `edit_file_tool` 仅允许在以下根目录下写入（或通过配置指定）：

- `outputs/`
- `temp/`
- `data/`
- `docs/`
- `src/`

路径不得包含 `..`，且需在项目根下。

---

## 四、自动化 Agent 开发建议

- **编排层（PMO）**：目标澄清、任务拆解、调度、验收 —— 对应本项目的长期计划（澄清 + planner + 调度器 + 执行器）。
- **执行层（Worker）**：集成上述工具，按指令调用 API、生成素材、合成视频 —— 对应 `TOOL_REGISTRY` 中的工具与计划任务的 `executor_type: llm | shell`。
- **状态管理**：可用 SQLite（如 `data/shared_state/state.db`）记录去重、游标、生成历史。
- **错误处理**：API 超时重试、片段生成失败降级、文件存在性校验，建议在调用工具的工作流或脚本中实现。

---

## 五、工具名与 API 速查

| 能力           | 工具名 / 接口                     | 说明 |
|----------------|-----------------------------------|------|
| 网页搜索       | `web_search`                      | 关键词 → 摘要/链接（需传入 query） |
| 爬取 URL       | `crawl_tool`                      | URL → 正文 Markdown |
| 文献搜索       | `literature_search_tool`          | 学术/文献检索 |
| 写文件         | `create_file_tool`                | path + content，限定根目录 |
| 追加/覆盖文件  | `edit_file_tool`                  | path + content + append |
| PPT 生成       | `ppt_generate_tool` 或 POST /api/ppt/generate | 内容 → .pptx |
| 视频生成       | `video_generation_tool`           | prompt + 可选图 → 轮询下载 .mp4 |
| 视频拼接       | `ffmpeg_tool` (action=concat)     | 片段列表 → 合成 .mp4 |
| 音画合成       | `ffmpeg_tool` (action=merge_av)   | 视频 + 音频 → 最终 .mp4 |
| TTS/配音       | `tts_tool`、POST /api/tts、/api/podcast/generate | 文本 → 音频 |
| 执行代码       | `python_repl_tool`                | 脚本执行、数据处理 |
| 计划内 Shell   | 长期计划任务 executor_type: shell | 任意 bash（含 ffmpeg、curl） |
