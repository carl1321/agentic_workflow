"use client";

// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { useState } from "react";
import { ArrowRight, Lightbulb } from "lucide-react";
import { Button } from "~/components/ui/button";
import { Textarea } from "~/components/ui/textarea";
import { Label } from "~/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "~/components/ui/card";
import { ConstraintEditor } from "./ConstraintEditor";
import type { Constraint, DesignObjective } from "../types";

interface Step1DefineObjectiveProps {
  /** 研究目标 */
  objective: DesignObjective;
  /** 研究目标变更回调 */
  onObjectiveChange: (objective: DesignObjective) => void;
  /** 约束列表 */
  constraints: Constraint[];
  /** 约束变更回调 */
  onConstraintsChange: (constraints: Constraint[]) => void;
  /** 下一步回调 */
  onNext: () => void;
  /** 是否显示验证错误 */
  showValidation?: boolean;
  /** 右上角操作区（例如：运行历史按钮） */
  headerRight?: React.ReactNode;
}

/**
 * 示例目标模板（中文）
 */
const EXAMPLE_OBJECTIVES = [
  "生成3个包含咔唑骨架和磷酸锚定基团的SAM分子。",
  "设计5个具有高表面锚定强度和优异能级匹配的SAM分子，用于钙钛矿太阳能电池。",
  "生成10个包含苯并噻吩骨架和羧酸锚定基团的SAM分子，要求能级在-4.5到-5.0 eV之间。",
];

/**
 * Step 1: 定义目标和约束组件
 */
export function Step1DefineObjective({
  objective,
  onObjectiveChange,
  constraints,
  onConstraintsChange,
  onNext,
  showValidation = false,
  headerRight,
}: Step1DefineObjectiveProps) {
  const [showExamples, setShowExamples] = useState(false);
  const [charCount, setCharCount] = useState(objective.text.length);

  /**
   * 处理目标文本变更
   */
  const handleObjectiveChange = (text: string) => {
    setCharCount(text.length);
    onObjectiveChange({ text });
  };

  /**
   * 使用示例目标
   */
  const handleUseExample = (example: string) => {
    handleObjectiveChange(example);
    setShowExamples(false);
  };

  /**
   * 验证表单
   */
  const isValid = objective.text.trim().length > 0;

  /**
   * 处理下一步
   */
  const handleNext = () => {
    if (isValid) {
      onNext();
    }
  };

  return (
    <div className="flex flex-col gap-8">
      {/* 顶部：标题 */}
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-2">
          <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100 sm:text-xl">
            指导分子生成
          </h1>
          <p className="text-sm text-slate-600 dark:text-slate-400">
            输入研究目标和关键约束条件，指导分子生成过程
          </p>
        </div>
        {headerRight ? <div className="pt-1">{headerRight}</div> : null}
      </div>

      {/* 研究目标：占满一行 */}
      <Card className="shadow-sm">
        <CardHeader className="pb-4">
          <CardTitle className="text-lg">研究目标</CardTitle>
          <CardDescription className="text-sm text-slate-600 dark:text-slate-400">
            请描述您的分子设计目标
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="objective-input" className="text-sm font-medium">
              研究目标描述
            </Label>
            <Textarea
              id="objective-input"
              value={objective.text}
              onChange={(e) => handleObjectiveChange(e.target.value)}
              placeholder="例如：设计一个具有强表面锚定、良好能级匹配和致密稳定膜形成的SAM分子"
              className="min-h-32 resize-none text-sm"
              aria-invalid={showValidation && !isValid}
            />
            <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
              <span>
                {showValidation && !isValid && (
                  <span className="text-destructive">研究目标不能为空</span>
                )}
              </span>
              <span>{charCount} 字符</span>
            </div>
          </div>

          {/* 示例链接和下一步按钮 */}
          <div className="flex items-center justify-between pt-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setShowExamples(!showExamples)}
              className="h-auto p-0 text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
            >
              <Lightbulb className="mr-1.5 h-4 w-4" />
              <span className="text-sm">查看示例</span>
              <ArrowRight className="ml-1.5 h-3.5 w-3.5" />
            </Button>
            <Button
              type="button"
              onClick={handleNext}
              disabled={!isValid}
              className="ml-auto"
            >
              分子生成
              <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
          </div>

          {/* 示例列表 */}
          {showExamples && (
            <Card className="border-blue-200 bg-blue-50 dark:border-blue-800 dark:bg-blue-900/20">
              <CardContent className="pt-5">
                <div className="space-y-3">
                  <p className="text-sm font-medium text-blue-900 dark:text-blue-100">
                    选择示例目标：
                  </p>
                  {EXAMPLE_OBJECTIVES.map((example, index) => (
                    <button
                      key={index}
                      type="button"
                      onClick={() => handleUseExample(example)}
                      className="w-full rounded-md border border-blue-200 bg-white p-3 text-left text-sm text-slate-700 transition-colors hover:border-blue-300 hover:bg-blue-50 dark:border-blue-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:border-blue-600 dark:hover:bg-blue-900/30"
                    >
                      {example}
                    </button>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </CardContent>
      </Card>

      {/* 关键约束：3列并排 */}
      <Card className="shadow-sm">
        <CardHeader className="pb-4">
          <CardTitle className="text-lg">关键约束</CardTitle>
          <CardDescription className="text-sm text-slate-600 dark:text-slate-400">
            设置约束条件有助于指导分子生成，非必填项
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ConstraintEditor
            constraints={constraints}
            onConstraintsChange={onConstraintsChange}
          />
        </CardContent>
      </Card>
    </div>
  );
}

