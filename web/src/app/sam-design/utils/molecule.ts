// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import type { Molecule, MolecularProperties } from "../types";

/**
 * 从模型执行的文本结果中解析SMILES字符串
 * 支持格式：
 * - "1. SMILES: xxx"
 * - "SMILES: xxx"
 * - "xxx" (纯SMILES字符串)
 */
export function parseSMILESFromText(text: string): string[] {
  if (!text || text.trim().length === 0) {
    return [];
  }

  const smilesList: string[] = [];
  
  // 匹配格式：1. SMILES: xxx 或 SMILES: xxx
  const numberedPattern = /\d+\.\s*SMILES:\s*`?([^`\n]+)`?/gi;
  const matches = text.matchAll(numberedPattern);
  
  for (const match of matches) {
    const smiles = match[1]?.trim();
    if (smiles && smiles.length > 0) {
      smilesList.push(smiles);
    }
  }

  // 如果没有找到编号格式，尝试匹配 "SMILES: xxx"
  if (smilesList.length === 0) {
    const simplePattern = /SMILES:\s*`?([^`\n]+)`?/gi;
    const simpleMatches = text.matchAll(simplePattern);
    for (const match of simpleMatches) {
      const smiles = match[1]?.trim();
      if (smiles && smiles.length > 0) {
        smilesList.push(smiles);
      }
    }
  }

  // 如果还是没有找到，尝试从行中提取可能的SMILES
  if (smilesList.length === 0) {
    const lines = text.split('\n');
    for (const line of lines) {
      const trimmed = line.trim();
      // 简单的SMILES验证：包含字母、数字、括号、等号等
      if (trimmed.length > 5 && /^[A-Za-z0-9=()\[\]+\-.,@#]+$/.test(trimmed)) {
        // 排除明显不是SMILES的行（如"成功生成"等）
        if (!trimmed.includes('成功') && !trimmed.includes('生成') && !trimmed.includes('骨架')) {
          smilesList.push(trimmed);
        }
      }
    }
  }

  return smilesList;
}

/**
 * 从工作流执行的node_outputs中提取分子数据
 */
export function extractMoleculesFromWorkflowResult(
  nodeOutputs: Record<string, any>
): Partial<Molecule>[] {
  // 新实现：工作流输出通常是结构化JSON（数组/对象），而不是包含“SMILES:”的纯文本。
  // 这里递归地从 workflow 的最终 outputs / node_outputs 中提取带 smiles 的对象/数组，
  // 并去重后返回给 Step3 做评估。
  const moleculeMap = new Map<string, Partial<Molecule>>();
  const imageUrlMap = new Map<string, string>(); // smiles -> imageUrl（如果输出里带了）

  const normalizeSmiles = (s: string) => s.trim();

  const tryCollectFromObject = (obj: any) => {
    if (!obj || typeof obj !== "object") return;

    // 常见字段：smiles / SMILES
    const rawSmiles = typeof obj.smiles === "string" ? obj.smiles : (typeof obj.SMILES === "string" ? obj.SMILES : null);
    if (rawSmiles) {
      const smiles = normalizeSmiles(rawSmiles);
      if (!moleculeMap.has(smiles)) {
        moleculeMap.set(smiles, { smiles });
      }
      // 可选：如果对象自带图像URL
      if (typeof obj.imageUrl === "string" && obj.imageUrl.includes("/molecular_images/")) {
        imageUrlMap.set(smiles, obj.imageUrl);
      }
      if (typeof obj.image_url === "string" && obj.image_url.includes("/molecular_images/")) {
        imageUrlMap.set(smiles, obj.image_url);
      }
      // 可选：如果对象带 properties
      if (obj.properties && typeof obj.properties === "object") {
        const existing = moleculeMap.get(smiles) || { smiles };
        existing.properties = { ...(existing.properties || {}), ...(obj.properties as MolecularProperties) };
        moleculeMap.set(smiles, existing);
      }
    }
  };

  const walk = (value: any) => {
    if (value === null || value === undefined) return;
    if (Array.isArray(value)) {
      for (const item of value) walk(item);
      return;
    }
    if (typeof value !== "object") return;

    // 先尝试从当前对象本身提取 smiles
    tryCollectFromObject(value);

    // 对 loop 节点输出做优先遍历：passed_items / pending_items / output
    if (Array.isArray((value as any).passed_items)) walk((value as any).passed_items);
    if (Array.isArray((value as any).pending_items)) walk((value as any).pending_items);
    if (Array.isArray((value as any).output)) walk((value as any).output);

    // 继续遍历所有子字段
    for (const v of Object.values(value)) {
      walk(v);
    }
  };

  // 从所有 nodeOutputs 递归提取
  for (const output of Object.values(nodeOutputs)) {
    // 常见结构：{ output: ... } / { outputs: ... } / { <nodeId>: {..} }
    walk(output);
  }

  // 如果没提取到结构化 smiles，尝试退化到文本解析（兼容老的工具输出）
  if (moleculeMap.size === 0) {
    for (const output of Object.values(nodeOutputs)) {
      const outputText = typeof output?.output === "string" ? output.output : JSON.stringify(output ?? "");
      const smilesList = parseSMILESFromText(outputText);
      for (const smiles of smilesList) {
        const key = normalizeSmiles(smiles);
        if (!moleculeMap.has(key)) {
          moleculeMap.set(key, { smiles: key });
        }
      }
    }
  }

  const molecules: Partial<Molecule>[] = Array.from(moleculeMap.values()).map((m, i) => ({
    index: i + 1,
    ...m,
  }));

  // 附加图片URL（如果有）
  for (const mol of molecules) {
    if (mol.smiles && imageUrlMap.has(mol.smiles)) {
      mol.imageUrl = imageUrlMap.get(mol.smiles);
    }
  }

  return molecules;
}

/**
 * 格式化评分显示
 */
export function formatScore(score: number): string {
  return score.toFixed(1);
}

/**
 * 获取评分颜色
 */
export function getScoreColor(score: number): string {
  if (score >= 80) return "text-green-600 dark:text-green-400";
  if (score >= 60) return "text-yellow-600 dark:text-yellow-400";
  return "text-red-600 dark:text-red-400";
}

