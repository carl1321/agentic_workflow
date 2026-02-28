// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import type { LucideIcon } from "lucide-react";
import {
  FlaskConical,
  Microscope,
  FileSearch,
  FileText,
  Code,
  Globe,
  Volume2,
  Atom,
  TrendingUp,
  Search,
  Sparkles,
  Workflow,
  Library,
  Cpu,
} from "lucide-react";

export type ToolCategory = "molecular" | "literature" | "general";

/** 页面类入口在 chat 内切换的 viewMode */
export type PageViewMode = "workflow" | "library";

/** 对话模式：深度研究走主对话流 + research_mode，VASP 走 vasp-stream */
export type ChatModeType = "deep_research" | "vasp";

export interface ToolParameter {
  name: string;
  type: "string" | "number" | "boolean" | "array";
  description: string;
  required: boolean;
  default?: unknown;
  enum?: string[];
}

export interface ToolConfig {
  id: string;
  name: string;
  description: string;
  category: ToolCategory;
  icon: LucideIcon;
  parameters: ToolParameter[];
  /** 后端工具名称；页面类/对话模式类可为空 */
  toolName: string;
  /** 入口类型：执行类打开 ToolExecutor，页面类切换 view/跳转，对话模式类进入对话并设 mode */
  entryType?: "executor" | "page" | "chat-mode";
  /** 当 entryType === "page" 时，在 chat 内切换的 viewMode（与 path 二选一） */
  pageView?: PageViewMode;
  /** 当 entryType === "page" 时，外链路径（如 /newSam） */
  path?: string;
  /** 当 entryType === "chat-mode" 时：deep_research | vasp */
  chatMode?: ChatModeType;
}

export const tools: ToolConfig[] = [
  // 页面类入口（点击打开新页面）
  {
    id: "workflow",
    name: "工作流",
    description: "创建、编辑与运行工作流",
    category: "general",
    icon: Workflow,
    toolName: "",
    parameters: [],
    entryType: "page",
    pageView: "workflow",
  },
  {
    id: "sam_design",
    name: "SAM分子设计",
    description: "自组装单分子层（SAM）分子设计流程",
    category: "molecular",
    icon: Atom,
    toolName: "",
    parameters: [],
    entryType: "page",
    path: "/newSam",
  },
  {
    id: "library",
    name: "我的文库",
    description: "管理个人文献与资料库",
    category: "general",
    icon: Library,
    toolName: "",
    parameters: [],
    entryType: "page",
    pageView: "library",
  },
  // 对话模式入口（点击进入对话并走对应流）
  {
    id: "deep_research",
    name: "深度研究",
    description: "进入深度研究对话，多轮迭代生成综合报告",
    category: "literature",
    icon: FileSearch,
    toolName: "",
    parameters: [],
    entryType: "chat-mode",
    chatMode: "deep_research",
  },
  {
    id: "vasp_calc",
    name: "VASP计算",
    description: "进入 VASP 计算对话，规划与执行第一性原理计算",
    category: "molecular",
    icon: Cpu,
    toolName: "",
    parameters: [],
    entryType: "chat-mode",
    chatMode: "vasp",
  },
  // 分子科学工具
  {
    id: "sam_generator",
    name: "SAM分子生成器",
    description: "根据骨架SMILES和锚定基团生成自组装单分子层（SAM）分子结构",
    category: "molecular",
    icon: Atom,
    toolName: "generate_sam_molecules",
    parameters: [
      {
        name: "scaffold_condition",
        type: "string",
        description: "骨架SMILES字符串，多个骨架用逗号分隔，例如：c1ccccc1,c1ccc2c(c1)[nH]c1ccccc12",
        required: true,
      },
      {
        name: "anchoring_group",
        type: "string",
        description: "锚定基团SMILES字符串，例如：O=P(O)(O) 表示磷酸基团",
        required: true,
      },
      {
        name: "gen_size",
        type: "number",
        description: "要生成的分子数量",
        required: false,
        default: 10,
      },
    ],
  },
  {
    id: "phase_diagram",
    name: "相图分析",
    description: "基于 Materials Project 的 0 K 能量凸包分析化学体系的稳定相与亚稳相",
    category: "molecular",
    icon: Globe,
    toolName: "phase_diagram_tool",
    parameters: [
      {
        name: "chemical_system",
        type: "string",
        description: "化学体系，例如 Li-Fe-P-O（元素用短横线分隔）",
        required: true,
      },
      {
        name: "max_entries",
        type: "number",
        description: "最多加载的材料条目数（用于构建相图）",
        required: false,
        default: 128,
      },
    ],
  },
  {
    id: "property_predictor",
    name: "性质预测",
    description: "预测分子的物理化学性质（HOMO、LUMO、偶极矩）",
    category: "molecular",
    icon: TrendingUp,
    toolName: "property_predictor_tool",
    parameters: [
      {
        name: "smiles",
        type: "string",
        description: "SMILES字符串",
        required: true,
      },
      {
        name: "properties",
        type: "array",
        description: "要预测的性质列表，可选值：HOMO（最高占据分子轨道）、LUMO（最低未占据分子轨道）、DM（偶极矩）",
        required: false,
        default: ["HOMO", "LUMO", "DM"],
        enum: ["HOMO", "LUMO", "DM"],
      },
    ],
  },
  {
    id: "visualize_molecules",
    name: "分子可视化",
    description: "生成分子结构图",
    category: "molecular",
    icon: Microscope,
    toolName: "visualize_molecules_tool",
    parameters: [
      {
        name: "smiles",
        type: "string",
        description: "SMILES字符串",
        required: true,
      },
      {
        name: "width",
        type: "number",
        description: "图片宽度（像素）",
        required: false,
        default: 800,
      },
      {
        name: "height",
        type: "number",
        description: "图片高度（像素）",
        required: false,
        default: 600,
      },
    ],
  },
  {
    id: "molecular_analysis",
    name: "分子结构分析",
    description: "使用InternLM API分析分子结构，包括化学性质、结构特征等",
    category: "molecular",
    icon: FlaskConical,
    toolName: "molecular_analysis_tool",
    parameters: [
      {
        name: "smiles",
        type: "string",
        description: "SMILES字符串",
        required: true,
      },
    ],
  },
  // 文献研究工具
  {
    id: "literature_search",
    name: "文献搜索",
    description: "使用 arXiv 搜索学术文献",
    category: "literature",
    icon: Search,
    toolName: "literature_search_tool",
    parameters: [
      {
        name: "query",
        type: "string",
        description: "搜索查询",
        required: true,
      },
      {
        name: "limit",
        type: "number",
        description: "返回结果数量",
        required: false,
        default: 10,
      },
    ],
  },
  // 通用工具
  {
    id: "python_repl",
    name: "Python代码执行",
    description: "在沙箱环境中执行Python代码",
    category: "general",
    icon: Code,
    toolName: "python_repl_tool",
    parameters: [
      {
        name: "code",
        type: "string",
        description: "要执行的Python代码",
        required: true,
      },
    ],
  },
  {
    id: "tts",
    name: "TTS语音",
    description: "文本转语音",
    category: "general",
    icon: Volume2,
    toolName: "tts_tool",
    parameters: [
      {
        name: "text",
        type: "string",
        description: "要转换的文本",
        required: true,
      },
      {
        name: "voice",
        type: "string",
        description: "语音类型",
        required: false,
        enum: ["male", "female"],
        default: "female",
      },
    ],
  },
  {
    id: "prompt_optimizer",
    name: "提示词优化",
    description: "基于自定义提示词和问题，使用AI模型生成回答",
    category: "general",
    icon: Sparkles,
    toolName: "prompt_optimizer_tool",
    parameters: [
      {
        name: "prompt",
        type: "string",
        description: "系统提示词或指令，用于指导模型的行为",
        required: true,
      },
      {
        name: "question",
        type: "string",
        description: "用户的问题或输入，需要模型回答的内容",
        required: true,
      },
      {
        name: "model_name",
        type: "string",
        description: "可选，指定使用的模型名称。留空则使用默认模型",
        required: false,
      },
    ],
  },
  {
    id: "data_extraction",
    name: "数据抽取",
    description: "从PDF或XML文件中提取结构化数据，支持提示词抽取和材料数据抽取两种模式",
    category: "general",
    icon: FileText,
    toolName: "data_extraction_tool",
    parameters: [
      {
        name: "extraction_type",
        type: "string",
        description: "抽取类型：prompt_extraction（提示词抽取）或 material_extraction（材料数据抽取）",
        required: false,
        default: "prompt_extraction",
      },
      {
        name: "pdf_file",
        type: "string",
        description: "上传PDF或XML文件（优先使用）",
        required: false,
      },
      {
        name: "extraction_prompt",
        type: "string",
        description: "数据抽取提示词，描述需要从PDF中提取的数据类型和字段（提示词抽取模式需要）",
        required: false,
      },
      {
        name: "json_schema",
        type: "string",
        description: "期望输出的JSON格式定义，可以是JSON示例或schema描述（提示词抽取模式需要）",
        required: false,
      },
      {
        name: "model_name",
        type: "string",
        description: "可选，指定使用的模型名称。留空则使用默认模型",
        required: false,
      },
      {
        name: "optimize_prompt",
        type: "boolean",
        description: "是否启用提示词优化，使用LLM优化抽取提示词（仅提示词抽取模式）",
        required: false,
        default: false,
      },
    ],
  },
  {
    id: "ppt_generator",
    name: "PPT生成",
    description: "一句话生成PPT：先生成大纲，确认后再生成文件",
    category: "general",
    icon: FileText,
    toolName: "generate_ppt_tool",
    parameters: [
      {
        name: "topic",
        type: "string",
        description: "一句话主题",
        required: false,
      },
      {
        name: "outline",
        type: "string",
        description: "大纲内容（第一步生成后可编辑）",
        required: false,
      },
      {
        name: "action",
        type: "string",
        description: "outline=生成大纲，generate=生成PPT",
        required: false,
        default: "outline",
        enum: ["outline", "generate"],
      },
    ],
  },
];

export const toolsByCategory: Record<ToolCategory, ToolConfig[]> = {
  molecular: tools.filter((t) => t.category === "molecular"),
  literature: tools.filter((t) => t.category === "literature"),
  general: tools.filter((t) => t.category === "general"),
};

export function getToolById(id: string): ToolConfig | undefined {
  return tools.find((t) => t.id === id);
}

