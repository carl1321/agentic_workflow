// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "~/components/ui/select";
import { Label } from "~/components/ui/label";

export type OutputFormat = "output" | "array" | "object" | "string" | "number";

interface OutputFormatSelectorProps {
  value: OutputFormat;
  onChange: (value: OutputFormat) => void;
  label?: string;
  description?: string;
}

const FORMAT_OPTIONS: Array<{ value: OutputFormat; label: string; description: string }> = [
  {
    value: "output",
    label: "输出 (output)",
    description: "默认输出字段，保持原始输出格式",
  },
  {
    value: "array",
    label: "数组 (array)",
    description: "将输出转换为数组格式",
  },
  {
    value: "object",
    label: "对象 (object)",
    description: "将输出转换为对象格式",
  },
  {
    value: "string",
    label: "字符串 (string)",
    description: "将输出转换为字符串格式",
  },
  {
    value: "number",
    label: "数值 (number)",
    description: "将输出转换为数值格式",
  },
];

export function OutputFormatSelector({
  value = "output",
  onChange,
  label = "输出格式",
  description,
}: OutputFormatSelectorProps) {
  const selectedOption = FORMAT_OPTIONS.find((opt) => opt.value === value) || FORMAT_OPTIONS[0];

  return (
    <div className="space-y-2">
      <Label htmlFor="outputFormat">{label}</Label>
      <Select
        value={value}
        onValueChange={(val) => onChange(val as OutputFormat)}
      >
        <SelectTrigger id="outputFormat">
          <SelectValue>
            <div className="flex flex-col items-start">
              <span>{selectedOption.label}</span>
              {selectedOption.description && (
                <span className="text-xs text-muted-foreground mt-0.5">
                  {selectedOption.description}
                </span>
              )}
            </div>
          </SelectValue>
        </SelectTrigger>
        <SelectContent>
          {FORMAT_OPTIONS.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              <div className="flex flex-col items-start">
                <span>{option.label}</span>
                <span className="text-xs text-muted-foreground mt-0.5">
                  {option.description}
                </span>
              </div>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {description && (
        <p className="text-xs text-muted-foreground">{description}</p>
      )}
    </div>
  );
}

