"use client";

// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { Check } from "lucide-react";
import { cn } from "~/lib/utils";
import type { DesignStep } from "../types";

interface DesignStepperProps {
  /** 当前步骤 */
  currentStep: DesignStep;
  /** 步骤变更回调 */
  onStepChange?: (step: DesignStep) => void;
  /** 是否允许点击切换步骤 */
  allowStepClick?: boolean;
}

const STEPS: Array<{ id: DesignStep; label: string; shortLabel: string }> = [
  { id: "step1", label: "定义目标与约束", shortLabel: "1" },
  { id: "step2", label: "运行设计实验室", shortLabel: "2" },
  { id: "step3", label: "审查与比较候选", shortLabel: "3" },
];

/**
 * 获取步骤的索引
 */
function getStepIndex(step: DesignStep): number {
  return STEPS.findIndex((s) => s.id === step);
}

/**
 * 步骤导航组件
 */
export function DesignStepper({
  currentStep,
  onStepChange,
  allowStepClick = false,
}: DesignStepperProps) {
  const currentIndex = getStepIndex(currentStep);

  return (
    <div className="flex w-full items-center justify-center px-2 py-3 sm:px-4 sm:py-4">
      <div className="flex w-full max-w-4xl items-center justify-between gap-2 sm:gap-4">
        {STEPS.map((step, index) => {
          const stepIndex = index;
          const isActive = step.id === currentStep;
          const isCompleted = stepIndex < currentIndex;
          const isClickable = allowStepClick && (isCompleted || isActive);

          return (
            <div
              key={step.id}
              className={cn(
                "flex flex-1 items-center",
                index < STEPS.length - 1 && "flex-1"
              )}
            >
              {/* 步骤按钮 */}
              <button
                type="button"
                onClick={() => {
                  if (isClickable && onStepChange) {
                    onStepChange(step.id);
                  }
                }}
                disabled={!isClickable}
                className={cn(
                  "flex flex-col items-center gap-2 transition-all",
                  isClickable && "cursor-pointer hover:opacity-80",
                  !isClickable && "cursor-default"
                )}
              >
                {/* 步骤编号/图标 */}
                <div
                  className={cn(
                    "flex h-8 w-8 items-center justify-center rounded-full border-2 transition-all sm:h-10 sm:w-10",
                    isActive &&
                      "border-blue-500 bg-blue-500 text-white dark:border-blue-600 dark:bg-blue-600",
                    isCompleted &&
                      "border-blue-500 bg-blue-500 text-white dark:border-blue-600 dark:bg-blue-600",
                    !isActive &&
                      !isCompleted &&
                      "border-slate-300 bg-white text-slate-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-400"
                  )}
                >
                  {isCompleted ? (
                    <Check className="h-4 w-4 sm:h-5 sm:w-5" />
                  ) : (
                    <span className="text-xs font-semibold sm:text-sm">{stepIndex + 1}</span>
                  )}
                </div>

                {/* 步骤标签 */}
                <div className="flex flex-col items-center gap-1">
                  <span
                    className={cn(
                      "text-xs font-medium transition-colors sm:text-sm",
                      isActive &&
                        "text-blue-600 dark:text-blue-400",
                      isCompleted &&
                        "text-blue-600 dark:text-blue-400",
                      !isActive &&
                        !isCompleted &&
                        "text-slate-500 dark:text-slate-400"
                    )}
                  >
                    {step.label}
                  </span>
                </div>
              </button>

              {/* 连接线 */}
              {index < STEPS.length - 1 && (
                <div
                  className={cn(
                    "mx-2 h-0.5 flex-1 transition-colors sm:mx-4",
                    stepIndex < currentIndex
                      ? "bg-blue-500 dark:bg-blue-600"
                      : "bg-slate-200 dark:bg-slate-700"
                  )}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

