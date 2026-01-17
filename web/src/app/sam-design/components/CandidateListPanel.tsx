"use client";

// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { useState, useEffect, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "~/components/ui/card";
import { Badge } from "~/components/ui/badge";
import { Progress } from "~/components/ui/progress";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "~/components/ui/collapsible";
import { ChevronDown } from "lucide-react";
import { getScoreColor, formatScore, extractDimScoresFromResolvedInputsPrompt } from "../utils/molecule";
import { apiRequest } from "~/core/api/api-client";
import { executeTool } from "~/core/api/tools";
import type { Molecule, Constraint, DesignObjective } from "../types";
import { ConstraintSatisfactionPanel } from "./ConstraintSatisfactionPanel";
import { MoleculeOptimizationHistory } from "./MoleculeOptimizationHistory";

interface CandidateListPanelProps {
  molecules: Molecule[];
  constraints: Constraint[];
  executionState: "idle" | "running" | "completed" | "failed";
  initialMolecules?: Molecule[];
  objective?: DesignObjective;
  evaluationModel?: string;
  iterationSnapshots?: Array<{
    iter: number;
    passed: Partial<Molecule>[];
    pending: Partial<Molecule>[];
    best: Partial<Molecule> | null;
  }>;
  iterationNodeOutputs?: Map<number, Record<string, any>>;
  workflowGraph?: { nodes: any[]; edges: any[] } | null;
}

/**
 * 候选分子列表面板（右列）
 */
export function CandidateListPanel({
  molecules,
  constraints,
  executionState,
  initialMolecules,
  objective,
  evaluationModel = "Qwen-235B-Instruct",
  iterationSnapshots = [],
  iterationNodeOutputs = new Map(),
  workflowGraph,
}: CandidateListPanelProps) {
  const [processedMolecules, setProcessedMolecules] = useState<Molecule[]>([]);
  const [selectedMolecule, setSelectedMolecule] = useState<Molecule | null>(null);
  const processedImagesRef = useRef<Set<string>>(new Set());
  const imageUrlMapRef = useRef<Map<string, string>>(new Map()); // SMILES -> imageUrl 缓存
  const isProcessingRef = useRef(false);

  // 从迭代过程的评估节点输出中构建“最后一次出现时的三维评分”（按分子 id 对齐）
  // 这是确定数据源：resolved_inputs.prompt 里三段 JSON（critic_aspect + score）
  const lastDimScoresById = useRef<Map<number | string, { surfaceAnchoring?: number; energyLevel?: number; packingDensity?: number }>>(new Map());
  useEffect(() => {
    const m = new Map<number | string, { surfaceAnchoring?: number; energyLevel?: number; packingDensity?: number }>();

    // iterationNodeOutputs: Map<iter, Record<nodeId, outputs>>
    // 我们扫描每轮的 node outputs，找出含 iteration_outputs[].resolved_inputs.prompt 的节点，然后解析三段 JSON
    for (const [iter, iterOutputs] of iterationNodeOutputs.entries()) {
      if (!iterOutputs) continue;
      for (const nodeOutput of Object.values(iterOutputs)) {
        if (!nodeOutput || typeof nodeOutput !== "object") continue;
        const iterationOutputs = (nodeOutput as any).iteration_outputs;
        if (!Array.isArray(iterationOutputs)) continue;

        const entry = iterationOutputs.find((x: any) => x && typeof x === "object" && x.iteration === iter);
        const promptText = entry?.resolved_inputs?.prompt;
        if (typeof promptText !== "string" || promptText.length === 0) continue;

        const dimsById = extractDimScoresFromResolvedInputsPrompt(promptText);
        for (const [id, dims] of dimsById.entries()) {
          const prev = m.get(id) || {};
          // 以最新一轮为准覆盖（只覆盖有值的维度）
          m.set(id, {
            surfaceAnchoring: dims.surfaceAnchoring ?? prev.surfaceAnchoring,
            energyLevel: dims.energyLevel ?? prev.energyLevel,
            packingDensity: dims.packingDensity ?? prev.packingDensity,
          });
        }
      }
    }

    lastDimScoresById.current = m;
  }, [iterationNodeOutputs]);

  // 处理分子：生成图片、评估等
  useEffect(() => {
    const processMolecules = async () => {
      if (isProcessingRef.current) return;
      isProcessingRef.current = true;

      const sourceMolecules = molecules.length > 0 ? molecules : (initialMolecules || []);
      if (sourceMolecules.length === 0) {
        setProcessedMolecules([]);
        isProcessingRef.current = false;
        return;
      }

      try {
        const processed = await Promise.all(
          sourceMolecules.map(async (mol, idx) => {
            const molecule: Molecule = {
              index: mol.index || idx + 1,
              smiles: mol.smiles || "",
              scaffoldCondition: mol.scaffoldCondition,
              scaffoldSmiles: mol.scaffoldSmiles,
              imageUrl: mol.imageUrl,
              properties: mol.properties,
              score: mol.score,
              analysis: mol.analysis,
            };

            // 生成图片（如果没有）
            // 首先检查缓存
            if (!molecule.imageUrl && molecule.smiles) {
              const cachedUrl = imageUrlMapRef.current.get(molecule.smiles);
              if (cachedUrl) {
                molecule.imageUrl = cachedUrl;
                console.log(`[CandidateListPanel] Using cached imageUrl for molecule ${molecule.index}: ${molecule.imageUrl}`);
              } else if (!processedImagesRef.current.has(molecule.smiles)) {
                try {
                  processedImagesRef.current.add(molecule.smiles);
                  console.log(`[CandidateListPanel] Generating image for molecule ${molecule.index}: ${molecule.smiles.substring(0, 30)}...`);
                  const visResult = await executeTool("visualize_molecules_tool", {
                    smiles_text: `${molecule.index}. SMILES: ${molecule.smiles}`,
                  });
                  console.log(`[CandidateListPanel] Tool result for molecule ${molecule.index} (first 500 chars):`, visResult.substring(0, 500));
                  
                  const imageIdMatch = visResult.match(/<!--\s*MOLECULAR_IMAGE_ID:([a-f0-9\-]+)\s*-->/i);
                  if (imageIdMatch) {
                    molecule.imageUrl = `/molecular_images/${imageIdMatch[1]}.svg`;
                    imageUrlMapRef.current.set(molecule.smiles, molecule.imageUrl);
                    console.log(`[CandidateListPanel] ✓ Set imageUrl for molecule ${molecule.index}: ${molecule.imageUrl}`);
                  } else {
                    const imageUrlMatch = visResult.match(/\/molecular_images\/[a-f0-9\-]+\.svg/i);
                    if (imageUrlMatch) {
                      molecule.imageUrl = imageUrlMatch[0];
                      imageUrlMapRef.current.set(molecule.smiles, molecule.imageUrl);
                      console.log(`[CandidateListPanel] ✓ Set imageUrl (format 2) for molecule ${molecule.index}: ${molecule.imageUrl}`);
                    } else {
                      console.warn(`[CandidateListPanel] ✗ Could not extract image URL from tool result for molecule ${molecule.index}`);
                      console.warn(`[CandidateListPanel] Full tool result:`, visResult);
                      // 如果生成失败，从processedImagesRef中移除，允许重试
                      processedImagesRef.current.delete(molecule.smiles);
                    }
                  }
                } catch (err) {
                  console.error(`[CandidateListPanel] ✗ Failed to visualize molecule ${molecule.index}:`, err);
                  // 如果生成失败，从processedImagesRef中移除，允许重试
                  processedImagesRef.current.delete(molecule.smiles);
                }
              } else {
                console.log(`[CandidateListPanel] Image generation already in progress for molecule ${molecule.index}, skipping...`);
              }
            }

            // 评估分子（如果没有评估结果）
            if (!molecule.score && molecule.smiles && objective) {
              try {
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
                    model: evaluationModel,
                    smiles: molecule.smiles,
                    objective: objective.text,
                    constraints: constraints.map((c) => ({
                      name: c.name,
                      value: c.value,
                      enabled: c.enabled,
                    })),
                    properties: molecule.properties,
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
                  if (evalResult.properties && !molecule.properties) {
                    molecule.properties = evalResult.properties;
                  }
                }
              } catch (err) {
                console.error(`Failed to evaluate molecule ${molecule.index}:`, err);
              }
            }

            // 修正：维度评分缺失/被错误置 0 时，必须以迭代评估节点输出为准（按分子 id 对齐）
            if (molecule.score) {
              const moleculeId = molecule.index; // 当前项目内 index 实际承载了 workflow 的分子 id
              const fallback = lastDimScoresById.current.get(moleculeId);
              const isMissing = (v: number | undefined) => v === undefined || v === null || v <= 0;
              molecule.score = {
                ...molecule.score,
                surfaceAnchoring: !isMissing(molecule.score.surfaceAnchoring)
                  ? molecule.score.surfaceAnchoring
                  : fallback?.surfaceAnchoring,
                energyLevel: !isMissing(molecule.score.energyLevel)
                  ? molecule.score.energyLevel
                  : fallback?.energyLevel,
                packingDensity: !isMissing(molecule.score.packingDensity)
                  ? molecule.score.packingDensity
                  : fallback?.packingDensity,
              };

              // 总分同样用三维均值计算（按你定义的规则），避免出现“维度有值但 total 不一致”
              const sa = molecule.score.surfaceAnchoring;
              const el = molecule.score.energyLevel;
              const pd = molecule.score.packingDensity;
              const dims = [sa, el, pd].filter((v) => typeof v === "number") as number[];
              if (dims.length > 0) {
                const computedTotal = Math.round((dims.reduce((a, b) => a + b, 0) / dims.length) * 10) / 10;
                molecule.score.total = computedTotal;
              }
            }

            return molecule;
          })
        );

        setProcessedMolecules(processed);
        console.log(`[CandidateListPanel] Processed ${processed.length} molecules, images:`, 
          processed.map(m => ({ index: m.index, smiles: m.smiles?.substring(0, 30), imageUrl: m.imageUrl })));
      } catch (err) {
        console.error("[CandidateListPanel] Failed to process molecules:", err);
        setProcessedMolecules(sourceMolecules);
      } finally {
        isProcessingRef.current = false;
      }
    };

    processMolecules();
  }, [molecules, initialMolecules, objective, constraints, evaluationModel]);

  // 按总分排序
  const sortedMolecules = [...processedMolecules].sort(
    (a, b) => (b.score?.total || 0) - (a.score?.total || 0)
  );


  if (executionState === "idle" && sortedMolecules.length === 0) {
    return (
      <div className="flex h-full flex-col bg-white dark:bg-slate-900">
        <div className="border-b border-slate-200 px-4 py-2 dark:border-slate-700">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">候选分子</h3>
        </div>
        <div className="flex flex-1 items-center justify-center p-8 text-center text-slate-500 dark:text-slate-400">
          <p className="text-sm">请先执行工作流以生成候选分子</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-y-auto bg-white dark:bg-slate-900">
      <div className="border-b border-slate-200 px-4 py-2 dark:border-slate-700">
        <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
          候选分子 ({sortedMolecules.length})
        </h3>
      </div>
      <div className="flex-1 space-y-4 p-4">
        {sortedMolecules.map((molecule) => (
          <Card key={molecule.index} className="shadow-sm">
            <CardHeader className="pb-3">
              <div className="flex items-start justify-between">
                <CardTitle className="text-sm">分子 #{molecule.index}</CardTitle>
                {molecule.score && (
                  <Badge
                    className={`${getScoreColor(molecule.score.total)} bg-opacity-10`}
                  >
                    {formatScore(molecule.score.total)}
                  </Badge>
                )}
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              {/* SMILES 图片 */}
              {molecule.imageUrl ? (
                <div className="flex justify-center rounded border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-800">
                  <img
                    src={molecule.imageUrl}
                    alt={`Molecule ${molecule.index}`}
                    className="max-h-32 max-w-full"
                    onError={(e) => {
                      console.error(`[CandidateListPanel] Failed to load image for molecule ${molecule.index}: ${molecule.imageUrl}`);
                      // 图片加载失败时，清除imageUrl以显示SMILES文本
                      const target = e.target as HTMLImageElement;
                      target.style.display = 'none';
                      const parent = target.parentElement;
                      if (parent) {
                        const fallback = document.createElement('div');
                        fallback.className = 'flex items-center justify-center text-xs text-slate-500';
                        fallback.textContent = molecule.smiles;
                        parent.appendChild(fallback);
                      }
                    }}
                    onLoad={() => {
                      console.log(`[CandidateListPanel] Successfully loaded image for molecule ${molecule.index}: ${molecule.imageUrl}`);
                    }}
                  />
                </div>
              ) : (
                <div className="flex items-center justify-center rounded border border-slate-200 bg-slate-50 p-4 text-xs text-slate-500 dark:border-slate-700 dark:bg-slate-800">
                  {molecule.smiles}
                </div>
              )}

              {/* 评分详情 */}
              {molecule.score && (
                <div className="space-y-2">
                  <div className="text-xs font-medium text-slate-700 dark:text-slate-300">
                    评分详情
                  </div>
                  <div className="space-y-1.5">
                    {molecule.score.surfaceAnchoring !== undefined && (
                      <div>
                        <div className="mb-1 flex items-center justify-between text-xs">
                          <span className="text-slate-600 dark:text-slate-400">表面锚定强度</span>
                          <span className={getScoreColor(molecule.score.surfaceAnchoring)}>
                            {formatScore(molecule.score.surfaceAnchoring)}
                          </span>
                        </div>
                        <Progress
                          value={Math.min(100, Math.max(0, molecule.score.surfaceAnchoring * 10))}
                          className="h-1.5"
                        />
                      </div>
                    )}
                    {molecule.score.energyLevel !== undefined && (
                      <div>
                        <div className="mb-1 flex items-center justify-between text-xs">
                          <span className="text-slate-600 dark:text-slate-400">能级匹配</span>
                          <span className={getScoreColor(molecule.score.energyLevel)}>
                            {formatScore(molecule.score.energyLevel)}
                          </span>
                        </div>
                        <Progress
                          value={Math.min(100, Math.max(0, molecule.score.energyLevel * 10))}
                          className="h-1.5"
                        />
                      </div>
                    )}
                    {molecule.score.packingDensity !== undefined && (
                      <div>
                        <div className="mb-1 flex items-center justify-between text-xs">
                          <span className="text-slate-600 dark:text-slate-400">膜致密度</span>
                          <span className={getScoreColor(molecule.score.packingDensity)}>
                            {formatScore(molecule.score.packingDensity)}
                          </span>
                        </div>
                        <Progress
                          value={Math.min(100, Math.max(0, molecule.score.packingDensity * 10))}
                          className="h-1.5"
                        />
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* 描述 */}
              {molecule.analysis?.description && (
                <div className="space-y-1">
                  <div className="text-xs font-medium text-slate-700 dark:text-slate-300">
                    描述
                  </div>
                  <p className="text-xs text-slate-600 dark:text-slate-400">
                    {molecule.analysis.description}
                  </p>
                </div>
              )}

              {/* 约束满足情况 */}
              <Collapsible>
                <CollapsibleTrigger
                  className="flex w-full items-center justify-between rounded border border-slate-200 px-3 py-2 text-xs hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
                  onClick={() => setSelectedMolecule(molecule)}
                >
                  <span className="font-medium text-slate-700 dark:text-slate-300">
                    约束满足情况
                  </span>
                  <ChevronDown className="h-4 w-4 text-slate-500" />
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <div className="pt-2">
                    <ConstraintSatisfactionPanel
                      molecule={molecule}
                      constraints={constraints}
                    />
                  </div>
                </CollapsibleContent>
              </Collapsible>

              {/* 优化历史 */}
              <Collapsible>
                <CollapsibleTrigger
                  className="flex w-full items-center justify-between rounded border border-slate-200 px-3 py-2 text-xs hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
                  onClick={() => setSelectedMolecule(molecule)}
                >
                  <span className="font-medium text-slate-700 dark:text-slate-300">
                    优化历史
                  </span>
                  <ChevronDown className="h-4 w-4 text-slate-500" />
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <div className="pt-2">
                    <MoleculeOptimizationHistory 
                      molecule={molecule} 
                      iterationSnapshots={iterationSnapshots}
                      iterationNodeOutputs={iterationNodeOutputs}
                      workflowGraph={workflowGraph}
                    />
                  </div>
                </CollapsibleContent>
              </Collapsible>
            </CardContent>
          </Card>
        ))}

        {sortedMolecules.length === 0 && executionState === "running" && (
          <div className="flex items-center justify-center p-8 text-center text-slate-500 dark:text-slate-400">
            <p className="text-sm">执行中，等待生成分子...</p>
          </div>
        )}
      </div>
    </div>
  );
}
