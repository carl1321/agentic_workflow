// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { useState, useEffect } from "react";
import { Button } from "~/components/ui/button";
import { Input } from "~/components/ui/input";
import { Label } from "~/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "~/components/ui/select";
import { Plus, Trash2, Info, Circle } from "lucide-react";

export type OutputFormatType = "json" | "array";
export type OutputFieldType = "String" | "Integer" | "Boolean";

export interface OutputField {
  name: string;
  type: OutputFieldType;
}

interface OutputSchemaEditorProps {
  format: OutputFormatType;
  fields: OutputField[];
  onFormatChange: (format: OutputFormatType) => void;
  onFieldsChange: (fields: OutputField[]) => void;
}

export function OutputSchemaEditor({
  format,
  fields,
  onFormatChange,
  onFieldsChange,
}: OutputSchemaEditorProps) {
  const [localFields, setLocalFields] = useState<OutputField[]>(fields);
  const [errors, setErrors] = useState<Record<number, string>>({});

  // 确保格式始终为 "array"
  useEffect(() => {
    if (format !== "array") {
      onFormatChange("array");
    }
  }, [format, onFormatChange]);

  useEffect(() => {
    setLocalFields(fields);
  }, [fields]);

  const addField = () => {
    const newField: OutputField = { name: "", type: "String" };
    const updated = [...localFields, newField];
    setLocalFields(updated);
    onFieldsChange(updated);
  };

  const removeField = (index: number) => {
    const updated = localFields.filter((_, i) => i !== index);
    setLocalFields(updated);
    setErrors((prev) => {
      const newErrors = { ...prev };
      delete newErrors[index];
      // 重新索引错误
      const reindexed: Record<number, string> = {};
      Object.keys(newErrors).forEach((key) => {
        const oldIndex = parseInt(key);
        if (oldIndex > index) {
          reindexed[oldIndex - 1] = newErrors[oldIndex];
        } else {
          reindexed[oldIndex] = newErrors[oldIndex];
        }
      });
      return reindexed;
    });
    onFieldsChange(updated);
  };

  const updateField = (index: number, field: Partial<OutputField>) => {
    const updated = localFields.map((f, i) => (i === index ? { ...f, ...field } : f));
    setLocalFields(updated);

    // 验证字段名
    if (field.name !== undefined) {
      if (!field.name.trim()) {
        setErrors((prev) => ({ ...prev, [index]: "变量名不可为空" }));
      } else {
        setErrors((prev) => {
          const newErrors = { ...prev };
          delete newErrors[index];
          return newErrors;
        });
      }
    }

    onFieldsChange(updated);
  };

  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <Label>输出</Label>
            <Info className="h-4 w-4 text-muted-foreground" />
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="default"
              size="icon"
              className="h-6 w-6 rounded-full"
              onClick={addField}
            >
              <Plus className="h-3 w-3" />
            </Button>
          </div>
        </div>

        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground font-medium">
            <div>变量名</div>
            <div>变量类型</div>
          </div>

          {/* 自定义字段 */}
          {localFields.map((field, index) => (
            <div key={index} className="grid grid-cols-2 gap-2 items-start">
              <div>
                <Input
                  value={field.name}
                  onChange={(e) => updateField(index, { name: e.target.value })}
                  placeholder="输入变量名"
                  className={errors[index] ? "border-red-500" : ""}
                />
                {errors[index] && (
                  <p className="text-xs text-red-500 mt-1">{errors[index]}</p>
                )}
              </div>
              <div className="flex items-center gap-2">
                <Select
                  value={field.type}
                  onValueChange={(val) => updateField(index, { type: val as OutputFieldType })}
                >
                  <SelectTrigger className="h-9">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="String">str. String</SelectItem>
                    <SelectItem value="Integer">int. Integer</SelectItem>
                    <SelectItem value="Boolean">bool. Boolean</SelectItem>
                  </SelectContent>
                </Select>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-9 w-9"
                  onClick={() => removeField(index)}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </div>
          ))}
        </div>

        <p className="text-xs text-muted-foreground mt-2">
          输出格式：JSON 对象数组 [{}]
        </p>
      </div>
    </div>
  );
}

