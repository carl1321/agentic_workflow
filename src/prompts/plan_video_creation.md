---
CURRENT_TIME: {{ CURRENT_TIME }}
---

# 视频/动画创作类任务规划（专业提示词）

根据用户目标与澄清要求，按「视频动画制作全链路」四阶段规划可执行任务。每个任务会生成一个文件（Markdown、JSON 或媒体），后续任务可依赖前面任务的产物。所有产物存放在同一目录下，引用依赖时只写文件名即可。

## 用户目标
{{ objective }}

## 用户要求（澄清结果）
{{ requirements }}

## 四阶段与可选工具/产物

- **第一阶段：策划与预生产** — 信息搜索、选题库（data/选题库.txt）、分镜剧本（分镜剧本.md）；工具示例：web_search、crawl_tool、create_file_tool、edit_file_tool。
- **第二阶段：视觉素材生成** — 角色/场景设计（文生图）、分镜可视化（create-ppt）、图表辅助（drawio/剧情与角色关系图）；工具示例：文生图、ppt_generate_tool。
- **第三阶段：动画片段生成** — 云端视频 API（如本地模型 API、或 create_file 生成 Python 调用脚本（含 API 调用、轮询、下载）；工具示例：video_generation_tool、create_file_tool。
- **第四阶段：后期合成** — 音频生成（播客/配音）、字幕（SRT）、视频拼接（ffmpeg concat）、音画合成（ffmpeg merge_av）；工具示例：tts_tool、create_file_tool 生成 .srt、ffmpeg_tool。


## 输出格式
请输出一个 JSON 数组，且只输出该数组，不要其他说明或 Markdown 代码块。每个元素表示一个任务：

{
  "name": "任务名称（简短）",
  "output_relpath": "产出文件名；图片用 .png/.jpg，视频用 .mp4，文本用 .md/.json（如 positioning.md、tiger_bathing.png、ep01.mp4）",
  "prompt": "执行该任务时发给大模型的完整提示词。引用依赖文件时只写文件名。严格根据用户目标与澄清撰写，不写死题材。",
  "depends_on": ["依赖的产出文件名列表"]
}

## 要求
- 任务顺序和依赖合理，符合四阶段逻辑；被依赖的文件对应的任务必须先执行。
- 第一个任务通常为定位/方案/分镜剧本等，depends_on 为 []；后续按阶段依赖前序产物。
- **output_relpath 后缀必须与产物类型一致**：文生图/图片任务必须用 .png 或 .jpg（如 role_scene.png），视频任务用 .mp4，文本/分镜用 .md、.json。禁止将图片任务产出写成 .json。
- 只输出 JSON 数组，不要 ```json 或任何前后文字。
