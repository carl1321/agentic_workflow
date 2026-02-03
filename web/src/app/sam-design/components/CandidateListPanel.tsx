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
import { ChevronDown, Box } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "~/components/ui/dialog";
import { Button } from "~/components/ui/button";
import { getScoreColor, formatScore, extractDimScoresFromResolvedInputsPrompt } from "../utils/molecule";
import { apiRequest } from "~/core/api/api-client";
import { executeTool } from "~/core/api/tools";
import type { Molecule, Constraint, DesignObjective } from "../types";
import { ConstraintSatisfactionPanel } from "./ConstraintSatisfactionPanel";
import { MoleculeOptimizationHistory } from "./MoleculeOptimizationHistory";
import { Molecule3DViewer } from "./Molecule3DViewer";

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
  const processingSeqRef = useRef(0); // 用于取消过期的异步处理（避免旧请求覆盖新列表）

  // 从迭代过程的评估节点输出中构建“最后一次出现时的三维评分”（按分子 id 对齐）
  // 这是确定数据源：resolved_inputs.prompt 里三段 JSON（critic_aspect + score）
  type DimScores = {
    surfaceAnchoring?: number;
    // 不同工作流/版本里字段可能不同，这里做兼容保留
    energyLevel?: number;
    packingDensity?: number;
    chemistryValidity?: number;
    defectPassivation?: number;
    [k: string]: number | undefined;
  };
  const lastDimScoresById = useRef<Map<number | string, DimScores>>(new Map());
  useEffect(() => {
    const m = new Map<number | string, DimScores>();

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

        const dimsById = extractDimScoresFromResolvedInputsPrompt(promptText) as Map<number | string, DimScores>;
        for (const [id, dims] of dimsById.entries()) {
          const prev = m.get(id) || {};
          // 以最新一轮为准覆盖（只覆盖有值的维度）
          m.set(id, {
            surfaceAnchoring: dims.surfaceAnchoring ?? prev.surfaceAnchoring,
            energyLevel: dims.energyLevel ?? prev.energyLevel,
            packingDensity: dims.packingDensity ?? prev.packingDensity,
            chemistryValidity: dims.chemistryValidity ?? prev.chemistryValidity,
            defectPassivation: dims.defectPassivation ?? prev.defectPassivation,
          });
        }
      }
    }

    lastDimScoresById.current = m;
  }, [iterationNodeOutputs]);

  // 处理分子：生成图片、评估等
  useEffect(() => {
    const processMolecules = async () => {
      const seq = ++processingSeqRef.current;
      const isStale = () => processingSeqRef.current !== seq;

      const sourceMolecules = molecules.length > 0 ? molecules : (initialMolecules || []);
      if (sourceMolecules.length === 0) {
        setProcessedMolecules([]);
        return;
      }

      try {
        // 先“立刻”展示基础信息（SMILES/分数/约束等），图片和评估结果再逐个补齐
        const baseList: Molecule[] = sourceMolecules.map((mol, idx) => {
          const smiles = mol.smiles || "";
          const cachedUrl = smiles ? imageUrlMapRef.current.get(smiles) : undefined;
          return {
            index: mol.index || idx + 1,
            smiles,
            scaffoldCondition: mol.scaffoldCondition,
            scaffoldSmiles: mol.scaffoldSmiles,
            imageUrl: mol.imageUrl || cachedUrl,
            properties: mol.properties,
            score: mol.score,
            analysis: mol.analysis,
          };
        });
        setProcessedMolecules(baseList);

        const updateOne = (updated: Molecule) => {
          if (isStale()) return;
          setProcessedMolecules((prev) =>
            prev.map((m) => (m.index === updated.index ? updated : m))
          );
        };

        const processOne = async (molecule: Molecule) => {
          // 如果过程中列表已更新（新 seq），放弃更新
          if (isStale()) return;

          const next: Molecule = { ...molecule };

          // 1) 图片：按需生成（不阻塞列表展示）
          if (!next.imageUrl && next.smiles) {
            const cachedUrl = imageUrlMapRef.current.get(next.smiles);
            if (cachedUrl) {
              next.imageUrl = cachedUrl;
              updateOne(next);
            } else if (!processedImagesRef.current.has(next.smiles)) {
              try {
                processedImagesRef.current.add(next.smiles);
                const visResult = await executeTool("visualize_molecules_tool", {
                  smiles_text: `${next.index}. SMILES: ${next.smiles}`,
                });
                const imageIdMatch = visResult.match(/<!--\s*MOLECULAR_IMAGE_ID:([a-f0-9\-]+)\s*-->/i);
                if (imageIdMatch) {
                  next.imageUrl = `/molecular_images/${imageIdMatch[1]}.svg`;
                } else {
                  const imageUrlMatch = visResult.match(/\/molecular_images\/[a-f0-9\-]+\.svg/i);
                  if (imageUrlMatch) next.imageUrl = imageUrlMatch[0];
                }
                if (next.imageUrl) {
                  imageUrlMapRef.current.set(next.smiles, next.imageUrl);
                  updateOne(next);
                } else {
                  processedImagesRef.current.delete(next.smiles); // 允许重试
                }
              } catch (err) {
                console.error(`[CandidateListPanel] ✗ Failed to visualize molecule ${next.index}:`, err);
                processedImagesRef.current.delete(next.smiles); // 允许重试
              }
            }
          }

          // 2) 评估：缺字段才补齐（不阻塞列表展示）
          const needsEvaluation = (mol: Molecule, constraints: Constraint[]): boolean => {
            if (!mol.smiles || !objective?.text) return false;

            const enabledConstraints = constraints.filter((c) => c.enabled);
            if (enabledConstraints.length === 0) return false;

            const isMissing = (v: number | undefined) =>
              v === undefined || v === null || Number.isNaN(v);

            for (const constraint of enabledConstraints) {
              switch (constraint.type) {
                case "surface_anchoring":
                  if (isMissing(mol.score?.surfaceAnchoring)) return true;
                  break;
                case "packing_density":
                  if (isMissing(mol.score?.packingDensity)) return true;
                  break;
                case "energy_level":
                  if (isMissing(mol.properties?.HOMO) || isMissing(mol.properties?.LUMO)) return true;
                  break;
              }
            }

            return false;
          };

          // 重要：历史记录加载/已完成状态不应再触发大模型评估（应优先展示数据库中已有信息）。
          // 仅在“运行中”才允许按需补齐缺失字段，避免每次打开历史都调用 LLM。
          if (executionState === "running" && needsEvaluation(next, constraints) && objective?.text) {
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
                  smiles: next.smiles,
                  objective: objective.text,
                  constraints: constraints.map((c) => ({
                    name: c.name,
                    value: c.value,
                    enabled: c.enabled,
                  })),
                  properties: next.properties,
                }),
              });

              if (evalResult.success) {
                const isMissing = (v: number | undefined) =>
                  v === undefined || v === null || Number.isNaN(v);

                next.score = {
                  total: !isMissing(next.score?.total) ? next.score!.total : evalResult.score.total,
                  surfaceAnchoring: !isMissing(next.score?.surfaceAnchoring)
                    ? next.score!.surfaceAnchoring
                    : evalResult.score.surfaceAnchoring,
                  energyLevel: !isMissing(next.score?.energyLevel)
                    ? next.score!.energyLevel
                    : evalResult.score.energyLevel,
                  packingDensity: !isMissing(next.score?.packingDensity)
                    ? next.score!.packingDensity
                    : evalResult.score.packingDensity,
                };

                next.analysis = next.analysis || {
                  description: evalResult.description,
                  explanation: evalResult.explanation,
                };

                if (evalResult.properties) {
                  next.properties = {
                    HOMO: !isMissing(next.properties?.HOMO) ? next.properties!.HOMO : evalResult.properties.HOMO,
                    LUMO: !isMissing(next.properties?.LUMO) ? next.properties!.LUMO : evalResult.properties.LUMO,
                    DM: !isMissing(next.properties?.DM) ? next.properties!.DM : evalResult.properties.DM,
                  };
                }
                updateOne(next);
              }
            } catch (err) {
              console.error(`Failed to evaluate molecule ${next.index}:`, err);
            }
          }

          // 3) 维度评分兜底：用迭代评估节点输出补齐缺失维度（按分子 id 对齐）
          if (next.score) {
            const moleculeId = next.index; // 当前项目内 index 实际承载了 workflow 的分子 id
            const fallback = lastDimScoresById.current.get(moleculeId);
            const isMissing = (v: number | undefined) =>
              v === undefined || v === null || Number.isNaN(v);

            next.score = {
              ...next.score,
              surfaceAnchoring: !isMissing(next.score.surfaceAnchoring)
                ? next.score.surfaceAnchoring
                : fallback?.surfaceAnchoring,
              energyLevel: !isMissing(next.score.energyLevel)
                ? next.score.energyLevel
                : fallback?.energyLevel,
              packingDensity: !isMissing(next.score.packingDensity)
                ? next.score.packingDensity
                : fallback?.packingDensity,
            };

            const sa = next.score.surfaceAnchoring;
            const el = next.score.energyLevel;
            const pd = next.score.packingDensity;
            const dims = [sa, el, pd].filter((v) => typeof v === "number") as number[];
            const totalMissing =
              next.score.total === undefined || next.score.total === null || Number.isNaN(next.score.total);
            if (totalMissing && dims.length > 0) {
              next.score.total = Math.round((dims.reduce((a, b) => a + b, 0) / dims.length) * 10) / 10;
            }
            updateOne(next);
          }
        };

        // 控制并发，避免同时触发过多图片/评估请求
        const CONCURRENCY = 3;
        const queue = [...baseList];
        const workers = Array.from({ length: Math.min(CONCURRENCY, queue.length) }, async () => {
          while (queue.length > 0 && !isStale()) {
            const item = queue.shift();
            if (!item) break;
            await processOne(item);
          }
        });
        await Promise.all(workers);
      } catch (err) {
        console.error("[CandidateListPanel] Failed to process molecules:", err);
        // 失败时也至少展示原始列表
        setProcessedMolecules(sourceMolecules);
      }
    };

    processMolecules();
    return () => {
      // 使当前批次处理过期，避免异步回调覆盖新列表
      processingSeqRef.current += 1;
    };
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
              {/* SMILES 图片 + 3D 查看入口 */}
              {molecule.imageUrl ? (
                <div className="space-y-2">
                  <div className="flex justify-center rounded border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-800">
                    <img
                      src={molecule.imageUrl}
                      alt={`Molecule ${molecule.index}`}
                      className="max-h-32 max-w-full"
                      onError={(e) => {
                        console.error(`[CandidateListPanel] Failed to load image for molecule ${molecule.index}: ${molecule.imageUrl}`);
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
                  {/* 3D 结构：支持拖拽旋转、滚轮缩放 */}
                  <Dialog>
                    <DialogTrigger asChild>
                      <Button variant="outline" size="sm" className="w-full text-xs">
                        <Box className="mr-1.5 h-3.5 w-3.5" />
                        3D 结构（旋转/缩放）
                      </Button>
                    </DialogTrigger>
                    <DialogContent className="max-w-2xl">
                      <DialogHeader>
                        <DialogTitle>分子 #{molecule.index} · 3D 结构</DialogTitle>
                      </DialogHeader>
                      <Molecule3DViewer
                        smiles={molecule.smiles}
                        width="100%"
                        height={400}
                        backgroundColor="white"
                      />
                    </DialogContent>
                  </Dialog>
                </div>
              ) : (
                <div className="space-y-2">
                  <div className="flex items-center justify-center rounded border border-slate-200 bg-slate-50 p-4 text-xs text-slate-500 dark:border-slate-700 dark:bg-slate-800">
                    {molecule.smiles}
                  </div>
                  {molecule.smiles && (
                    <Dialog>
                      <DialogTrigger asChild>
                        <Button variant="outline" size="sm" className="w-full text-xs">
                          <Box className="mr-1.5 h-3.5 w-3.5" />
                          3D 结构（旋转/缩放）
                        </Button>
                      </DialogTrigger>
                      <DialogContent className="max-w-2xl">
                        <DialogHeader>
                          <DialogTitle>分子 #{molecule.index} · 3D 结构</DialogTitle>
                        </DialogHeader>
                        <Molecule3DViewer
                          smiles={molecule.smiles}
                          width="100%"
                          height={400}
                          backgroundColor="white"
                        />
                      </DialogContent>
                    </Dialog>
                  )}
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
