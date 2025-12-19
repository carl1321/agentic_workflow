# AgenticWorkflow

一个基于多智能体架构的 AI 研究代理系统，集成了对话聊天、知识库管理、工具箱和工作流等功能。

## ✨ 主要特性

- 🤖 **多智能体架构** - 基于 LangGraph 的 Coordinator、Planner、Researcher、Coder、Reporter 多智能体协作
- 💬 **智能对话** - 支持深度思考、背景调研、多轮澄清的智能对话系统
- 📚 **知识库管理** - 集成 RAGFlow、Milvus、MCP 等多种 RAG 提供者
- 🛠️ **工具箱** - 丰富的工具集，包括搜索引擎、网络爬虫、Python 执行、MCP 服务等
- 👥 **用户管理系统** - 完整的 RBAC 权限控制系统，支持用户、角色、权限、菜单、单位、部门管理
- 🎙️ **播客生成** - 从研究报告自动生成播客音频
- 🔄 **工作流支持** - 可视化工作流编辑器（基于 ReactFlow）
- 🌐 **多语言支持** - 支持中英文界面

## 🏗️ 技术架构

### 后端
- **框架**: FastAPI
- **语言**: Python 3.12+
- **数据库**: PostgreSQL (用于对话持久化和用户管理)
- **AI 框架**: LangChain + LangGraph
- **包管理**: uv

### 前端
- **框架**: Next.js 15+ (App Router)
- **语言**: TypeScript
- **UI 库**: Radix UI + Tailwind CSS
- **状态管理**: Zustand
- **包管理**: pnpm

## 📋 前置要求

- Python 3.12+
- Node.js 22+
- PostgreSQL 14+ (可选，用于数据持久化)
- uv (Python 包管理工具)
- pnpm (Node.js 包管理工具)

## 🚀 快速开始

### 1. 克隆仓库

```bash
git clone <repository-url>
cd AgenticWorkflow
```

### 2. 安装依赖

```bash
# 安装 Python 依赖
uv sync

# 安装前端依赖
cd web
pnpm install
cd ..
```

### 3. 配置

复制配置文件模板并编辑：

```bash
cp conf.yaml.example conf.yaml
```

编辑 `conf.yaml`，配置以下内容：

- **LLM 模型配置** (`BASIC_MODEL`, `MODELS`): 配置你的 API 密钥和模型信息
- **搜索引擎** (`ENV.TAVILY_API_KEY`, `ENV.BRAVE_API_KEY`): 配置搜索引擎 API 密钥
- **RAG 提供者** (`ENV.RAG_PROVIDER`, `ENV.RAGFLOW_API_URL`): 配置知识库服务
- **数据库连接** (`ENV.LANGGRAPH_CHECKPOINT_DB_URL`): 配置 PostgreSQL 连接
- **其他环境变量**: 在 `ENV` 部分配置所有必要的环境变量

详细配置请参考 [配置指南](docs/configuration_guide.md)

### 4. 初始化数据库

如果使用 PostgreSQL 进行数据持久化（推荐）：

```bash
# 确保 PostgreSQL 服务正在运行
# macOS: brew services start postgresql
# Linux: sudo systemctl start postgresql

# 运行数据库初始化脚本
uv run scripts/init_database.py
```

这个脚本会：
- 创建 `agenticworkflow` 数据库（如果不存在）
- 初始化 LangGraph checkpoint 表结构
- 创建 `chat_streams` 表用于对话历史
- 初始化 RBAC 系统表（users, roles, permissions, menus, organizations, departments）

### 5. 启动服务

#### 方式一：使用启动脚本（推荐）

```bash
# 开发模式（自动重载）
./bootstrap.sh -d

# 生产模式
./bootstrap.sh
```

启动脚本会自动启动：
- 后端服务：`http://localhost:8008`
- 前端服务：`http://localhost:3002`

#### 方式二：手动启动

**启动后端**：

```bash
# 开发模式（自动重载）
uv run server.py --reload

# 生产模式
uv run server.py

# 指定端口
uv run server.py --host 0.0.0.0 --port 8008
```

**启动前端**：

```bash
cd web

# 开发模式
pnpm dev

# 生产模式（需要先构建）
pnpm build
pnpm start
```

## 🌐 访问地址

启动成功后，在浏览器中访问：

- **前端界面**: http://localhost:3002
- **后端 API**: http://localhost:8008
- **API 文档**: http://localhost:8008/docs
- **管理后台**: http://localhost:3002/admin (需要登录)

## 🔐 默认管理员账户

首次运行后，系统会自动创建默认管理员账户：

- **用户名**: `admin`
- **密码**: `admin123` (请在生产环境中修改)

登录后可以在管理后台修改密码和配置用户权限。

## 📖 功能模块

### 对话聊天
- 智能对话和研究助手
- 支持深度思考模式
- 背景调研功能
- 多轮澄清对话
- 对话历史管理

### 工具箱
- 搜索引擎集成（Tavily, Brave）
- 网络爬虫工具
- Python 代码执行
- MCP 服务集成
- 数据提取工具

### 知识库
- 支持多种 RAG 提供者（RAGFlow, Milvus, MCP）
- 知识库资源管理
- 文档上传和索引

### 用户管理
- 用户、角色、权限管理
- 单位、部门管理
- 菜单动态配置
- 数据权限控制

### 工作流
- 可视化工作流编辑器
- 基于 ReactFlow 的拖拽式设计

## 🛠️ 开发指南

### 项目结构

```
AgenticWorkflow/
├── src/                    # 后端源代码
│   ├── agents/            # 智能体定义
│   ├── graph/             # LangGraph 图定义
│   ├── llms/              # LLM 提供者
│   ├── rag/               # RAG 实现
│   ├── server/            # FastAPI 服务器
│   │   ├── auth/          # 认证和授权
│   │   └── ...
│   └── tools/              # 工具集
├── web/                    # 前端源代码
│   └── src/
│       ├── app/           # Next.js App Router
│       ├── core/          # 核心功能
│       └── components/    # UI 组件
├── scripts/               # 工具脚本
├── conf.yaml              # 配置文件
└── server.py              # 服务器启动脚本
```

### 开发模式

开发模式下，代码修改会自动重载：

- **后端**: 使用 `--reload` 参数
- **前端**: Next.js 自动热重载

### 运行测试

```bash
# 运行 Python 测试
uv run pytest

# 运行前端测试
cd web
pnpm test
```

## 📚 文档

- [配置指南](docs/configuration_guide.md) - 详细的配置说明
- [深度研究模式](docs/deep_research_mode.md) - 深度研究功能说明
- [MCP 集成](docs/mcp_integrations.md) - MCP 服务集成指南
- [FAQ](docs/FAQ.md) - 常见问题解答

## 🔧 常见问题

### 端口冲突

如果 3002 或 8008 端口被占用：

**前端端口**: 修改 `web/package.json` 中的 dev 脚本

**后端端口**: 启动时指定端口
```bash
uv run server.py --port 8009
```

同时需要更新 `src/server/app.py` 中的 CORS 配置。

### 数据库连接问题

确保 PostgreSQL 服务正在运行，并且 `conf.yaml` 中的数据库连接配置正确：

```yaml
ENV:
  LANGGRAPH_CHECKPOINT_DB_URL: "postgresql://user:password@localhost:5432/agenticworkflow"
```

### 对话记录未保存

确保已启用检查点保存：

```yaml
ENV:
  LANGGRAPH_CHECKPOINT_SAVER: true
```

## 🚢 生产部署

生产环境建议：

1. 使用 `pnpm build` 构建前端
2. 使用 `pnpm start` 启动前端
3. 使用进程管理器（如 PM2）管理后端服务
4. 配置反向代理（如 Nginx）
5. 配置 HTTPS
6. 修改默认管理员密码
7. 配置适当的 CORS 策略

## 📝 许可证

MIT License

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📧 联系方式

如有问题或建议，请通过 Issue 联系我们。

---

**注意**: 首次使用前请务必：
1. 配置 `conf.yaml` 中的所有必要参数
2. 运行数据库初始化脚本
3. 修改默认管理员密码

