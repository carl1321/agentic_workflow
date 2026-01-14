"use client";

// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { useState, useEffect, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "~/components/ui/card";
import { Button } from "~/components/ui/button";
import { Badge } from "~/components/ui/badge";
import { Progress } from "~/components/ui/progress";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "~/components/ui/collapsible";
import { ArrowLeft, CheckCircle2, Loader2, ChevronDown, AlertCircle, RotateCcw, Save } from "lucide-react";
import { executeTool } from "~/core/api/tools";
import { getWorkflowRun } from "~/core/api/workflow";
import { apiRequest } from "~/core/api/api-client";
import { saveDesignHistory } from "~/core/api/sam-design";
import { parseSMILESFromText, extractMoleculesFromWorkflowResult } from "../utils/molecule";
import { getScoreColor, formatScore } from "../utils/molecule";
import type { ExecutionResult, Molecule, DesignObjective, Constraint } from "../types";
import { Skeleton } from "~/components/ui/skeleton";
import { toast } from "sonner";

interface Step3ReviewCandidatesProps {
  /** 上一步回调 */
  onBack: () => void;
  /** 完成回调 */
  onComplete?: () => void;
  /** 重新设计回调 */
  onRedesign?: () => void;
  /** 执行结果 */
  executionResult?: ExecutionResult | null;
  /** 研究目标 */
  objective: DesignObjective;
  /** 约束条件 */
  constraints: Constraint[];
  /** 初始分子数据（从历史记录加载时使用，如果提供则直接使用，不重新执行预测） */
  initialMolecules?: Molecule[];
  /** 右上角操作区（例如：运行历史按钮） */
  headerRight?: React.ReactNode;
}

/**
 * Step 3: 审查和比较候选
 */
export function Step3ReviewCandidates({
  onBack,
  onComplete,
  onRedesign,
  executionResult,
  objective,
  constraints,
  initialMolecules,
  headerRight,
}: Step3ReviewCandidatesProps) {
  const [molecules, setMolecules] = useState<Molecule[]>(initialMolecules || []);
  const [loading, setLoading] = useState(!initialMolecules); // 如果有初始数据，不需要加载
  const [error, setError] = useState<string | null>(null);
  const [expandedMolecules, setExpandedMolecules] = useState<Set<number>>(new Set());
  const [saving, setSaving] = useState(false);
  const [hasAutoSaved, setHasAutoSaved] = useState(!!initialMolecules); // 如果从历史记录加载，标记为已保存
  const hasLoadedRef = useRef(false); // 防止重复加载
  const loadingExecutionIdRef = useRef<string | null>(null); // 跟踪正在加载的执行ID
  const isProcessingRef = useRef(false); // 防止并发处理
  const processedMoleculeImagesRef = useRef<Set<string>>(new Set()); // 跟踪已处理的分子图像（基于SMILES）
  
  // 获取预期的分子数量（用于显示加载骨架屏）
  const getExpectedMoleculeCount = (): number => {
    if (!executionResult) return 0;
    
    // 优先使用预解析的molecules数组长度
    if (executionResult.mode === "model" && executionResult.modelResult?.molecules) {
      return executionResult.modelResult.molecules.length;
    }
    if (executionResult.mode === "workflow" && executionResult.workflowResult?.molecules) {
      return executionResult.workflowResult.molecules.length;
    }
    
    // 如果没有预解析的，尝试从原始结果中估算
    // 这里可以根据实际情况调整，暂时返回1作为默认值
    return 1;
  };
  
  const expectedCount = getExpectedMoleculeCount();

  // 获取用于评估的模型（新字段优先，其次兼容旧字段 selectedModel）
  const evaluationModel = executionResult?.evaluationModel || executionResult?.selectedModel;

  /**
   * 保存历史记录
   */
  const handleSaveHistory = async () => {
    if (!executionResult || molecules.length === 0) {
      toast.error("没有可保存的数据");
      return;
    }

    try {
      setSaving(true);
      const result = await saveDesignHistory(
        undefined, // 使用自动生成的名称
        objective,
        constraints,
        executionResult,
        molecules,
      );

      if (result.success) {
        toast.success("历史记录保存成功");
      } else {
        toast.error("保存历史记录失败");
      }
    } catch (error: any) {
      console.error("Failed to save history:", error);
      toast.error(`保存历史记录失败: ${error.message}`);
    } finally {
      setSaving(false);
    }
  };

  // 提取分子数据
  useEffect(() => {
    // 如果提供了初始分子数据（从历史记录加载），直接使用，不重新执行预测
    if (initialMolecules && initialMolecules.length > 0) {
      if (!hasLoadedRef.current) {
        setMolecules(initialMolecules);
        setLoading(false);
        hasLoadedRef.current = true;
      }
      return;
    }

    if (!executionResult) {
      setLoading(false);
      return;
    }

    // 生成执行ID，用于防止重复加载
    const executionId = `${executionResult.mode}-${executionResult.modelResult?.result?.substring(0, 50) || executionResult.workflowResult?.workflowId || executionResult.workflowResult?.runId || 'unknown'}`;
    
    // 如果已经在加载相同的执行结果，跳过
    if (loadingExecutionIdRef.current === executionId || isProcessingRef.current) {
      console.log("Skipping duplicate load for executionId:", executionId, "isProcessing:", isProcessingRef.current);
      return;
    }

    // 标记开始加载
    console.log("Starting to load molecules for executionId:", executionId);
    loadingExecutionIdRef.current = executionId;
    hasLoadedRef.current = false;
    isProcessingRef.current = true;
    processedMoleculeImagesRef.current.clear(); // 清除之前的处理记录

    const loadMolecules = async () => {
      try {
        setLoading(true);
        setError(null);

        let moleculesData: Partial<Molecule>[] = [];

        // 优先使用ExecutionResult中预解析的molecules数组
        if (executionResult.mode === "model" && executionResult.modelResult?.molecules) {
          moleculesData = executionResult.modelResult.molecules;
        } else if (executionResult.mode === "workflow" && executionResult.workflowResult?.molecules) {
          moleculesData = executionResult.workflowResult.molecules;
        } else {
          // 如果没有预解析的molecules，则从原始结果中解析
          if (executionResult.mode === "model" && executionResult.modelResult?.result) {
            // 从模型执行结果中解析SMILES
            const smilesList = parseSMILESFromText(executionResult.modelResult.result);
            moleculesData = smilesList.map((smiles, index) => ({
              index: index + 1,
              smiles,
            }));
          } else if (
            executionResult.mode === "workflow" &&
            executionResult.workflowResult?.runId &&
            executionResult.workflowResult?.workflowId
          ) {
            // 从工作流执行结果中提取数据
            try {
              const workflowId = executionResult.workflowResult.workflowId;
              const run = await getWorkflowRun(workflowId, executionResult.workflowResult.runId);
              if (run.output) {
                moleculesData = extractMoleculesFromWorkflowResult(run.output);
              } else {
                setError("工作流执行结果中没有输出数据");
                setLoading(false);
                return;
              }
            } catch (err: any) {
              console.error("Failed to load workflow run:", err);
              setError(`加载工作流结果失败: ${err.message}`);
              setLoading(false);
              return;
            }
          }
        }

        if (moleculesData.length === 0) {
          setError("未找到分子数据");
          setLoading(false);
          return;
        }

        // 补充缺失的数据（可视化、性质预测、评估）
        const processedMolecules = await Promise.all(
          moleculesData.map(async (mol, index) => {
            // 检查分子是否已经有完整的评估结果（从历史记录或工作流结果中可能已经包含）
            const hasCompleteEvaluation = mol.score && mol.analysis && mol.properties;
            
            const molecule: Molecule = {
              index: mol.index || index + 1,
              smiles: mol.smiles || "",
              scaffoldCondition: mol.scaffoldCondition,
              scaffoldSmiles: mol.scaffoldSmiles,
              imageUrl: mol.imageUrl,
              properties: mol.properties,
              // 如果已有完整评估结果，直接复制
              score: hasCompleteEvaluation ? mol.score : undefined,
              analysis: hasCompleteEvaluation ? mol.analysis : undefined,
            };
            
            // 如果没有图像，为每个分子单独生成图片
            // 使用SMILES作为唯一标识，防止重复生成
            const moleculeKey = molecule.smiles;
            if (!molecule.imageUrl && molecule.smiles && !processedMoleculeImagesRef.current.has(moleculeKey)) {
              try {
                // 标记为正在处理
                processedMoleculeImagesRef.current.add(moleculeKey);
                console.log(`Generating image for molecule ${molecule.index}: ${molecule.smiles.substring(0, 30)}...`);
                const visResult = await executeTool("visualize_molecules_tool", {
                  smiles_text: `${molecule.index}. SMILES: ${molecule.smiles}`,
                });
                
                // 从结果中提取图像URL（支持多种格式）
                // 格式1: <!-- MOLECULAR_IMAGE_ID:uuid -->
                const imageIdMatch = visResult.match(/<!--\s*MOLECULAR_IMAGE_ID:([a-f0-9\-]+)\s*-->/i);
                if (imageIdMatch) {
                  molecule.imageUrl = `/molecular_images/${imageIdMatch[1]}.svg`;
                } else {
                  // 格式2: /molecular_images/uuid.svg
                  const imageUrlMatch = visResult.match(/\/molecular_images\/[a-f0-9\-]+\.svg/i);
                  if (imageUrlMatch) {
                    molecule.imageUrl = imageUrlMatch[0];
                  }
                }
              } catch (err) {
                console.error(`Failed to visualize molecule ${molecule.index}:`, err);
              }
            }

            // 如果已经有完整的评估结果，直接使用，不重新执行评估
            if (hasCompleteEvaluation) {
              molecule.score = mol.score;
              molecule.analysis = mol.analysis;
              molecule.properties = mol.properties;
              console.log(`Molecule ${molecule.index} already has complete evaluation, skipping re-evaluation`);
            } else if (molecule.smiles) {
              // 只有在没有完整评估结果时才进行评估
              // 评估API会自动使用LLM预测性质（如果没有提供），所以不需要单独调用性质预测工具
              try {
                console.log(`Evaluating molecule ${molecule.index}: ${molecule.smiles.substring(0, 30)}...`);
                const evalResult = await apiRequest<{
                  success: boolean;
                  score: {
                    total: number;
                    surfaceAnchoring?: number;
                    energyLevel?: number;
                    packingDensity?: number;
                  };
                  description: string;
                  explanation: string;
                  properties?: {
                    HOMO?: number;
                    LUMO?: number;
                    DM?: number;
                  };
                }>("sam-design/evaluate-molecule", {
                  method: "POST",
                  body: JSON.stringify({
                    model: evaluationModel, // 传递评估模型
                    smiles: molecule.smiles,
                    objective: objective.text,
                    constraints: constraints.map((c) => ({
                      name: c.name,
                      value: c.value,
                      enabled: c.enabled,
                    })),
                    properties: molecule.properties, // 如果已有性质则传递，否则评估API会用LLM预测
                  }),
                });

                if (evalResult.success) {
                  molecule.score = {
                    total: evalResult.score.total,
                    surfaceAnchoring: evalResult.score.surfaceAnchoring,
                    energyLevel: evalResult.score.energyLevel,
                    packingDensity: evalResult.score.packingDensity,
                  };
                  molecule.analysis = {
                    description: evalResult.description,
                    explanation: evalResult.explanation,
                  };
                  // 如果评估API返回了预测的性质，更新molecule.properties
                  if (evalResult.properties && !molecule.properties) {
                    molecule.properties = evalResult.properties;
                  }
                }
              } catch (err) {
                console.error(`Failed to evaluate molecule ${molecule.index}:`, err);
              }
            }

            return molecule;
          })
        );

        setMolecules(processedMolecules);
        hasLoadedRef.current = true;
        isProcessingRef.current = false;
        console.log("Molecules loaded successfully, executionId:", executionId);
      } catch (err: any) {
        console.error("Failed to load molecules:", err);
        setError(err.message || "加载分子数据失败");
        hasLoadedRef.current = true;
        isProcessingRef.current = false;
        // 清除执行ID，允许重试
        if (loadingExecutionIdRef.current === executionId) {
          loadingExecutionIdRef.current = null;
        }
      } finally {
        setLoading(false);
      }
    };

    loadMolecules();
    
    // 清理函数：如果组件卸载或依赖项变化，清除执行ID
    return () => {
      if (loadingExecutionIdRef.current === executionId) {
        loadingExecutionIdRef.current = null;
      }
    };
  }, [executionResult, objective, constraints, initialMolecules]);

  // 自动保存历史记录（当分子数据加载完成后）
  useEffect(() => {
    // 如果是从历史记录加载的（有initialMolecules），不自动保存
    if (initialMolecules && initialMolecules.length > 0) {
      return;
    }
    
    // 只有在分子数据加载完成且不为空时才自动保存，且只保存一次
    if (molecules.length > 0 && executionResult && !loading && !saving && !hasAutoSaved) {
      // 延迟保存，避免频繁保存
      const autoSaveTimer = setTimeout(async () => {
        try {
          console.log("Auto-saving design history...", {
            moleculesCount: molecules.length,
            executionMode: executionResult.mode,
          });
          
          setSaving(true);
          const result = await saveDesignHistory(
            undefined, // 使用自动生成的名称
            objective,
            constraints,
            executionResult,
            molecules,
          );

          if (result.success) {
            console.log("Design history auto-saved successfully:", result.id);
            setHasAutoSaved(true);
            toast.success("设计历史已自动保存");
          } else {
            console.warn("Auto-save failed:", result);
          }
        } catch (error: any) {
          console.error("Failed to auto-save history:", error);
          // 自动保存失败不显示错误提示，避免打扰用户
        } finally {
          setSaving(false);
        }
      }, 2000); // 延迟2秒保存

      return () => clearTimeout(autoSaveTimer);
    }
  }, [molecules, executionResult, loading, saving, hasAutoSaved, objective, constraints, initialMolecules]);

  const toggleExpanded = (index: number) => {
    setExpandedMolecules((prev) => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  };

  return (
    <div className="flex flex-col gap-6">
      {/* 顶部：标题 */}
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-2">
          <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100 sm:text-xl">
            审查与比较候选
          </h1>
          <p className="text-sm text-slate-600 dark:text-slate-400">
            根据您的目标和约束条件，审查和比较生成的候选分子
          </p>
        </div>
        {headerRight ? <div className="pt-1">{headerRight}</div> : null}
      </div>

      {/* 主要内容 */}
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle className="text-lg">候选分子</CardTitle>
          <CardDescription className="text-sm">
            {executionResult
              ? `执行方式：${executionResult.mode === "model" ? "模型执行" : "工作流执行"} | 共 ${molecules.length} 个候选分子`
              : "此步骤将在后续版本中实现。您将能够审查、比较并选择最佳的候选分子。"}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {loading ? (
            <div className="space-y-4">
              {expectedCount > 0 ? (
                Array.from({ length: expectedCount }).map((_, i) => (
                  <Card key={i} className="p-4">
                    <div className="flex gap-4">
                      <Skeleton className="h-32 w-32" />
                      <div className="flex-1 space-y-2">
                        <Skeleton className="h-4 w-3/4" />
                        <Skeleton className="h-4 w-1/2" />
                        <Skeleton className="h-4 w-2/3" />
                      </div>
                    </div>
                  </Card>
                ))
              ) : (
                <Card className="p-4">
                  <div className="flex gap-4">
                    <Skeleton className="h-32 w-32" />
                    <div className="flex-1 space-y-2">
                      <Skeleton className="h-4 w-3/4" />
                      <Skeleton className="h-4 w-1/2" />
                      <Skeleton className="h-4 w-2/3" />
                    </div>
                  </div>
                </Card>
              )}
            </div>
          ) : error ? (
            <div className="flex items-center gap-3 rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 p-4">
              <AlertCircle className="h-5 w-5 text-red-600 dark:text-red-400" />
              <div className="flex-1">
                <p className="text-sm font-medium text-red-900 dark:text-red-100">加载失败</p>
                <p className="text-xs text-red-700 dark:text-red-300 mt-1">{error}</p>
              </div>
            </div>
          ) : molecules.length === 0 ? (
            <div className="rounded-lg border border-dashed border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-800/50 py-12 text-center">
              <CheckCircle2 className="mx-auto h-12 w-12 text-slate-400 dark:text-slate-500" />
              <p className="mt-4 text-sm font-medium text-slate-600 dark:text-slate-400">
                未找到候选分子
              </p>
              <p className="mt-2 text-xs text-slate-500 dark:text-slate-500">
                请返回上一步重新执行
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {molecules.map((molecule) => (
                <Card key={molecule.index} className="overflow-hidden">
                  <CardContent className="p-6">
                    <div className="flex flex-col lg:flex-row gap-6">
                      {/* 左侧：分子结构图 */}
                      <div className="flex-shrink-0 w-full lg:w-auto">
                        {molecule.imageUrl ? (
                          <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-4">
                            <span className="block w-fit overflow-hidden">
                              <img
                                src={molecule.imageUrl}
                                alt={`Molecule ${molecule.index}`}
                                className="size-full object-contain"
                                style={{ 
                                  maxWidth: '400px',
                                  maxHeight: '400px',
                                }}
                                onError={(e) => {
                                  (e.target as HTMLImageElement).style.display = "none";
                                  const parent = (e.target as HTMLImageElement).parentElement;
                                  if (parent) {
                                    parent.innerHTML = '<div class="text-center text-sm text-slate-500 dark:text-slate-400 py-8">图像加载失败</div>';
                                  }
                                }}
                              />
                            </span>
                          </div>
                        ) : (
                          <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 p-8 flex items-center justify-center mx-auto lg:mx-0" style={{ width: '400px', height: '400px' }}>
                            <div className="flex flex-col items-center gap-2">
                              <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
                              <p className="text-xs text-slate-500 dark:text-slate-400">加载图像中...</p>
                            </div>
                          </div>
                        )}
                      </div>

                      {/* 右侧：分子信息 */}
                      <div className="flex-1 space-y-4">
                        {/* 分子基本信息 */}
                        <div>
                          <div className="flex items-center justify-between mb-2">
                            <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                              候选分子 {molecule.index}
                            </h3>
                            {molecule.score && (
                              <Badge
                                variant="outline"
                                className={`text-lg font-bold px-3 py-1 ${getScoreColor(molecule.score.total)}`}
                              >
                                {formatScore(molecule.score.total)} 分
                              </Badge>
                            )}
                          </div>
                          <p className="text-sm font-mono text-slate-600 dark:text-slate-400 break-all">
                            SMILES: {molecule.smiles}
                          </p>
                        </div>

                        {/* 总评分 */}
                        {molecule.score && (
                          <div className="space-y-2">
                            <div className="flex items-center justify-between">
                              <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                                总评分
                              </span>
                              <span className={`text-lg font-bold ${getScoreColor(molecule.score.total)}`}>
                                {formatScore(molecule.score.total)} / 100
                              </span>
                            </div>
                            <Progress value={molecule.score.total} className="h-2" />
                          </div>
                        )}

                        {/* 各维度指标 */}
                        {molecule.score && (
                          <div className="space-y-3">
                            <h4 className="text-sm font-medium text-slate-700 dark:text-slate-300">
                              各维度评分
                            </h4>
                            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                              {molecule.score.surfaceAnchoring !== undefined && (
                                <div className="space-y-1">
                                  <div className="flex items-center justify-between text-xs">
                                    <span className="text-slate-600 dark:text-slate-400">
                                      表面锚定强度
                                    </span>
                                    <span className="font-medium">
                                      {formatScore(molecule.score.surfaceAnchoring)}
                                    </span>
                                  </div>
                                  <Progress
                                    value={molecule.score.surfaceAnchoring}
                                    className="h-1.5"
                                  />
                                </div>
                              )}
                              {molecule.score.energyLevel !== undefined && (
                                <div className="space-y-1">
                                  <div className="flex items-center justify-between text-xs">
                                    <span className="text-slate-600 dark:text-slate-400">
                                      能级匹配
                                    </span>
                                    <span className="font-medium">
                                      {formatScore(molecule.score.energyLevel)}
                                    </span>
                                  </div>
                                  <Progress
                                    value={molecule.score.energyLevel}
                                    className="h-1.5"
                                  />
                                </div>
                              )}
                              {molecule.score.packingDensity !== undefined && (
                                <div className="space-y-1">
                                  <div className="flex items-center justify-between text-xs">
                                    <span className="text-slate-600 dark:text-slate-400">
                                      膜致密度和稳定性
                                    </span>
                                    <span className="font-medium">
                                      {formatScore(molecule.score.packingDensity)}
                                    </span>
                                  </div>
                                  <Progress
                                    value={molecule.score.packingDensity}
                                    className="h-1.5"
                                  />
                                </div>
                              )}
                            </div>
                          </div>
                        )}

                        {/* 分子性质 */}
                        {molecule.properties && (
                          <div className="space-y-2">
                            <h4 className="text-sm font-medium text-slate-700 dark:text-slate-300">
                              分子性质
                            </h4>
                            <div className="flex flex-wrap gap-2">
                              {molecule.properties.HOMO !== undefined && (
                                <Badge variant="secondary" className="text-xs">
                                  HOMO: {molecule.properties.HOMO.toFixed(3)} eV
                                </Badge>
                              )}
                              {molecule.properties.LUMO !== undefined && (
                                <Badge variant="secondary" className="text-xs">
                                  LUMO: {molecule.properties.LUMO.toFixed(3)} eV
                                </Badge>
                              )}
                              {molecule.properties.DM !== undefined && (
                                <Badge variant="secondary" className="text-xs">
                                  偶极矩: {molecule.properties.DM.toFixed(3)} Debye
                                </Badge>
                              )}
                            </div>
                          </div>
                        )}

                        {/* 分子描述 */}
                        {molecule.analysis && (
                          <div className="space-y-2">
                            <h4 className="text-sm font-medium text-slate-700 dark:text-slate-300">
                              分子描述
                            </h4>
                            <p className="text-sm text-slate-600 dark:text-slate-400">
                              {molecule.analysis.description}
                            </p>
                          </div>
                        )}

                        {/* 系统解释（可折叠） */}
                        {molecule.analysis && (
                          <Collapsible
                            open={expandedMolecules.has(molecule.index)}
                            onOpenChange={() => toggleExpanded(molecule.index)}
                          >
                            <CollapsibleTrigger asChild>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="w-full justify-between"
                              >
                                <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                                  系统解释
                                </span>
                                <ChevronDown
                                  className={`h-4 w-4 transition-transform ${
                                    expandedMolecules.has(molecule.index) ? "rotate-180" : ""
                                  }`}
                                />
                              </Button>
                            </CollapsibleTrigger>
                            <CollapsibleContent className="pt-2">
                              <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 p-4">
                                <p className="text-sm text-slate-600 dark:text-slate-400 whitespace-pre-wrap">
                                  {molecule.analysis.explanation}
                                </p>
                              </div>
                            </CollapsibleContent>
                          </Collapsible>
                        )}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}

          {/* 操作按钮 */}
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between pt-4 border-t">
            <div className="flex gap-2">
              <Button type="button" variant="outline" onClick={onBack} className="w-full sm:w-auto">
                <ArrowLeft className="mr-2 h-4 w-4" />
                返回上一步
              </Button>
              {onRedesign && (
                <Button type="button" variant="outline" onClick={onRedesign} className="w-full sm:w-auto">
                  <RotateCcw className="mr-2 h-4 w-4" />
                  重新设计
                </Button>
              )}
            </div>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={handleSaveHistory}
                disabled={saving || molecules.length === 0}
                className="w-full sm:w-auto"
              >
                {saving ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    保存中...
                  </>
                ) : (
                  <>
                    <Save className="mr-2 h-4 w-4" />
                    保存历史
                  </>
                )}
              </Button>
              <Button
                type="button"
                onClick={onComplete}
                disabled={molecules.length === 0}
                className="w-full sm:w-auto"
              >
                <CheckCircle2 className="mr-2 h-4 w-4" />
                完成设计
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
