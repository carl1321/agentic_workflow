// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { useRef, useState, useCallback } from "react";
import { Node, Edge } from "@xyflow/react";
import { Button } from "~/components/ui/button";
import { Variable } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "~/components/ui/popover";
import { UpstreamNodeSelector } from "./UpstreamNodeSelector";

interface VariableInsertButtonProps {
  currentNodeId: string;
  nodes: Node[];
  edges: Edge[];
  textareaRef: React.RefObject<HTMLTextAreaElement>;
  value: string;
  onChange: (value: string) => void;
  className?: string;
}

export function VariableInsertButton({
  currentNodeId,
  nodes,
  edges,
  textareaRef,
  value,
  onChange,
  className,
}: VariableInsertButtonProps) {
  const [open, setOpen] = useState(false);

  const insertAtCursor = useCallback(
    (text: string) => {
      const textarea = textareaRef.current;
      if (!textarea) return;

      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      const currentValue = value;

      // 在光标位置插入文本
      const newValue =
        currentValue.substring(0, start) +
        text +
        currentValue.substring(end);

      onChange(newValue);

      // 设置新的光标位置（在插入文本之后）
      setTimeout(() => {
        const newCursorPos = start + text.length;
        textarea.setSelectionRange(newCursorPos, newCursorPos);
        textarea.focus();
      }, 0);
    },
    [textareaRef, value, onChange]
  );

  const handleSelect = useCallback(
    (template: string) => {
      insertAtCursor(template);
      setOpen(false);
    },
    [insertAtCursor]
  );

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className={className}
        >
          <Variable className="mr-2 h-4 w-4" />
          插入变量
        </Button>
      </PopoverTrigger>
      <PopoverContent
        className="w-auto p-0"
        align="start"
        side="bottom"
        sideOffset={4}
      >
        <UpstreamNodeSelector
          currentNodeId={currentNodeId}
          nodes={nodes}
          edges={edges}
          onSelect={handleSelect}
          onClose={() => setOpen(false)}
        />
      </PopoverContent>
    </Popover>
  );
}

