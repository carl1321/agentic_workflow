"use client";

// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { useState, useEffect } from "react";
import { DesignStepper } from "./components/DesignStepper";
import { Step1DefineObjective } from "./components/Step1DefineObjective";
import { Step2RunDesignLab } from "./components/Step2RunDesignLab";
import { Step3ReviewCandidates } from "./components/Step3ReviewCandidates";
import { HistoryList } from "./components/HistoryList";
import { Button } from "~/components/ui/button";
import { History } from "lucide-react";
import { getDesignHistory } from "~/core/api/sam-design";
import { toast } from "sonner";
import type { DesignStep, DesignState, DesignObjective, Constraint, ExecutionResult, DesignHistory, Molecule } from "./types";

/**
 * 从 localStorage 加载设计状态
 */
function loadDesignState(): Partial<DesignState> {
  if (typeof window === "undefined") return {};
  try {
    const saved = localStorage.getItem("sam-design-state");
    if (saved) {
      return JSON.parse(saved);
    }
  } catch (error) {
    console.error("Failed to load design state:", error);
  }
  return {};
}

/**
 * 保存设计状态到 localStorage
 */
function saveDesignState(state: DesignState) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem("sam-design-state", JSON.stringify(state));
  } catch (error) {
    console.error("Failed to save design state:", error);
  }
}

/**
 * SAM分子设计主页面
 */
export default function SAMDesignPage() {
  // 使用useState和useEffect来避免hydration错误
  const [isClient, setIsClient] = useState(false);
  const [currentStep, setCurrentStep] = useState<DesignStep>("step1");
  const [objective, setObjective] = useState<DesignObjective>({ text: "" });
  const [constraints, setConstraints] = useState<Constraint[]>([]);
  const [taskName] = useState<string>("SAM 分子设计");
  const [taskStatus] = useState<"preparing" | "running" | "completed" | "failed">("preparing");
  const [executionResult, setExecutionResult] = useState<ExecutionResult | null>(null);
  const [historyDialogOpen, setHistoryDialogOpen] = useState(false);
  const [historyMolecules, setHistoryMolecules] = useState<Molecule[] | undefined>(undefined); // 从历史记录加载的完整分子数据

  // 在客户端加载保存的状态
  useEffect(() => {
    setIsClient(true);
    const savedState = loadDesignState();
    
    if (savedState.currentStep) {
      setCurrentStep(savedState.currentStep as DesignStep);
    }
    if (savedState.objective) {
      setObjective(savedState.objective);
    }
    if (savedState.constraints && savedState.constraints.length > 0) {
      setConstraints(savedState.constraints);
    } else {
      // 只在客户端生成默认约束，使用固定ID避免hydration错误
      const defaultConstraints: Constraint[] = [
        {
          id: "constraint-1-default",
          name: "表面锚定强度",
          type: "surface_anchoring",
          valueType: "select",
          value: "High",
          enabled: true,
          options: ["High", "Medium", "Low"],
        },
        {
          id: "constraint-2-default",
          name: "能级匹配",
          type: "energy_level",
          valueType: "range",
          value: { min: -0.2, max: 0.2 },
          enabled: true,
          unit: "eV",
        },
        {
          id: "constraint-3-default",
          name: "膜致密度和稳定性",
          type: "packing_density",
          valueType: "select",
          value: "High",
          enabled: true,
          options: ["High", "Medium", "Low"],
        },
      ];
      setConstraints(defaultConstraints);
    }
    if (savedState.taskName) {
      // taskName is already initialized, but we can update it if needed
    }
    if (savedState.taskStatus) {
      // taskStatus is already initialized, but we can update it if needed
    }
  }, []);

  // 保存状态到 localStorage
  useEffect(() => {
    if (!isClient) return; // 只在客户端保存
    
    const state: DesignState = {
      currentStep,
      objective,
      constraints,
      taskName,
      taskStatus,
      executionResult,
    };
    saveDesignState(state);
  }, [currentStep, objective, constraints, taskName, taskStatus, executionResult, isClient]);

  /**
   * 处理步骤变更
   */
  const handleStepChange = (step: DesignStep) => {
    // 验证是否可以切换到该步骤
    if (step === "step1") {
      setCurrentStep(step);
    } else if (step === "step2") {
      // 验证 Step 1 是否完成
      if (objective.text.trim().length > 0) {
        setCurrentStep(step);
      }
    } else if (step === "step3") {
      // 验证前面的步骤是否完成
      if (objective.text.trim().length > 0) {
        setCurrentStep(step);
      }
    }
  };

  /**
   * 处理下一步
   */
  const handleNext = () => {
    if (currentStep === "step1") {
      setCurrentStep("step2");
    } else if (currentStep === "step2") {
      setCurrentStep("step3");
    }
  };

  /**
   * 处理上一步
   */
  const handleBack = () => {
    if (currentStep === "step2") {
      setCurrentStep("step1");
    } else if (currentStep === "step3") {
      setCurrentStep("step2");
    }
  };

  /**
   * 处理执行完成
   */
  const handleExecutionComplete = (result: ExecutionResult) => {
    setExecutionResult(result);
    // 自动跳转到Step3
    setTimeout(() => {
      setCurrentStep("step3");
    }, 1000);
  };

  /**
   * 处理选择历史记录
   */
  const handleSelectHistory = async (historyId: string) => {
    try {
      const result = await getDesignHistory(historyId);
      if (result.success && result.history) {
        const history: DesignHistory = result.history;
        
        // 加载历史记录数据
        setObjective(history.objective);
        setConstraints(history.constraints);
        setExecutionResult(history.executionResult);
        setHistoryMolecules(history.molecules); // 保存完整的分子数据（包含评估结果）
        
        // 跳转到Step3
        setCurrentStep("step3");
        
        toast.success("历史记录加载成功");
      } else {
        toast.error("加载历史记录失败");
      }
    } catch (error: any) {
      console.error("Failed to load history:", error);
      toast.error(`加载历史记录失败: ${error.message}`);
    }
  };

  /**
   * 处理重新设计
   */
  const handleRedesign = () => {
    // 保留objective和constraints，清空executionResult和历史分子数据
    setExecutionResult(null);
    setHistoryMolecules(undefined);
    setCurrentStep("step1");
  };

  /**
   * 渲染当前步骤的内容
   */
  const renderStepContent = () => {
    switch (currentStep) {
      case "step1":
        return (
          <Step1DefineObjective
            objective={objective}
            onObjectiveChange={setObjective}
            constraints={constraints}
            onConstraintsChange={setConstraints}
            onNext={handleNext}
            showValidation={true}
            headerRight={
              <Button
                variant="outline"
                size="sm"
                onClick={() => setHistoryDialogOpen(true)}
                className="flex items-center gap-2"
              >
                <History className="h-4 w-4" />
                运行历史
              </Button>
            }
          />
        );
      case "step2":
        return (
          <Step2RunDesignLab
            onBack={handleBack}
            objective={objective}
            constraints={constraints}
            onExecutionComplete={handleExecutionComplete}
            headerRight={
              <Button
                variant="outline"
                size="sm"
                onClick={() => setHistoryDialogOpen(true)}
                className="flex items-center gap-2"
              >
                <History className="h-4 w-4" />
                运行历史
              </Button>
            }
          />
        );
      case "step3":
        return (
          <Step3ReviewCandidates
            onBack={handleBack}
            onRedesign={handleRedesign}
            executionResult={executionResult}
            objective={objective}
            constraints={constraints}
            initialMolecules={historyMolecules}
            headerRight={
              <Button
                variant="outline"
                size="sm"
                onClick={() => setHistoryDialogOpen(true)}
                className="flex items-center gap-2"
              >
                <History className="h-4 w-4" />
                运行历史
              </Button>
            }
          />
        );
      default:
        return null;
    }
  };

  return (
    <div className="flex min-h-screen flex-col bg-slate-50 dark:bg-slate-950">
      {/* 顶部栏：步骤导航 */}
      <div className="relative bg-white dark:bg-slate-900">
        <div className="container mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between border-b border-slate-200 dark:border-slate-700">
            {/* 步骤导航 */}
            <div className="flex-1">
              <DesignStepper
                currentStep={currentStep}
                onStepChange={handleStepChange}
                allowStepClick={true}
              />
            </div>
          </div>
        </div>
      </div>

      {/* 主内容区域 */}
      <main className="flex-1">
        <div className="container mx-auto max-w-7xl px-4 py-6 sm:px-6 sm:py-8 lg:px-8 lg:py-10">
          {renderStepContent()}
        </div>
      </main>

      {/* 历史记录列表弹窗 */}
      <HistoryList
        open={historyDialogOpen}
        onClose={() => setHistoryDialogOpen(false)}
        onSelect={handleSelectHistory}
      />
    </div>
  );
}
