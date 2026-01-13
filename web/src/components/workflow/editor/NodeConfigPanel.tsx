// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { useState, useEffect, useRef } from "react";
import { X, Plus, Trash2, CheckCircle2, XCircle, Loader2, Clock, Circle } from "lucide-react";
import { Node, Edge } from "@xyflow/react";
import { Button } from "~/components/ui/button";
import { Input } from "~/components/ui/input";
import { Label } from "~/components/ui/label";
import { Textarea } from "~/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "~/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "~/components/ui/tabs";
import { Badge } from "~/components/ui/badge";
import { ScrollArea } from "~/components/ui/scroll-area";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "~/components/ui/accordion";
import { ToolSelector } from "./components/ToolSelector";
import { KnowledgeSelector } from "./components/KnowledgeSelector";
import { VariableInsertButton } from "./components/VariableInsertButton";
import { ModelSelector } from "./components/ModelSelector";
import { LoopBodyNodeSelector } from "./components/LoopBodyNodeSelector";
import { OutputSchemaEditor, type OutputFormatType, type OutputField } from "./components/OutputSchemaEditor";

interface NodeConfigPanelProps {
  node: Node;
  nodes: Node[];
  edges: Edge[];
  onUpdate: (nodeId: string, data: any) => void;
  onClose: () => void;
}

// 格式化 JSON 用于显示，去除字符串中的换行符，以标准 JSON 格式展开显示
function formatJSONForDisplay(obj: any): string {
  if (obj === null || obj === undefined) {
    return "null";
  }
  
  // 递归处理对象和数组，去除字符串中的换行符和转义字符
  const processValue = (value: any): any => {
    if (typeof value === "string") {
      // 去除字符串中的换行符（包括 \n 和实际的换行符），替换为空格
      return value
        .replace(/\\n/g, " ")  // 将 \n 转义字符替换为空格
        .replace(/\n/g, " ")    // 将实际换行符替换为空格
        .replace(/\\t/g, " ")   // 将 \t 替换为空格
        .replace(/\t/g, " ")     // 将实际制表符替换为空格
        .replace(/\\r/g, " ")   // 将 \r 替换为空格
        .replace(/\r/g, " ")     // 将实际回车符替换为空格
        .replace(/\\"/g, '"')   // 保留转义的引号
        .replace(/\\\\/g, "\\") // 保留转义的反斜杠
        .replace(/\s+/g, " ")    // 将多个连续空格合并为单个空格
        .trim();                // 去除首尾空格
    } else if (Array.isArray(value)) {
      return value.map(processValue);
    } else if (typeof value === "object" && value !== null) {
      const processed: any = {};
      for (const key in value) {
        if (value.hasOwnProperty(key)) {
          processed[key] = processValue(value[key]);
        }
      }
      return processed;
    }
    return value;
  };
  
  try {
    // 先处理字符串中的换行符，然后格式化为标准 JSON
    const processed = processValue(obj);
    return JSON.stringify(processed, null, 2);
  } catch (e) {
    // 如果处理失败，返回标准格式化的 JSON
    return JSON.stringify(obj, null, 2);
  }
}

// 渲染对象字段，直接展开显示内部字段（不显示 input/output 字段名）
function renderObjectFields(obj: any, label: string) {
  if (!obj || typeof obj !== 'object') {
    return null;
  }
  
  // 如果是数组，直接显示
  if (Array.isArray(obj)) {
    return (
      <div className="space-y-1">
        <Label className="text-xs text-muted-foreground">{label}</Label>
        <div className="bg-muted rounded-md p-2 overflow-auto max-h-[200px]">
          <pre className="text-xs font-mono whitespace-pre-wrap">{formatJSONForDisplay(obj)}</pre>
        </div>
      </div>
    );
  }
  
  // 如果是对象，展开显示每个字段
  return (
    <div className="space-y-1">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      <div className="bg-muted rounded-md p-2 space-y-2">
        {Object.entries(obj).map(([key, value]) => (
          <div key={key} className="border-b border-border/50 pb-2 last:border-0 last:pb-0">
            <div className="text-xs font-semibold text-foreground mb-1">{key}</div>
            <div className="text-xs text-muted-foreground">
              {typeof value === 'object' && value !== null ? (
                <pre className="whitespace-pre-wrap">{formatJSONForDisplay(value)}</pre>
              ) : (
                String(value)
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function RunResultTab({ nodeData }: { nodeData: any }) {
  const result = nodeData.executionResult;
  const status = nodeData.executionStatus || "pending";
  const nodeType = nodeData.type || nodeData.nodeType;
  const isLoopNode = nodeType === "loop";
  const isLoopBodyNode = nodeData.loopId || nodeData.loop_id;
  
  if (!result && status === "pending") {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted-foreground p-8">
        <p>暂无运行结果</p>
        <p className="text-xs mt-2">点击"执行"查看结果</p>
      </div>
    );
  }

  const duration = result?.startTime && result?.endTime 
    ? ((new Date(result.endTime).getTime() - new Date(result.startTime).getTime()) / 1000).toFixed(2) + "s"
    : null;

  // 循环体节点：显示 iterations, passed_items, pending_items
  if (isLoopNode) {
    const outputs = result?.outputs || {};
    const iterations = outputs.iterations || 0;
    const passedItems = outputs.passed_items || [];
    const pendingItems = outputs.pending_items || [];
    
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
              {status === "success" && <Badge variant="default" className="bg-green-500 hover:bg-green-600"><CheckCircle2 className="w-3 h-3 mr-1"/> 成功</Badge>}
              {status === "error" && <Badge variant="destructive"><XCircle className="w-3 h-3 mr-1"/> 失败</Badge>}
              {status === "running" && <Badge variant="secondary" className="bg-blue-100 text-blue-800"><Loader2 className="w-3 h-3 mr-1 animate-spin"/> 运行中</Badge>}
              {status === "ready" && <Badge variant="secondary" className="bg-blue-100 text-blue-800 animate-pulse">就绪</Badge>}
              {status === "skipped" && <Badge variant="outline">已跳过</Badge>}
              {status === "cancelled" && <Badge variant="outline">已取消</Badge>}
              {status === "pending" && <Badge variant="outline">未运行</Badge>}
          </div>
          {duration && (
            <div className="flex items-center text-xs text-muted-foreground">
              <Clock className="w-3 h-3 mr-1" />
              {duration}
            </div>
          )}
        </div>

        {result?.error && (
          <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-md p-3">
            <p className="text-sm font-medium text-red-800 dark:text-red-300">错误信息</p>
            <pre className="mt-1 text-xs text-red-600 dark:text-red-400 whitespace-pre-wrap overflow-auto max-h-[100px]">{typeof result.error === 'string' ? result.error : JSON.stringify(result.error, null, 2)}</pre>
          </div>
        )}

        {/* 显示重试信息 */}
        {result?.attempt && result.attempt > 1 && (
          <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-md p-3">
            <p className="text-sm font-medium text-yellow-800 dark:text-yellow-300">重试信息</p>
            <p className="mt-1 text-xs text-yellow-600 dark:text-yellow-400">
              当前重试次数: {result.attempt} / 4
            </p>
            {result.retry_delay_seconds && result.retry_delay_seconds > 0 && (
              <p className="mt-1 text-xs text-yellow-600 dark:text-yellow-400">
                下次重试延迟: {result.retry_delay_seconds}秒
              </p>
            )}
          </div>
        )}

        {/* 显示超时信息 */}
        {result?.timeout_seconds && (
          <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-md p-3">
            <p className="text-sm font-medium text-blue-800 dark:text-blue-300">超时配置</p>
            <p className="mt-1 text-xs text-blue-600 dark:text-blue-400">
              超时时间: {result.timeout_seconds}秒
            </p>
          </div>
        )}

        {/* 迭代次数 */}
        <div className="space-y-2">
          <Label className="text-xs text-muted-foreground">迭代次数</Label>
          <div className="bg-muted rounded-md p-2">
            <p className="text-sm font-medium">{iterations}</p>
          </div>
        </div>

        {/* 通过筛选的数据 */}
        <div className="space-y-2">
          <Label className="text-xs text-muted-foreground">通过筛选的数据 (passed_items)</Label>
          <div className="bg-muted rounded-md p-2 overflow-auto max-h-[300px]">
            <pre className="text-xs font-mono whitespace-pre-wrap">{formatJSONForDisplay(passedItems)}</pre>
          </div>
        </div>

        {/* 不满足条件的条目 */}
        <div className="space-y-2">
          <Label className="text-xs text-muted-foreground">不满足条件的条目 (pending_items)</Label>
          <div className="bg-muted rounded-md p-2 overflow-auto max-h-[300px]">
            <pre className="text-xs font-mono whitespace-pre-wrap">{formatJSONForDisplay(pendingItems)}</pre>
          </div>
        </div>
      </div>
    );
  }

  // 循环体内的节点：按迭代次数分组展示
  if (isLoopBodyNode && result?.outputs?.iteration_outputs && Array.isArray(result.outputs.iteration_outputs) && result.outputs.iteration_outputs.length > 0) {
    const iterationOutputs = result.outputs.iteration_outputs;
    
    // 按迭代次数分组
    const groupedByIteration: Record<number, typeof iterationOutputs> = {};
    iterationOutputs.forEach((item: any) => {
      const iter = item.iteration || 0;
      if (!groupedByIteration[iter]) {
        groupedByIteration[iter] = [];
      }
      groupedByIteration[iter].push(item);
    });
    
    const iterations = Object.keys(groupedByIteration).map(Number).sort((a, b) => a - b);
    
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
              {status === "success" && <Badge variant="default" className="bg-green-500 hover:bg-green-600"><CheckCircle2 className="w-3 h-3 mr-1"/> 成功</Badge>}
              {status === "error" && <Badge variant="destructive"><XCircle className="w-3 h-3 mr-1"/> 失败</Badge>}
              {status === "running" && <Badge variant="secondary" className="bg-blue-100 text-blue-800"><Loader2 className="w-3 h-3 mr-1 animate-spin"/> 运行中</Badge>}
              {status === "ready" && <Badge variant="secondary" className="bg-blue-100 text-blue-800 animate-pulse">就绪</Badge>}
              {status === "skipped" && <Badge variant="outline">已跳过</Badge>}
              {status === "cancelled" && <Badge variant="outline">已取消</Badge>}
              {status === "pending" && <Badge variant="outline">未运行</Badge>}
          </div>
          {duration && (
            <div className="flex items-center text-xs text-muted-foreground">
              <Clock className="w-3 h-3 mr-1" />
              {duration}
            </div>
          )}
        </div>

        {result?.error && (
          <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-md p-3">
            <p className="text-sm font-medium text-red-800 dark:text-red-300">错误信息</p>
            <pre className="mt-1 text-xs text-red-600 dark:text-red-400 whitespace-pre-wrap overflow-auto max-h-[100px]">{typeof result.error === 'string' ? result.error : JSON.stringify(result.error, null, 2)}</pre>
          </div>
        )}

        <div className="space-y-2">
          <Label className="text-xs text-muted-foreground">迭代执行结果</Label>
          <Accordion type="multiple" className="w-full">
            {iterations.map((iter) => {
              const items = groupedByIteration[iter];
              if (!items || items.length === 0) return null;
              
              // 取最后一次执行的结果（同一迭代可能执行多次）
              const lastItem = items[items.length - 1];
              
              return (
                <AccordionItem key={iter} value={`iteration-${iter}`}>
                  <AccordionTrigger className="text-sm">
                    迭代 {iter}
                    {lastItem.duration && (
                      <span className="ml-2 text-xs text-muted-foreground">
                        ({lastItem.duration.toFixed(2)}s)
                      </span>
                    )}
                  </AccordionTrigger>
                  <AccordionContent>
                    <div className="space-y-3 pt-2">
                      {/* 输入：优先使用 resolved_inputs，如果没有则使用 inputs */}
                      {(lastItem.resolved_inputs || lastItem.inputs) && (
                        renderObjectFields(
                          lastItem.resolved_inputs || lastItem.inputs,
                          "输入"
                        )
                      )}
                      
                      {/* 输出：直接显示内部字段 */}
                      {lastItem.output && (() => {
                        const output = lastItem.output;
                        
                        // 检查是否是评估节点的数组输出
                        // 评估节点输出通常是数组，每个元素包含 score、opt_des 等字段
                        const isEvaluationArray = Array.isArray(output) && 
                          output.length > 0 && 
                          output.every(item => 
                            typeof item === 'object' && 
                            item !== null && 
                            ('score' in item || 'opt_des' in item || 'name' in item || 'smiles' in item)
                          );
                        
                        if (isEvaluationArray) {
                          // 数组格式：直接显示整个数组，不展开字段
                          return (
                            <div className="space-y-2">
                              <Label className="text-xs text-muted-foreground">输出</Label>
                              <div className="bg-muted rounded-md p-2 overflow-auto max-h-[300px]">
                                <pre className="text-xs font-mono whitespace-pre-wrap">
                                  {formatJSONForDisplay(output)}
                                </pre>
                              </div>
                            </div>
                          );
                        }
                        
                        // 其他情况：使用原有的 renderObjectFields
                        return renderObjectFields(output, "输出");
                      })()}
                      
                      {lastItem.metrics && Object.keys(lastItem.metrics).length > 0 && (
                        <div className="grid grid-cols-2 gap-2">
                          {Object.entries(lastItem.metrics).map(([key, value]) => {
                            if (typeof value === 'object') return null;
                            return (
                              <div key={key} className="bg-muted rounded p-2">
                                <p className="text-[10px] text-muted-foreground uppercase">{key}</p>
                                <p className="text-sm font-medium">{String(value)}</p>
                              </div>
                            );
                          })}
                        </div>
                      )}
                      
                      {lastItem.error && (
                        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-md p-2">
                          <p className="text-xs text-red-600 dark:text-red-400">{lastItem.error}</p>
                        </div>
                      )}
                    </div>
                  </AccordionContent>
                </AccordionItem>
              );
            })}
          </Accordion>
        </div>
      </div>
    );
  }

  // 普通节点：显示标准结果
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
            {status === "success" && <Badge variant="default" className="bg-green-500 hover:bg-green-600"><CheckCircle2 className="w-3 h-3 mr-1"/> 成功</Badge>}
            {status === "error" && <Badge variant="destructive"><XCircle className="w-3 h-3 mr-1"/> 失败</Badge>}
            {status === "running" && <Badge variant="secondary" className="bg-blue-100 text-blue-800"><Loader2 className="w-3 h-3 mr-1 animate-spin"/> 运行中</Badge>}
            {status === "ready" && <Badge variant="secondary" className="bg-blue-100 text-blue-800 animate-pulse">就绪</Badge>}
            {status === "skipped" && <Badge variant="outline">已跳过</Badge>}
            {status === "cancelled" && <Badge variant="outline">已取消</Badge>}
            {status === "pending" && <Badge variant="outline">未运行</Badge>}
        </div>
        {duration && (
            <div className="flex items-center text-xs text-muted-foreground">
                <Clock className="w-3 h-3 mr-1" />
                {duration}
            </div>
        )}
      </div>

      {result?.error && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-md p-3">
          <p className="text-sm font-medium text-red-800 dark:text-red-300">错误信息</p>
          <pre className="mt-1 text-xs text-red-600 dark:text-red-400 whitespace-pre-wrap overflow-auto max-h-[100px]">{typeof result.error === 'string' ? result.error : JSON.stringify(result.error, null, 2)}</pre>
        </div>
      )}

      {result?.metrics && Object.keys(result.metrics).length > 0 && (
        <div className="grid grid-cols-2 gap-2">
            {Object.entries(result.metrics).map(([key, value]) => {
                if (typeof value === 'object') return null;
                return (
                    <div key={key} className="bg-muted rounded p-2">
                        <p className="text-[10px] text-muted-foreground uppercase">{key}</p>
                        <p className="text-sm font-medium">{String(value)}</p>
                    </div>
                );
            })}
        </div>
      )}

      {result?.inputs && (
        <div className="space-y-2">
          <Label className="text-xs text-muted-foreground">输入参数</Label>
          <div className="bg-muted rounded-md p-2 overflow-auto max-h-[200px]">
            <pre className="text-xs font-mono whitespace-pre-wrap">{formatJSONForDisplay(result.inputs)}</pre>
          </div>
        </div>
      )}

      {result?.outputs && (
        <div className="space-y-2">
          <Label className="text-xs text-muted-foreground">输出结果</Label>
          <div className="bg-muted rounded-md p-2 overflow-auto max-h-[300px]">
             <pre className="text-xs font-mono whitespace-pre-wrap">{formatJSONForDisplay(result.outputs)}</pre>
          </div>
        </div>
      )}
    </div>
  );
}

export function NodeConfigPanel({ node, nodes, edges, onUpdate, onClose }: NodeConfigPanelProps) {
  const nodeData = node.data || {};
  const [displayName, setDisplayName] = useState(nodeData.displayName || nodeData.label || "");
  
  // 节点名称（不可编辑）
  // 确保 taskName 始终是字符串
  const taskName = typeof nodeData.taskName === 'string' 
    ? nodeData.taskName 
    : (typeof nodeData.nodeName === 'string' ? nodeData.nodeName : (typeof nodeData.label === 'string' ? nodeData.label : String(node.type || 'node')));
  
  // 开始和结束节点固定名称
  const isFixedName = node.type === "start" || node.type === "end";

  useEffect(() => {
    setDisplayName(nodeData.displayName || nodeData.label || "");
  }, [node.id, nodeData.displayName, nodeData.label]);

  const handleDisplayNameChange = (value: string) => {
    setDisplayName(value);
    onUpdate(node.id, { ...nodeData, displayName: value });
  };

  // 根据节点类型显示不同的配置选项
  const renderNodeSpecificConfig = () => {
    switch (node.type) {
      case "start":
        return (
          <StartNodeConfig 
            node={node} 
            nodeData={nodeData} 
            onUpdate={onUpdate} 
          />
        );
      case "llm":
        return (
          <LLMNodeConfig 
            node={node} 
            nodeData={nodeData} 
            nodes={nodes}
            edges={edges}
            onUpdate={onUpdate} 
          />
        );
      case "tool":
        return (
          <ToolNodeConfig 
            node={node} 
            nodeData={nodeData} 
            nodes={nodes}
            edges={edges}
            onUpdate={onUpdate} 
          />
        );
      case "condition":
        return (
          <ConditionNodeConfig 
            node={node} 
            nodeData={nodeData} 
            nodes={nodes}
            edges={edges}
            onUpdate={onUpdate} 
          />
        );
      case "loop":
        return (
          <LoopNodeConfig 
            node={node} 
            nodeData={nodeData} 
            nodes={nodes}
            edges={edges}
            onUpdate={onUpdate} 
          />
        );
      default:
        return <div className="text-sm text-muted-foreground">此节点类型暂无额外配置</div>;
    }
  };

  return (
    <div className="h-full w-full flex flex-col border-l border-border bg-card shadow-lg">
      <div className="flex h-16 items-center justify-between border-b border-border px-4">
        <h2 className="text-lg font-semibold text-foreground">节点配置</h2>
        <Button variant="ghost" size="icon" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>
      
      {node.type === "start" || node.type === "end" ? (
        // 开始和结束节点不显示运行结果页签
        <div className="flex-1 overflow-y-auto p-4">
          <div className="space-y-4">
            <div>
              <Label htmlFor="taskName">节点名称</Label>
              <Input
                id="taskName"
                value={taskName}
                disabled
                className="bg-muted"
              />
              <p className="mt-1 text-xs text-muted-foreground">
                节点名称用于程序运行和记录，不可更改
              </p>
            </div>
            <div>
              <Label htmlFor="displayName">显示名称</Label>
              <Input
                id="displayName"
                value={displayName}
                onChange={(e) => handleDisplayNameChange(e.target.value)}
                placeholder="输入显示名称"
                disabled={isFixedName}
                className={isFixedName ? "bg-muted" : ""}
              />
              {isFixedName && (
                <p className="mt-1 text-xs text-muted-foreground">
                  开始和结束节点的显示名称不可更改
                </p>
              )}
              {!isFixedName && (
                <p className="mt-1 text-xs text-muted-foreground">
                  显示名称用于界面展示，可以自定义
                </p>
              )}
            </div>
            {renderNodeSpecificConfig()}
          </div>
        </div>
      ) : (
        <Tabs defaultValue="config" className="flex-1 flex flex-col overflow-hidden">
          <div className="px-4 pt-2">
            <TabsList className="w-full grid grid-cols-2">
              <TabsTrigger value="config">配置</TabsTrigger>
              <TabsTrigger value="result">运行结果</TabsTrigger>
            </TabsList>
          </div>
          
          <TabsContent value="config" className="flex-1 overflow-y-auto p-4 data-[state=inactive]:hidden mt-0">
            <div className="space-y-4">
              <div>
                <Label htmlFor="taskName">节点名称</Label>
                <Input
                  id="taskName"
                  value={taskName}
                  disabled
                  className="bg-muted"
                />
                <p className="mt-1 text-xs text-muted-foreground">
                  节点名称用于程序运行和记录，不可更改
                </p>
              </div>
              <div>
                <Label htmlFor="displayName">显示名称</Label>
                <Input
                  id="displayName"
                  value={displayName}
                  onChange={(e) => handleDisplayNameChange(e.target.value)}
                  placeholder="输入显示名称"
                  disabled={isFixedName}
                  className={isFixedName ? "bg-muted" : ""}
                />
                {isFixedName && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    开始和结束节点的显示名称不可更改
                  </p>
                )}
                {!isFixedName && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    显示名称用于界面展示，可以自定义
                  </p>
                )}
              </div>
              {renderNodeSpecificConfig()}
            </div>
          </TabsContent>
          
          <TabsContent value="result" className="flex-1 overflow-y-auto p-4 data-[state=inactive]:hidden mt-0">
            <RunResultTab nodeData={nodeData} />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}

interface NodeConfigProps {
  node: Node;
  nodeData: any;
  nodes?: Node[];
  edges?: Edge[];
  onUpdate: (nodeId: string, data: any) => void;
}

function StartNodeConfig({ node, nodeData, onUpdate }: NodeConfigProps) {
  const [inputInfo, setInputInfo] = useState(nodeData.startInputInfo || "");

  return (
    <div className="space-y-4">
      <div>
        <Label htmlFor="inputInfo">输入信息</Label>
        <Input
          id="inputInfo"
          value={inputInfo}
          onChange={(e) => {
            setInputInfo(e.target.value);
            onUpdate(node.id, { ...nodeData, startInputInfo: e.target.value || undefined });
          }}
          placeholder="输入信息描述（可选）"
        />
        <p className="mt-1 text-xs text-muted-foreground">
          工作流开始时的输入信息描述，用于提示用户输入内容
        </p>
      </div>
    </div>
  );
}

function LLMNodeConfig({ node, nodeData, nodes = [], edges = [], onUpdate }: NodeConfigProps) {
  const [model, setModel] = useState(nodeData.llmModel || "");
  const [temperature, setTemperature] = useState(nodeData.llmTemperature?.toString() || "0.7");
  const [prompt, setPrompt] = useState(nodeData.llmPrompt || "");
  const [systemPrompt, setSystemPrompt] = useState(nodeData.llmSystemPrompt || "");
  const [outputFormat, setOutputFormat] = useState<OutputFormatType>(
    (nodeData.outputFormat || nodeData.output_format || "array") as OutputFormatType
  );
  const [outputFields, setOutputFields] = useState<OutputField[]>(
    nodeData.outputFields || nodeData.output_fields || []
  );
  const promptRef = useRef<HTMLTextAreaElement>(null);
  const systemPromptRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setModel(nodeData.llmModel || "");
  }, [nodeData.llmModel]);

  useEffect(() => {
    setTemperature(nodeData.llmTemperature?.toString() || "0.7");
  }, [nodeData.llmTemperature]);

  useEffect(() => {
    setPrompt(nodeData.llmPrompt || "");
  }, [nodeData.llmPrompt]);

  useEffect(() => {
    setSystemPrompt(nodeData.llmSystemPrompt || "");
  }, [nodeData.llmSystemPrompt]);

  useEffect(() => {
    setOutputFormat((nodeData.outputFormat || nodeData.output_format || "array") as OutputFormatType);
    setOutputFields(nodeData.outputFields || nodeData.output_fields || []);
  }, [nodeData.outputFormat, nodeData.output_format, nodeData.outputFields, nodeData.output_fields]);

  return (
    <div className="space-y-4">
      <div>
        <Label htmlFor="model">模型</Label>
        <ModelSelector
          value={model}
          onChange={(modelName) => {
            setModel(modelName);
            onUpdate(node.id, { ...nodeData, llmModel: modelName });
          }}
        />
        <p className="mt-1 text-xs text-muted-foreground">
          选择要使用的大语言模型
        </p>
      </div>
      
      <div>
        <Label htmlFor="temperature">温度</Label>
        <Input
          id="temperature"
          type="number"
          min="0"
          max="2"
          step="0.1"
          value={temperature}
          onChange={(e) => {
            setTemperature(e.target.value);
            const temp = parseFloat(e.target.value);
            if (!isNaN(temp)) {
              onUpdate(node.id, { ...nodeData, llmTemperature: temp });
            }
          }}
        />
      </div>
      
      <div>
        <Label htmlFor="timeoutSeconds">超时时间（秒）</Label>
        <Input
          id="timeoutSeconds"
          type="number"
          min="1"
          step="1"
          value={nodeData.timeoutSeconds || nodeData.timeout_seconds || 300}
          onChange={(e) => {
            const timeout = parseInt(e.target.value);
            if (!isNaN(timeout) && timeout > 0) {
              onUpdate(node.id, { ...nodeData, timeoutSeconds: timeout });
            }
          }}
          placeholder="默认：300（5分钟）"
        />
        <p className="text-xs text-muted-foreground mt-1">
          节点执行超时时间。对于循环体内的节点，每次迭代都会独立检测超时。
          循环体节点本身不参与超时检测，其他节点最多重试4次。
        </p>
      </div>
      
      <div>
        <div className="flex items-center justify-between mb-2">
          <Label htmlFor="prompt">提示词</Label>
          <VariableInsertButton
            currentNodeId={node.id}
            nodes={nodes}
            edges={edges}
            textareaRef={promptRef}
            value={prompt}
            onChange={(value) => {
              setPrompt(value);
              onUpdate(node.id, { ...nodeData, llmPrompt: value });
            }}
          />
        </div>
        <Textarea
          ref={promptRef}
          id="prompt"
          value={prompt}
          onChange={(e) => {
            setPrompt(e.target.value);
            onUpdate(node.id, { ...nodeData, llmPrompt: e.target.value });
          }}
          placeholder="输入提示词，可使用 {'{'}{'{'}节点名.字段名{'}'}{'}'} 引用上游节点输出"
          rows={4}
        />
        <p className="mt-1 text-xs text-muted-foreground">
          提示：点击"插入变量"按钮选择上游节点的输出字段
        </p>
      </div>
      
      <div>
        <div className="flex items-center justify-between mb-2">
          <Label htmlFor="systemPrompt">系统提示词</Label>
          <VariableInsertButton
            currentNodeId={node.id}
            nodes={nodes}
            edges={edges}
            textareaRef={systemPromptRef}
            value={systemPrompt}
            onChange={(value) => {
              setSystemPrompt(value);
              onUpdate(node.id, { ...nodeData, llmSystemPrompt: value || undefined });
            }}
          />
        </div>
        <Textarea
          ref={systemPromptRef}
          id="systemPrompt"
          value={systemPrompt}
          onChange={(e) => {
            setSystemPrompt(e.target.value);
            onUpdate(node.id, { ...nodeData, llmSystemPrompt: e.target.value || undefined });
          }}
          placeholder="输入系统提示词（可选），可使用 {'{'}{'{'}节点名.字段名{'}'}{'}'} 引用上游节点输出"
          rows={3}
        />
      </div>
      
      <div>
        <Label>知识库</Label>
        <KnowledgeSelector
          value={nodeData.llmResources || []}
          onChange={(resources) => {
            onUpdate(node.id, { ...nodeData, llmResources: resources });
          }}
        />
      </div>
      
      <div>
        <Label>工具选择</Label>
        <ToolSelector
          value={nodeData.llmTools || []}
          onChange={(tools) => {
            onUpdate(node.id, { ...nodeData, llmTools: tools });
          }}
        />
      </div>
      
      <div>
        <OutputSchemaEditor
          format={outputFormat}
          fields={outputFields}
          onFormatChange={(format) => {
            setOutputFormat(format);
            onUpdate(node.id, { ...nodeData, outputFormat: format, output_format: format });
          }}
          onFieldsChange={(fields) => {
            setOutputFields(fields);
            onUpdate(node.id, { ...nodeData, outputFields: fields, output_fields: fields });
          }}
        />
      </div>
    </div>
  );
}

function ToolNodeConfig({ node, nodeData, nodes = [], edges = [], onUpdate }: NodeConfigProps) {
  const [toolName, setToolName] = useState(nodeData.toolName || "");
  const [toolParams, setToolParams] = useState(
    JSON.stringify(nodeData.toolParams || {}, null, 2)
  );
  const [outputFormat, setOutputFormat] = useState<OutputFormatType>(
    (nodeData.outputFormat || nodeData.output_format || "array") as OutputFormatType
  );
  const [outputFields, setOutputFields] = useState<OutputField[]>(
    nodeData.outputFields || nodeData.output_fields || []
  );
  const toolParamsRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setOutputFormat((nodeData.outputFormat || nodeData.output_format || "array") as OutputFormatType);
    setOutputFields(nodeData.outputFields || nodeData.output_fields || []);
  }, [nodeData.outputFormat, nodeData.output_format, nodeData.outputFields, nodeData.output_fields]);

  return (
    <div className="space-y-4">
      <div>
        <Label htmlFor="toolName">工具名称</Label>
        <Input
          id="toolName"
          value={toolName}
          onChange={(e) => {
            setToolName(e.target.value);
            onUpdate(node.id, { ...nodeData, toolName: e.target.value });
          }}
          placeholder="输入工具名称"
        />
      </div>
      
      <div>
        <Label htmlFor="timeoutSeconds">超时时间（秒）</Label>
        <Input
          id="timeoutSeconds"
          type="number"
          min="1"
          step="1"
          value={nodeData.timeoutSeconds || nodeData.timeout_seconds || 120}
          onChange={(e) => {
            const timeout = parseInt(e.target.value);
            if (!isNaN(timeout) && timeout > 0) {
              onUpdate(node.id, { ...nodeData, timeoutSeconds: timeout });
            }
          }}
          placeholder="默认：120（2分钟）"
        />
        <p className="text-xs text-muted-foreground mt-1">
          节点执行超时时间。对于循环体内的节点，每次迭代都会独立检测超时。
          循环体节点本身不参与超时检测，其他节点最多重试4次。
        </p>
      </div>
      <div>
        <div className="flex items-center justify-between mb-2">
          <Label htmlFor="toolParams">工具参数</Label>
          <VariableInsertButton
            currentNodeId={node.id}
            nodes={nodes}
            edges={edges}
            textareaRef={toolParamsRef}
            value={toolParams}
            onChange={(value) => {
              setToolParams(value);
              try {
                const params = JSON.parse(value);
                onUpdate(node.id, { ...nodeData, toolParams: params });
              } catch {
                // Invalid JSON, ignore
              }
            }}
          />
        </div>
        <Textarea
          ref={toolParamsRef}
          id="toolParams"
          value={toolParams}
          onChange={(e) => {
            setToolParams(e.target.value);
            try {
              const params = JSON.parse(e.target.value);
              onUpdate(node.id, { ...nodeData, toolParams: params });
            } catch {
              // Invalid JSON, ignore
            }
          }}
          placeholder='{"key": "value"}'
          rows={4}
        />
        <p className="mt-1 text-xs text-muted-foreground">
          提示：可在 JSON 字符串值中使用 {'{'}{'{'}节点名.字段名{'}'}{'}'} 引用上游节点输出
        </p>
      </div>
      
      <div>
        <OutputSchemaEditor
          format={outputFormat}
          fields={outputFields}
          onFormatChange={(format) => {
            setOutputFormat(format);
            onUpdate(node.id, { ...nodeData, outputFormat: format, output_format: format });
          }}
          onFieldsChange={(fields) => {
            setOutputFields(fields);
            onUpdate(node.id, { ...nodeData, outputFields: fields, output_fields: fields });
          }}
        />
      </div>
    </div>
  );
}

function ConditionNodeConfig({ node, nodeData, nodes = [], edges = [], onUpdate }: NodeConfigProps) {
  const [expression, setExpression] = useState(nodeData.conditionExpression || "");
  const [outputFormat, setOutputFormat] = useState<OutputFormatType>(
    (nodeData.outputFormat || nodeData.output_format || "array") as OutputFormatType
  );
  const [outputFields, setOutputFields] = useState<OutputField[]>(
    nodeData.outputFields || nodeData.output_fields || []
  );
  const expressionRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setOutputFormat((nodeData.outputFormat || nodeData.output_format || "array") as OutputFormatType);
    setOutputFields(nodeData.outputFields || nodeData.output_fields || []);
  }, [nodeData.outputFormat, nodeData.output_format, nodeData.outputFields, nodeData.output_fields]);

  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-center justify-between mb-2">
          <Label htmlFor="expression">条件表达式</Label>
          <VariableInsertButton
            currentNodeId={node.id}
            nodes={nodes}
            edges={edges}
            textareaRef={expressionRef}
            value={expression}
            onChange={(value) => {
              setExpression(value);
              onUpdate(node.id, { ...nodeData, conditionExpression: value });
            }}
          />
        </div>
        <Textarea
          ref={expressionRef}
          id="expression"
          value={expression}
          onChange={(e) => {
            setExpression(e.target.value);
            onUpdate(node.id, { ...nodeData, conditionExpression: e.target.value });
          }}
          placeholder="输入条件表达式，例如: {'{'}{'{'}节点名.字段名{'}'}{'}'} > 80"
          rows={3}
        />
        <p className="mt-1 text-xs text-muted-foreground">
          提示：使用 {'{'}{'{'}节点名.字段名{'}'}{'}'} 引用上游节点的输出字段
        </p>
      </div>
      
      <div>
        <Label htmlFor="timeoutSeconds">超时时间（秒）</Label>
        <Input
          id="timeoutSeconds"
          type="number"
          min="1"
          step="1"
          value={nodeData.timeoutSeconds || nodeData.timeout_seconds || 30}
          onChange={(e) => {
            const timeout = parseInt(e.target.value);
            if (!isNaN(timeout) && timeout > 0) {
              onUpdate(node.id, { ...nodeData, timeoutSeconds: timeout });
            }
          }}
          placeholder="默认：30秒"
        />
        <p className="text-xs text-muted-foreground mt-1">
          节点执行超时时间。对于循环体内的节点，每次迭代都会独立检测超时。
          循环体节点本身不参与超时检测，其他节点最多重试4次。
        </p>
      </div>
      
      <div>
        <OutputSchemaEditor
          format={outputFormat}
          fields={outputFields}
          onFormatChange={(format) => {
            setOutputFormat(format);
            onUpdate(node.id, { ...nodeData, outputFormat: format, output_format: format });
          }}
          onFieldsChange={(fields) => {
            setOutputFields(fields);
            onUpdate(node.id, { ...nodeData, outputFields: fields, output_fields: fields });
          }}
        />
      </div>
    </div>
  );
}

function LoopNodeConfig({ node, nodeData, nodes = [], edges = [], onUpdate }: NodeConfigProps) {
  const [loopCount, setLoopCount] = useState(
    nodeData.loopCount?.toString() || nodeData.loop_count?.toString() || "3"
  );
  const [breakConditions, setBreakConditions] = useState(
    nodeData.breakConditions || nodeData.break_conditions || []
  );
  const [logicalOperator, setLogicalOperator] = useState(
    nodeData.logicalOperator || nodeData.logical_operator || "and"
  );
  const [outputFormat, setOutputFormat] = useState<OutputFormatType>(
    (nodeData.outputFormat || nodeData.output_format || "array") as OutputFormatType
  );
  const [outputFields, setOutputFields] = useState<OutputField[]>(
    nodeData.outputFields || nodeData.output_fields || []
  );
  const [pendingItemsVariableName, setPendingItemsVariableName] = useState(
    nodeData.pendingItemsVariableName || nodeData.pending_items_variable_name || "pending_items"
  );
  const [showLoopBodySelector, setShowLoopBodySelector] = useState<number | null>(null); // 显示选择器的条件索引

  useEffect(() => {
    setOutputFormat((nodeData.outputFormat || nodeData.output_format || "array") as OutputFormatType);
    setOutputFields(nodeData.outputFields || nodeData.output_fields || []);
  }, [nodeData.outputFormat, nodeData.output_format, nodeData.outputFields, nodeData.output_fields]);

  const addBreakCondition = () => {
    const newCondition = {
      outputVariable: "",
      operator: ">=",
      value: "",
    };
    setBreakConditions([...breakConditions, newCondition]);
    onUpdate(node.id, {
      ...nodeData,
      breakConditions: [...breakConditions, newCondition],
    });
  };

  const removeBreakCondition = (index: number) => {
    const newConditions = breakConditions.filter((_, i) => i !== index);
    setBreakConditions(newConditions);
    onUpdate(node.id, { ...nodeData, breakConditions: newConditions });
  };

  const updateBreakCondition = (index: number, field: string, value: any) => {
    const newConditions = [...breakConditions];
    newConditions[index] = { ...newConditions[index], [field]: value };
    setBreakConditions(newConditions);
    onUpdate(node.id, { ...nodeData, breakConditions: newConditions });
  };

  return (
    <div className="space-y-4">
      <div>
        <Label htmlFor="loopCount">最大循环次数</Label>
        <Input
          id="loopCount"
          type="number"
          min="1"
          value={loopCount}
          onChange={(e) => {
            setLoopCount(e.target.value);
            const count = parseInt(e.target.value);
            if (!isNaN(count) && count >= 1) {
              onUpdate(node.id, { ...nodeData, loopCount: count, loop_count: count });
            } else if (e.target.value === "") {
              onUpdate(node.id, { ...nodeData, loopCount: undefined, loop_count: undefined });
            }
          }}
          placeholder="留空表示无限制"
        />
        <p className="mt-1 text-xs text-muted-foreground">
          设置循环的最大执行次数，留空表示无限制（需配置退出条件）
        </p>
      </div>

      <div>
        <Label htmlFor="pendingItemsVariableName">待优化数据变量名</Label>
        <Input
          id="pendingItemsVariableName"
          value={pendingItemsVariableName}
          onChange={(e) => {
            setPendingItemsVariableName(e.target.value);
            onUpdate(node.id, {
              ...nodeData,
              pendingItemsVariableName: e.target.value,
              pending_items_variable_name: e.target.value,
            });
          }}
          placeholder="pending_items"
        />
        <p className="mt-1 text-xs text-muted-foreground">
          用于在循环体内访问待优化数据的变量名，可在LLM节点的Prompt中使用 {'{'}{'{'}loop.variables.{pendingItemsVariableName}{'}'}{'}'} 引用
        </p>
      </div>

      <div>
        <div className="flex items-center justify-between mb-2">
          <Label>退出条件</Label>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={addBreakCondition}
          >
            <Plus className="h-4 w-4 mr-1" />
            添加条件
          </Button>
        </div>
        {breakConditions.length === 0 ? (
          <p className="text-sm text-muted-foreground py-2">
            暂无退出条件，将根据最大循环次数退出
          </p>
        ) : (
          <div className="space-y-2">
            {breakConditions.map((condition: any, index: number) => (
              <div key={index} className="border rounded-md p-3 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium">条件 {index + 1}</span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => removeBreakCondition(index)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
                <div className="grid grid-cols-12 gap-2 items-end">
                  <div className="col-span-6">
                    <Label className="text-xs">输出变量</Label>
                    <div className="flex gap-1 items-center">
                      <Input
                        value={condition.outputVariable || ""}
                        onChange={(e) =>
                          updateBreakCondition(index, "outputVariable", e.target.value)
                        }
                        placeholder="如：LLM6.output.score"
                        className="h-8 flex-1"
                      />
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6 p-0"
                        onClick={() => setShowLoopBodySelector(index)}
                        title="选择循环体内节点变量"
                      >
                        <Circle className="h-3 w-3 text-muted-foreground" />
                      </Button>
                    </div>
                  </div>
                  <div className="col-span-3">
                    <Label className="text-xs">运算符</Label>
                    <Select
                      value={condition.operator || ">="}
                      onValueChange={(value) =>
                        updateBreakCondition(index, "operator", value)
                      }
                    >
                      <SelectTrigger className="h-8 text-xs">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value=">=">≥</SelectItem>
                        <SelectItem value="<=">≤</SelectItem>
                        <SelectItem value=">">&gt;</SelectItem>
                        <SelectItem value="<">&lt;</SelectItem>
                        <SelectItem value="==">=</SelectItem>
                        <SelectItem value="!=">≠</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="col-span-3">
                    <Label className="text-xs">比较值</Label>
                    <Input
                      value={condition.value || ""}
                      onChange={(e) =>
                        updateBreakCondition(index, "value", e.target.value)
                      }
                      placeholder="值"
                      className="h-8 text-xs"
                    />
                  </div>
                </div>
              </div>
            ))}
            {breakConditions.length > 1 && (
              <div>
                <Label className="text-xs">逻辑运算符</Label>
                <Select
                  value={logicalOperator}
                  onValueChange={(value) => {
                    setLogicalOperator(value);
                    onUpdate(node.id, { ...nodeData, logicalOperator: value, logical_operator: value });
                  }}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="and">AND（所有条件都满足）</SelectItem>
                    <SelectItem value="or">OR（任一条件满足）</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>
        )}
      </div>
      
      <div>
        <OutputSchemaEditor
          format={outputFormat}
          fields={outputFields}
          onFormatChange={(format) => {
            setOutputFormat(format);
            onUpdate(node.id, { ...nodeData, outputFormat: format, output_format: format });
          }}
          onFieldsChange={(fields) => {
            setOutputFields(fields);
            onUpdate(node.id, { ...nodeData, outputFields: fields, output_fields: fields });
          }}
        />
      </div>
      
      {/* 循环体内节点选择器对话框 */}
      {showLoopBodySelector !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-card border border-border rounded-lg shadow-lg">
            <LoopBodyNodeSelector
              loopNodeId={node.id}
              nodes={nodes}
              onSelect={(variablePath) => {
                // 移除 {{ 和 }}，只保留变量路径
                const cleanPath = variablePath.replace(/^\{\{|\}\}$/g, "");
                updateBreakCondition(showLoopBodySelector, "outputVariable", cleanPath);
                setShowLoopBodySelector(null);
              }}
              onClose={() => setShowLoopBodySelector(null)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
