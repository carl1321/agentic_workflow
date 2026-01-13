// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

/**
 * SAM分子设计相关的类型定义
 */

/**
 * 设计步骤枚举
 */
export type DesignStep = "step1" | "step2" | "step3";

/**
 * 研究目标
 */
export interface DesignObjective {
  /** 研究目标的文本描述 */
  text: string;
}

/**
 * 约束类型
 */
export type ConstraintType =
  | "surface_anchoring" // 表面锚定强度
  | "energy_level" // 能级匹配
  | "packing_density" // 膜致密度和稳定性
  | "custom"; // 自定义约束

/**
 * 约束值类型
 */
export type ConstraintValueType = "select" | "range" | "text" | "number";

/**
 * 约束条件
 */
export interface Constraint {
  /** 约束的唯一标识 */
  id: string;
  /** 约束名称 */
  name: string;
  /** 约束类型 */
  type: ConstraintType;
  /** 约束值类型 */
  valueType: ConstraintValueType;
  /** 约束值（根据valueType不同，可能是字符串、数字或范围对象） */
  value: string | number | { min: number; max: number };
  /** 单位（可选） */
  unit?: string;
  /** 是否启用 */
  enabled: boolean;
  /** 选项列表（用于select类型） */
  options?: string[];
}

/**
 * 完整的设计状态
 */
export interface DesignState {
  /** 当前步骤 */
  currentStep: DesignStep;
  /** 研究目标 */
  objective: DesignObjective;
  /** 约束条件列表 */
  constraints: Constraint[];
  /** 任务名称 */
  taskName?: string;
  /** 任务状态 */
  taskStatus?: "preparing" | "running" | "completed" | "failed";
  /** 执行结果 */
  executionResult?: ExecutionResult | null;
}

/**
 * 约束类型配置
 */
export interface ConstraintTypeConfig {
  type: ConstraintType;
  label: string;
  valueType: ConstraintValueType;
  options?: string[];
  defaultUnit?: string;
  placeholder?: string;
}

/**
 * 预定义的约束类型配置
 */
export const CONSTRAINT_TYPE_CONFIGS: ConstraintTypeConfig[] = [
  {
    type: "surface_anchoring",
    label: "表面锚定强度",
    valueType: "select",
    options: ["High", "Medium", "Low"],
    defaultUnit: "",
  },
  {
    type: "energy_level",
    label: "能级匹配",
    valueType: "range",
    defaultUnit: "eV",
    placeholder: "-0.2 到 +0.2",
  },
  {
    type: "packing_density",
    label: "膜致密度和稳定性",
    valueType: "select",
    options: ["High", "Medium", "Low"],
    defaultUnit: "",
  },
  {
    type: "custom",
    label: "自定义约束",
    valueType: "text",
    placeholder: "请输入约束描述",
  },
];

/**
 * 执行模式
 */
export type ExecutionMode = "model" | "workflow";

/**
 * 执行状态
 */
export type ExecutionState = "idle" | "running" | "completed" | "failed";

/**
 * 模型执行状态
 */
export interface ModelExecutionState {
  state: ExecutionState;
  result?: string; // 原始文本结果（向后兼容）
  molecules?: Partial<Molecule>[]; // 解析后的分子数组
  error?: string;
}

/**
 * 工作流执行状态
 */
export interface WorkflowExecutionState {
  state: ExecutionState;
  workflowId?: string;
  runId?: string;
  molecules?: Partial<Molecule>[]; // 解析后的分子数组（如果能在Step2中提取）
  error?: string;
}

/**
 * 执行结果
 */
export interface ExecutionResult {
  mode: ExecutionMode;
  /**
   * 兼容字段：历史版本里用它表示“评估模型”
   * 新代码请优先使用 evaluationModel
   */
  selectedModel?: string;
  /** 生成模型（Step2：模型执行时用于生成分子） */
  generationModel?: string;
  /** 评估模型（Step3：用于评估/打分） */
  evaluationModel?: string;
  modelResult?: ModelExecutionState;
  workflowResult?: WorkflowExecutionState;
}

/**
 * 分子性质数据
 */
export interface MolecularProperties {
  /** HOMO (最高占据分子轨道) */
  HOMO?: number;
  /** LUMO (最低未占据分子轨道) */
  LUMO?: number;
  /** DM (偶极矩) */
  DM?: number;
}

/**
 * 分子评分
 */
export interface MoleculeScore {
  /** 总评分 (0-100) */
  total: number;
  /** 表面锚定强度评分 (0-100) */
  surfaceAnchoring?: number;
  /** 能级匹配评分 (0-100) */
  energyLevel?: number;
  /** 膜致密度和稳定性评分 (0-100) */
  packingDensity?: number;
}

/**
 * 分子分析
 */
export interface MoleculeAnalysis {
  /** 分子总体描述 */
  description: string;
  /** 系统解释 */
  explanation: string;
}

/**
 * 候选分子
 */
export interface Molecule {
  /** 分子序号 */
  index: number;
  /** SMILES字符串 */
  smiles: string;
  /** 骨架条件 */
  scaffoldCondition?: string;
  /** 实际骨架 */
  scaffoldSmiles?: string;
  /** 分子结构图像URL */
  imageUrl?: string;
  /** 分子性质 */
  properties?: MolecularProperties;
  /** 评分 */
  score?: MoleculeScore;
  /** 分析结果 */
  analysis?: MoleculeAnalysis;
}

/**
 * 设计历史记录
 */
export interface DesignHistory {
  /** 唯一标识符 */
  id: string;
  /** 历史记录名称 */
  name: string;
  /** 创建时间 */
  createdAt: string;
  /** 研究目标 */
  objective: DesignObjective;
  /** 约束条件 */
  constraints: Constraint[];
  /** 执行结果 */
  executionResult: ExecutionResult;
  /** 完整的分子数据（包含评估结果） */
  molecules: Molecule[];
}

