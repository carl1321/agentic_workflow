"use client";

// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { CheckCircle2, XCircle, HelpCircle } from "lucide-react";
import type { Molecule, Constraint } from "../types";

interface ConstraintSatisfactionPanelProps {
  molecule: Molecule;
  constraints: Constraint[];
}

/**
 * 约束满足情况面板
 */
export function ConstraintSatisfactionPanel({
  molecule,
  constraints,
}: ConstraintSatisfactionPanelProps) {
  // 评估单个约束是否满足
  const evaluateConstraint = (constraint: Constraint): {
    status: "pass" | "fail" | "unknown";
    reason: string;
  } => {
    if (!constraint.enabled) {
      return { status: "unknown", reason: "约束未启用" };
    }

    const score = molecule.score;
    const properties = molecule.properties;

    switch (constraint.type) {
      case "surface_anchoring": {
        if (!score?.surfaceAnchoring) {
          return { status: "unknown", reason: "缺少表面锚定强度评分数据" };
        }
        // 默认阈值：>=60 视为满足
        const threshold = constraint.value === "High" ? 80 : constraint.value === "Medium" ? 60 : 40;
        const passed = score.surfaceAnchoring >= threshold;
        return {
          status: passed ? "pass" : "fail",
          reason: passed
            ? `评分 ${score.surfaceAnchoring.toFixed(1)} >= ${threshold}（${constraint.value}）`
            : `评分 ${score.surfaceAnchoring.toFixed(1)} < ${threshold}（${constraint.value}），差距 ${(threshold - score.surfaceAnchoring).toFixed(1)}`,
        };
      }

      case "energy_level": {
        if (!properties?.HOMO || !properties?.LUMO) {
          return { status: "unknown", reason: "缺少能级数据（HOMO/LUMO）" };
        }
        // 能级匹配：计算 HOMO-LUMO gap 或与目标能级的差值
        const gap = properties.LUMO - properties.HOMO;
        if (typeof constraint.value === "object" && constraint.value.min !== undefined && constraint.value.max !== undefined) {
          const passed = gap >= constraint.value.min && gap <= constraint.value.max;
          return {
            status: passed ? "pass" : "fail",
            reason: passed
              ? `能级差 ${gap.toFixed(2)} eV 在范围内 [${constraint.value.min}, ${constraint.value.max}]`
              : `能级差 ${gap.toFixed(2)} eV 超出范围 [${constraint.value.min}, ${constraint.value.max}]，超出 ${Math.max(0, constraint.value.min - gap, gap - constraint.value.max).toFixed(2)} eV`,
          };
        }
        return { status: "unknown", reason: "能级约束格式不正确" };
      }

      case "packing_density": {
        if (!score?.packingDensity) {
          return { status: "unknown", reason: "缺少膜致密度评分数据" };
        }
        // 默认阈值：>=60 视为满足
        const threshold = constraint.value === "High" ? 80 : constraint.value === "Medium" ? 60 : 40;
        const passed = score.packingDensity >= threshold;
        return {
          status: passed ? "pass" : "fail",
          reason: passed
            ? `评分 ${score.packingDensity.toFixed(1)} >= ${threshold}（${constraint.value}）`
            : `评分 ${score.packingDensity.toFixed(1)} < ${threshold}（${constraint.value}），差距 ${(threshold - score.packingDensity).toFixed(1)}`,
        };
      }

      case "custom": {
        // 自定义约束：无法自动判断
        return { status: "unknown", reason: "自定义约束需要人工判断" };
      }

      default:
        return { status: "unknown", reason: "未知约束类型" };
    }
  };

  const enabledConstraints = constraints.filter((c) => c.enabled);

  if (enabledConstraints.length === 0) {
    return (
      <div className="text-xs text-slate-500 dark:text-slate-400">
        无启用的约束
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {enabledConstraints.map((constraint) => {
        const evaluation = evaluateConstraint(constraint);
        const Icon =
          evaluation.status === "pass"
            ? CheckCircle2
            : evaluation.status === "fail"
            ? XCircle
            : HelpCircle;
        const iconColor =
          evaluation.status === "pass"
            ? "text-green-600 dark:text-green-400"
            : evaluation.status === "fail"
            ? "text-red-600 dark:text-red-400"
            : "text-slate-400 dark:text-slate-500";

        return (
          <div
            key={constraint.id}
            className="flex items-start gap-2 rounded border border-slate-200 bg-slate-50 p-2 dark:border-slate-700 dark:bg-slate-800"
          >
            <Icon className={`h-4 w-4 shrink-0 ${iconColor} mt-0.5`} />
            <div className="flex-1 space-y-0.5">
              <div className="text-xs font-medium text-slate-900 dark:text-slate-100">
                {constraint.name}
              </div>
              <div className={`text-[10px] ${iconColor}`}>
                {evaluation.reason}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
