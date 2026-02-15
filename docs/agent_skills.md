# Agent Skills 集成说明

本项目集成了 [Agent Skills](https://agentskills.io) 开放标准，支持以「技能目录 + 可选工具」方式扩展能力。新工具只需提供 `SKILL.md`（及可选的 `tools.py`），放入配置的技能目录即可被自动发现并注册，无需修改 `app.py` 或 `src/tools/`。

## 配置

在 `conf.yaml` 中增加（可选，不配置时默认启用并扫描 `skills` 目录）：

```yaml
skills:
  enabled: true
  directories:
    - skills
```

- `enabled`: 是否启用技能发现与加载，默认 `true`
- `directories`: 技能根目录列表（相对于项目根），默认 `["skills"]`

## 技能目录结构

每个技能是一个子目录，目录名需与 `SKILL.md` 中 frontmatter 的 `name` 一致：

```
skills/
└── my-skill/
    ├── SKILL.md          # 必选：YAML frontmatter + Markdown 正文
    ├── tools.py          # 可选：该技能提供的工具（见下方约定）
    ├── scripts/          # 可选：可执行脚本
    ├── references/      # 可选：参考文档
    └── assets/           # 可选：静态资源
```

### SKILL.md 格式

- **必填 frontmatter**：`name`、`description`
- **可选**：`license`、`compatibility`、`metadata`、`allowed-tools`

示例：

```yaml
---
name: pdf-processing
description: Extract text and tables from PDF files. Use when the user mentions PDFs or document extraction.
metadata:
  tools: "pdf_crawler_tool"
---
# PDF Processing
...
```

通过 `metadata.tools` 可声明该技能关联的已有工具名（空格分隔），与 `TOOL_REGISTRY` 中的 key 一致，用于按技能过滤或展示。

## 新增带 SKILL.md 的新工具（无缝集成）

若希望新工具完全以技能形式接入，无需改 `app.py` 或 `src/tools/`：

1. 在 `skills/` 下新建目录，例如 `skills/my-capability/`。
2. 在该目录下创建 `SKILL.md`（必选），按上述格式填写 frontmatter 和正文。
3. 可选：在同一目录下创建 `tools.py`（或 `tools/__init__.py`），按下列约定暴露 LangChain 工具。

### tools.py 约定

- **位置**：技能目录下的 `tools.py` 或 `tools/__init__.py`。
- **暴露方式**（二选一）：
  - 定义 `def get_tools() -> list`，返回 `list[BaseTool]`（LangChain 兼容工具实例）。
  - 或定义 `TOOLS = [tool1, tool2, ...]` 列表。
- **注册**：服务启动时会扫描所有技能目录，对存在上述入口的目录动态 import，将得到的工具以 `tool.name` 为 key 注册到 `TOOL_REGISTRY`；重名时先到先得并打日志。
- **关联**：同一技能下的工具会自动与该技能的 `name` 关联，用于 API 与按技能过滤。

示例 `skills/my-capability/tools.py`：

```python
from langchain_core.tools import tool

@tool
def my_tool(query: str) -> str:
    """Do something with query."""
    return "result"

def get_tools():
    return [my_tool]
```

或：

```python
TOOLS = [my_tool]
```

重启服务后，该工具会出现在工作流可用工具列表和 agent 中。

## API

- **GET /api/skills**：返回所有技能的元数据。查询参数 `?include_tools=1` 时，每个技能会附带 `tools` 列表（工具名）。
- **GET /api/skills/{skill_name}/content**：返回该技能的 SKILL.md 全文（含正文），用于 agent 按需加载详细指令。`skill_name` 仅允许小写字母、数字和连字符。

## 与现有组件的集成

- **TOOL_REGISTRY**：内置工具仍在 `src/server/app.py` 中注册；技能目录内通过 `tools.py` 加载的工具在服务启动时合并进同一 `TOOL_REGISTRY`。
- **工作流**：`/api/workflow/tools` 从 `TOOL_REGISTRY` 列举工具，技能注册的工具会自动包含在内。
- **Planner / Researcher**：系统 prompt 中会注入当前可用技能列表（仅 name + description），模型可根据任务选用技能；完整指令可通过 `/api/skills/{skill_name}/content` 按需加载。

## 参考

- [Agent Skills 规范](https://agentskills.io/specification)
- [集成指南](https://agentskills.io/integrate-skills)
