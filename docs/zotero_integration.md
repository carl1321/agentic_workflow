# Zotero 文献库集成说明

本文档说明如何配置和使用 Zotero 技能（`skills/zotero`）及其工具 `zotero_literature_tool`。

## 配置

### conf.yaml

在 `conf.yaml` 中新增 ZOTERO 配置块：

```yaml
ZOTERO:
  enabled: true
  library_id: ""        # 个人库：从 zotero.org/settings 获取
                        # 群组库：从群组页面 URL 获取
  library_type: "user"  # user | group
  api_key: ""           # 在 zotero.org/settings/keys 创建，需勾选 library read
```

### 环境变量

以下环境变量可覆盖 YAML 配置：

- `ZOTERO_LIBRARY_ID`
- `ZOTERO_API_KEY`
- `ZOTERO_LIBRARY_TYPE`

## 工具说明

工具名：`zotero_literature_tool`，通过 `action` 参数切换功能。

### action 取值

| action      | 必填参数      | 可选参数                                   | 说明                       |
|-------------|---------------|--------------------------------------------|----------------------------|
| search      | query         | item_type, limit                           | 搜索库内文献，返回元数据列表 |
| get_detail  | item_key      | attachment_key                             | 获取文献详情与附件；提供 attachment_key 时尝试获取全文 |
| analyze     | item_keys     | analysis_type, custom_prompt               | 基于元数据与可选全文进行 LLM 分析 |

### analysis_type 取值

- `summary`：简要总结
- `compare`：对比分析
- `key_findings`：提炼要点
- `custom`：自定义分析，需配合 `custom_prompt`

### 示例调用

**搜索：**

```json
{
  "action": "search",
  "query": "machine learning",
  "limit": 20
}
```

**获取详情与全文：**

```json
{
  "action": "get_detail",
  "item_key": "ABC123",
  "attachment_key": "XYZ789"
}
```

**分析：**

```json
{
  "action": "analyze",
  "item_keys": "ABC123,DEF456",
  "analysis_type": "compare"
}
```

## 示例工作流

`skills/zotero/examples/zotero_workflow_example.json` 展示典型流程：

1. Start：输入搜索关键词
2. Tool (search)：在 Zotero 中搜索
3. LLM：选取第一项文献的 key
4. Tool (get_detail)：获取文献详情
5. Tool (analyze)：进行总结分析
6. End

可通过工作流导入功能加载该示例，或在工作流编辑器中手动搭建。

## 与其他工具的配合

- **literature_search_tool**：检索开放文献（如 Semantic Scholar），Zotero 侧重本地/私有库
- **pdf_crawler_tool**：按 URL 抓取 PDF；当 Zotero 附件无全文索引时，可提供 URL 供 pdf_crawler 抓取
- **data_extraction_tool**：从文本做结构化抽取，可与 zotero analyze 结果配合

## 依赖

- `pyzotero`：Zotero API 封装，已在 `pyproject.toml` 中声明
