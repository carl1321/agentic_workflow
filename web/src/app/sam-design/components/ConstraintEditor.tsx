"use client";

// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { nanoid } from "nanoid";
import { Plus, Trash2, RotateCcw } from "lucide-react";
import { Button } from "~/components/ui/button";
import { Input } from "~/components/ui/input";
import { Label } from "~/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "~/components/ui/select";
import { Checkbox } from "~/components/ui/checkbox";
import { Card, CardContent, CardHeader, CardTitle } from "~/components/ui/card";
import type { Constraint, ConstraintType } from "../types";
import { CONSTRAINT_TYPE_CONFIGS } from "../types";

interface ConstraintEditorProps {
  /** 约束列表 */
  constraints: Constraint[];
  /** 约束变更回调 */
  onConstraintsChange: (constraints: Constraint[]) => void;
}

/**
 * 约束编辑器组件
 */
export function ConstraintEditor({
  constraints,
  onConstraintsChange,
}: ConstraintEditorProps) {

  /**
   * 添加新约束
   */
  const handleAddConstraint = () => {
    // 使用nanoid生成唯一ID，避免hydration错误
    const newConstraint: Constraint = {
      id: `constraint-${nanoid()}`,
      name: "新约束",
      type: "custom",
      valueType: "text",
      value: "",
      enabled: true,
    };
    onConstraintsChange([...constraints, newConstraint]);
  };

  /**
   * 删除约束
   */
  const handleDeleteConstraint = (id: string) => {
    onConstraintsChange(constraints.filter((c) => c.id !== id));
  };

  /**
   * 更新约束
   */
  const handleUpdateConstraint = (id: string, updates: Partial<Constraint>) => {
    onConstraintsChange(
      constraints.map((c) => (c.id === id ? { ...c, ...updates } : c))
    );
  };

  /**
   * 根据约束类型获取配置
   */
  const getConstraintConfig = (type: ConstraintType) => {
    return CONSTRAINT_TYPE_CONFIGS.find((config) => config.type === type);
  };

  /**
   * 处理约束类型变更
   */
  const handleTypeChange = (id: string, newType: ConstraintType) => {
    const config = getConstraintConfig(newType);
    if (!config) return;

    const constraint = constraints.find((c) => c.id === id);
    if (!constraint) return;

    const updates: Partial<Constraint> = {
      type: newType,
      valueType: config.valueType,
      options: config.options,
      unit: config.defaultUnit,
    };

    // 根据类型设置默认值
    if (config.valueType === "select" && config.options && config.options.length > 0) {
      updates.value = config.options[0];
    } else if (config.valueType === "range") {
      updates.value = { min: -0.2, max: 0.2 };
    } else {
      updates.value = "";
    }

    handleUpdateConstraint(id, updates);
  };

  return (
    <div className="flex flex-col gap-4">
      {/* 约束列表：3列并排 */}
      <div className="grid grid-cols-3 gap-4">
        {constraints.length === 0 ? (
          <div className="col-span-full rounded-lg border border-dashed border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-800/50 py-8 text-center">
            <p className="text-sm text-slate-500 dark:text-slate-400">
              暂无约束条件。点击下方按钮添加约束。
            </p>
          </div>
        ) : (
          constraints.map((constraint) => {
            const config = getConstraintConfig(constraint.type);
            const isRangeType = constraint.valueType === "range";
            const rangeValue =
              typeof constraint.value === "object" && "min" in constraint.value
                ? constraint.value
                : { min: -0.2, max: 0.2 };

            return (
              <Card key={constraint.id} className="relative shadow-sm flex flex-col">
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                      <Checkbox
                        checked={constraint.enabled}
                        onCheckedChange={(checked) =>
                          handleUpdateConstraint(constraint.id, {
                            enabled: checked === true,
                          })
                        }
                        className="shrink-0"
                      />
                      <CardTitle className="text-sm font-medium truncate">
                        {constraint.name || config?.label || "约束"}
                      </CardTitle>
                    </div>
                    {constraints.length > 1 && (
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => handleDeleteConstraint(constraint.id)}
                        className="h-7 w-7 shrink-0 text-slate-500 hover:text-destructive dark:text-slate-400"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    )}
                  </div>
                </CardHeader>
                <CardContent className="space-y-3 pt-0 flex-1">
                  {/* 约束类型选择 - 仅自定义约束显示 */}
                  {constraint.type === "custom" && (
                    <div className="space-y-1.5">
                      <Label htmlFor={`type-${constraint.id}`} className="text-xs font-medium">约束类型</Label>
                      <Select
                        value={constraint.type}
                        onValueChange={(value) =>
                          handleTypeChange(constraint.id, value as ConstraintType)
                        }
                      >
                        <SelectTrigger id={`type-${constraint.id}`} className="w-full h-8 text-xs">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {CONSTRAINT_TYPE_CONFIGS.map((config) => (
                            <SelectItem key={config.type} value={config.type}>
                              {config.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  )}

                  {/* 约束名称（自定义类型时显示） */}
                  {constraint.type === "custom" && (
                    <div className="space-y-1.5">
                      <Label htmlFor={`name-${constraint.id}`} className="text-xs font-medium">约束名称</Label>
                      <Input
                        id={`name-${constraint.id}`}
                        value={constraint.name}
                        onChange={(e) =>
                          handleUpdateConstraint(constraint.id, { name: e.target.value })
                        }
                        placeholder="请输入约束名称"
                        className="h-8 text-xs"
                      />
                    </div>
                  )}

                  {/* 约束值输入 */}
                  {constraint.valueType === "select" && constraint.options && (
                    <div className="space-y-1.5">
                      <Label htmlFor={`value-${constraint.id}`} className="text-xs font-medium">值</Label>
                      <Select
                        value={String(constraint.value)}
                        onValueChange={(value) =>
                          handleUpdateConstraint(constraint.id, { value })
                        }
                      >
                        <SelectTrigger id={`value-${constraint.id}`} className="w-full h-8 text-xs">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {constraint.options.map((option) => (
                            <SelectItem key={option} value={option}>
                              {option}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  )}

                  {constraint.valueType === "range" && (
                    <div className="space-y-1.5">
                      <Label className="text-xs font-medium">范围</Label>
                      <div className="flex items-center gap-1.5">
                        <Input
                          type="number"
                          value={rangeValue.min}
                          onChange={(e) =>
                            handleUpdateConstraint(constraint.id, {
                              value: {
                                min: parseFloat(e.target.value) || 0,
                                max: rangeValue.max,
                              },
                            })
                          }
                          placeholder="最小"
                          step="0.1"
                          className="flex-1 text-xs h-8"
                        />
                        <span className="text-xs text-slate-500 dark:text-slate-400 shrink-0">~</span>
                        <Input
                          type="number"
                          value={rangeValue.max}
                          onChange={(e) =>
                            handleUpdateConstraint(constraint.id, {
                              value: {
                                min: rangeValue.min,
                                max: parseFloat(e.target.value) || 0,
                              },
                            })
                          }
                          placeholder="最大"
                          step="0.1"
                          className="flex-1 text-xs h-8"
                        />
                        {constraint.unit && (
                          <span className="text-xs text-slate-500 dark:text-slate-400 shrink-0">
                            {constraint.unit}
                          </span>
                        )}
                      </div>
                    </div>
                  )}

                  {(constraint.valueType === "text" || constraint.valueType === "number") && (
                    <div className="space-y-1.5">
                      <Label htmlFor={`value-${constraint.id}`} className="text-xs font-medium">值</Label>
                      <div className="flex items-center gap-2">
                        <Input
                          id={`value-${constraint.id}`}
                          type={constraint.valueType === "number" ? "number" : "text"}
                          value={String(constraint.value)}
                          onChange={(e) =>
                            handleUpdateConstraint(constraint.id, {
                              value:
                                constraint.valueType === "number"
                                  ? parseFloat(e.target.value) || 0
                                  : e.target.value,
                            })
                          }
                          placeholder={config?.placeholder || "请输入值"}
                          className="flex-1 h-8 text-xs"
                        />
                        {constraint.unit && (
                          <span className="text-xs text-slate-500 dark:text-slate-400 shrink-0">
                            {constraint.unit}
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            );
          })
        )}
      </div>

      {/* 添加约束和恢复默认按钮 */}
      <div className="col-span-full pt-2 flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          onClick={handleAddConstraint}
          className="w-full sm:w-auto"
        >
          <Plus className="mr-2 h-4 w-4" />
          添加约束
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            // 恢复默认的三个约束
            const defaultConstraints = [
              {
                id: `constraint-${nanoid()}`,
                name: "表面锚定强度",
                type: "surface_anchoring" as const,
                valueType: "select" as const,
                value: "High",
                enabled: true,
                options: ["High", "Medium", "Low"],
              },
              {
                id: `constraint-${nanoid()}`,
                name: "能级匹配",
                type: "energy_level" as const,
                valueType: "range" as const,
                value: { min: -0.2, max: 0.2 },
                enabled: true,
                unit: "eV",
              },
              {
                id: `constraint-${nanoid()}`,
                name: "膜致密度和稳定性",
                type: "packing_density" as const,
                valueType: "select" as const,
                value: "High",
                enabled: true,
                options: ["High", "Medium", "Low"],
              },
            ];
            onConstraintsChange(defaultConstraints);
          }}
          className="w-full sm:w-auto"
        >
          <RotateCcw className="mr-2 h-4 w-4" />
          恢复默认约束
        </Button>
      </div>
    </div>
  );
}

