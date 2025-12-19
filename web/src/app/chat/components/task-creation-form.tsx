"use client";

import { useState, useEffect } from "react";
import { Save, Sparkles, Check, X } from "lucide-react";
import { Button } from "~/components/ui/button";
import { Stepper } from "./stepper";
import { RangeSlider } from "./range-slider";

interface TaskFormData {
  pump5FlowRate: number;
  controlMode: "residenceTime" | "reactionFlowRate";
  residenceTime: number;
  reactionFlowRate: number;
  reactionTemperature: number;
  backPressure: number;
  autoCleaning: {
    innerWall: boolean;
    outerWall: boolean;
  };
  collection: {
    startVolume: number;
    endVolume: number;
    dispenseCount: number;
    dispenseVolume: number;
  };
}

interface OptimizationResult {
  residenceTime?: number;
  reactionFlowRate?: number;
  reactionTemperature?: number;
  backPressure?: number;
  targetValue?: number;
  targetLabel?: string;
}

interface TaskCreationFormProps {
  onSave: (data: TaskFormData) => void;
  onCancel: () => void;
}

export function TaskCreationForm({ onSave, onCancel }: TaskCreationFormProps) {
  const [formData, setFormData] = useState<TaskFormData>({
    pump5FlowRate: 0.0,
    controlMode: "residenceTime",
    residenceTime: 30,
    reactionFlowRate: 1.0,
    reactionTemperature: 70.0,
    backPressure: 0.0,
    autoCleaning: {
      innerWall: true,
      outerWall: true,
    },
    collection: {
      startVolume: 2.0,
      endVolume: 8.0,
      dispenseCount: 1,
      dispenseVolume: 6.0,
    },
  });

  const [optimizationResults, setOptimizationResults] = useState<OptimizationResult | null>(null);
  const [isOptimizing, setIsOptimizing] = useState(false);
  const [optimizationMethod, setOptimizationMethod] = useState<"algorithm" | "model">("algorithm");
  const [selectedAlgorithm, setSelectedAlgorithm] = useState("genetic");
  const [selectedModel, setSelectedModel] = useState("gpt-4");
  const [optimizationTarget, setOptimizationTarget] = useState("maximize");
  const [appliedOptimizations, setAppliedOptimizations] = useState<Set<string>>(new Set());

  // 自动计算泵5流速
  useEffect(() => {
    if (formData.controlMode === "residenceTime") {
      // 根据停留时间和反应流速计算
      const calculated = (formData.collection.endVolume - formData.collection.startVolume) / formData.residenceTime;
      setFormData((prev) => ({ ...prev, pump5FlowRate: calculated }));
    } else {
      // 根据反应流速计算
      setFormData((prev) => ({ ...prev, pump5FlowRate: formData.reactionFlowRate }));
    }
  }, [formData.controlMode, formData.residenceTime, formData.reactionFlowRate, formData.collection.startVolume, formData.collection.endVolume]);

  const handleOptimize = async () => {
    setIsOptimizing(true);
    // 模拟优化过程
    setTimeout(() => {
      const results: OptimizationResult = {
        residenceTime: formData.residenceTime + (Math.random() * 10 - 5),
        reactionFlowRate: formData.reactionFlowRate + (Math.random() * 0.5 - 0.25),
        reactionTemperature: formData.reactionTemperature + (Math.random() * 5 - 2.5),
        backPressure: formData.backPressure + (Math.random() * 2 - 1),
        targetValue: 85.5 + Math.random() * 10,
        targetLabel: "预期效率",
      };
      setOptimizationResults(results);
      setIsOptimizing(false);
      setAppliedOptimizations(new Set());
    }, 2000);
  };

  const applyOptimization = (field: keyof OptimizationResult) => {
    if (!optimizationResults || !optimizationResults[field]) return;

    const value = optimizationResults[field] as number;
    if (field === "residenceTime") {
      setFormData((prev) => ({ ...prev, residenceTime: Math.max(15, Math.min(600, value)) }));
    } else if (field === "reactionFlowRate") {
      setFormData((prev) => ({ ...prev, reactionFlowRate: Math.max(0.1, value) }));
    } else if (field === "reactionTemperature") {
      setFormData((prev) => ({ ...prev, reactionTemperature: Math.max(40, Math.min(100, value)) }));
    } else if (field === "backPressure") {
      setFormData((prev) => ({ ...prev, backPressure: Math.max(0, value) }));
    }

    setAppliedOptimizations((prev) => new Set(prev).add(field));
  };

  const applyAllOptimizations = () => {
    if (!optimizationResults) return;
    Object.keys(optimizationResults).forEach((key) => {
      if (key !== "targetValue" && key !== "targetLabel") {
        applyOptimization(key as keyof OptimizationResult);
      }
    });
  };

  const ignoreAllOptimizations = () => {
    setOptimizationResults(null);
    setAppliedOptimizations(new Set());
  };

  const handleSubmit = () => {
    onSave(formData);
  };

  return (
    <div className="w-full max-w-6xl mx-auto p-6 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50">
      <h2 className="text-2xl font-bold mb-6 text-slate-900 dark:text-white">新建实验</h2>

      <div className="space-y-6">
        {/* 参数优化区域 - 移到顶部 */}
        <div className="bg-slate-50 dark:bg-slate-800/50 rounded-lg border border-slate-200 dark:border-slate-700 p-6 space-y-4">
          <h3 className="text-lg font-semibold text-slate-900 dark:text-white flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-blue-500" />
            参数优化
          </h3>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                优化方法
              </label>
              <div className="flex gap-4">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="optimizationMethod"
                    value="algorithm"
                    checked={optimizationMethod === "algorithm"}
                    onChange={(e) => setOptimizationMethod(e.target.value as "algorithm" | "model")}
                    className="w-4 h-4 text-blue-600"
                  />
                  <span className="text-sm text-slate-700 dark:text-slate-300">算法</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="optimizationMethod"
                    value="model"
                    checked={optimizationMethod === "model"}
                    onChange={(e) => setOptimizationMethod(e.target.value as "algorithm" | "model")}
                    className="w-4 h-4 text-blue-600"
                  />
                  <span className="text-sm text-slate-700 dark:text-slate-300">模型</span>
                </label>
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                {optimizationMethod === "algorithm" ? "选择算法" : "选择模型"}
              </label>
              <select
                value={optimizationMethod === "algorithm" ? selectedAlgorithm : selectedModel}
                onChange={(e) =>
                  optimizationMethod === "algorithm"
                    ? setSelectedAlgorithm(e.target.value)
                    : setSelectedModel(e.target.value)
                }
                className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {optimizationMethod === "algorithm" ? (
                  <>
                    <option value="genetic">遗传算法</option>
                    <option value="pso">粒子群优化</option>
                    <option value="bayesian">贝叶斯优化</option>
                    <option value="gradient">梯度下降</option>
                  </>
                ) : (
                  <>
                    <option value="gpt-4">GPT-4</option>
                    <option value="claude">Claude</option>
                    <option value="llama">LLaMA</option>
                    <option value="internlm">InternLM</option>
                  </>
                )}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                优化目标
              </label>
              <select
                value={optimizationTarget}
                onChange={(e) => setOptimizationTarget(e.target.value)}
                className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="maximize">最大化效率</option>
                <option value="minimize">最小化成本</option>
                <option value="maximizeYield">最大化产量</option>
              </select>
            </div>

            <div className="flex items-end">
              <Button
                onClick={handleOptimize}
                disabled={isOptimizing}
                className="w-full bg-blue-500 hover:bg-blue-600 dark:bg-blue-600 dark:hover:bg-blue-500 text-white"
              >
                <Sparkles className="h-4 w-4 mr-2" />
                {isOptimizing ? "优化中..." : "开始优化"}
              </Button>
            </div>
          </div>

          {/* 优化结果展示 */}
          {optimizationResults && (
            <div className="mt-4 p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-800">
              <div className="flex items-center justify-between mb-3">
                <div>
                  <span className="text-sm font-medium text-blue-700 dark:text-blue-300">
                    {optimizationResults.targetLabel}:{" "}
                  </span>
                  <span className="text-lg font-bold text-blue-600 dark:text-blue-400">
                    {optimizationResults.targetValue?.toFixed(2)}%
                  </span>
                </div>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={applyAllOptimizations}
                    className="h-7 px-3 text-xs"
                  >
                    全部应用
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={ignoreAllOptimizations}
                    className="h-7 px-3 text-xs"
                  >
                    <X className="h-3 w-3 mr-1" />
                    全部忽略
                  </Button>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* 实验参数 - 改为网格布局 */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* 左列：反应区参数 */}
          <div className="space-y-4">
            <h3 className="text-lg font-semibold text-slate-900 dark:text-white">反应区</h3>
            
            {/* 控制模式选择 */}
            <div>
              <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                控制模式
              </label>
              <div className="flex gap-4">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="controlMode"
                    value="residenceTime"
                    checked={formData.controlMode === "residenceTime"}
                    onChange={(e) =>
                      setFormData((prev) => ({ ...prev, controlMode: e.target.value as "residenceTime" | "reactionFlowRate" }))
                    }
                    className="w-4 h-4 text-blue-600"
                  />
                  <span className="text-sm text-slate-700 dark:text-slate-300">停留时间</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="controlMode"
                    value="reactionFlowRate"
                    checked={formData.controlMode === "reactionFlowRate"}
                    onChange={(e) =>
                      setFormData((prev) => ({ ...prev, controlMode: e.target.value as "residenceTime" | "reactionFlowRate" }))
                    }
                    className="w-4 h-4 text-blue-600"
                  />
                  <span className="text-sm text-slate-700 dark:text-slate-300">反应流速</span>
                </label>
              </div>
            </div>

            {/* 停留时间 */}
            {formData.controlMode === "residenceTime" && (
              <div>
                <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                  停留时间(15min-600min)
                </label>
                <Stepper
                  value={formData.residenceTime}
                  onChange={(value) => setFormData((prev) => ({ ...prev, residenceTime: value }))}
                  min={15}
                  max={600}
                  step={1}
                  precision={0}
                />
                {optimizationResults?.residenceTime !== undefined && (
                  <div className="mt-2 p-2 bg-blue-50 dark:bg-blue-900/20 rounded border border-blue-200 dark:border-blue-800">
                    <div className="flex items-center justify-between">
                      <div>
                        <span className="text-xs text-blue-600 dark:text-blue-400">优化建议: </span>
                        <span className="text-sm font-medium text-blue-700 dark:text-blue-300">
                          {optimizationResults.residenceTime.toFixed(0)} min
                        </span>
                      </div>
                      {appliedOptimizations.has("residenceTime") ? (
                        <span className="text-xs text-green-600 dark:text-green-400">已应用</span>
                      ) : (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => applyOptimization("residenceTime")}
                          className="h-6 px-2 text-xs"
                        >
                          <Check className="h-3 w-3 mr-1" />
                          应用
                        </Button>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* 反应流速 */}
            <div>
              <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                反应流速(mL/min)
              </label>
              <input
                type="number"
                value={formData.reactionFlowRate.toFixed(3)}
                onChange={(e) =>
                  setFormData((prev) => ({ ...prev, reactionFlowRate: parseFloat(e.target.value) || 0 }))
                }
                step="0.001"
                className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              {optimizationResults?.reactionFlowRate !== undefined && (
                <div className="mt-2 p-2 bg-blue-50 dark:bg-blue-900/20 rounded border border-blue-200 dark:border-blue-800">
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="text-xs text-blue-600 dark:text-blue-400">优化建议: </span>
                      <span className="text-sm font-medium text-blue-700 dark:text-blue-300">
                        {optimizationResults.reactionFlowRate.toFixed(3)} mL/min
                      </span>
                    </div>
                    {appliedOptimizations.has("reactionFlowRate") ? (
                      <span className="text-xs text-green-600 dark:text-green-400">已应用</span>
                    ) : (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => applyOptimization("reactionFlowRate")}
                        className="h-6 px-2 text-xs"
                      >
                        <Check className="h-3 w-3 mr-1" />
                        应用
                      </Button>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* 右列：反应区参数（续）和其他参数 */}
          <div className="space-y-4">
            <h3 className="text-lg font-semibold text-slate-900 dark:text-white opacity-0">反应区</h3>
            
            {/* 反应温度 */}
            <div>
              <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                反应温度(40℃-100°C)
              </label>
              <Stepper
                value={formData.reactionTemperature}
                onChange={(value) => setFormData((prev) => ({ ...prev, reactionTemperature: value }))}
                min={40}
                max={100}
                step={0.1}
                precision={2}
              />
              {optimizationResults?.reactionTemperature !== undefined && (
                <div className="mt-2 p-2 bg-blue-50 dark:bg-blue-900/20 rounded border border-blue-200 dark:border-blue-800">
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="text-xs text-blue-600 dark:text-blue-400">优化建议: </span>
                      <span className="text-sm font-medium text-blue-700 dark:text-blue-300">
                        {optimizationResults.reactionTemperature.toFixed(2)} °C
                      </span>
                    </div>
                    {appliedOptimizations.has("reactionTemperature") ? (
                      <span className="text-xs text-green-600 dark:text-green-400">已应用</span>
                    ) : (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => applyOptimization("reactionTemperature")}
                        className="h-6 px-2 text-xs"
                      >
                        <Check className="h-3 w-3 mr-1" />
                        应用
                      </Button>
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* 背压压力 */}
            <div>
              <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                背压压力(bar)
              </label>
              <Stepper
                value={formData.backPressure}
                onChange={(value) => setFormData((prev) => ({ ...prev, backPressure: value }))}
                min={0}
                max={10}
                step={0.01}
                precision={2}
              />
              {optimizationResults?.backPressure !== undefined && (
                <div className="mt-2 p-2 bg-blue-50 dark:bg-blue-900/20 rounded border border-blue-200 dark:border-blue-800">
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="text-xs text-blue-600 dark:text-blue-400">优化建议: </span>
                      <span className="text-sm font-medium text-blue-700 dark:text-blue-300">
                        {optimizationResults.backPressure.toFixed(2)} bar
                      </span>
                    </div>
                    {appliedOptimizations.has("backPressure") ? (
                      <span className="text-xs text-green-600 dark:text-green-400">已应用</span>
                    ) : (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => applyOptimization("backPressure")}
                        className="h-6 px-2 text-xs"
                      >
                        <Check className="h-3 w-3 mr-1" />
                        应用
                      </Button>
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* 泵5流速 */}
            <div>
              <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                泵5流速 (mL/min)(自动计算)
              </label>
              <input
                type="number"
                value={formData.pump5FlowRate.toFixed(3)}
                readOnly
                className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-400 cursor-not-allowed"
              />
            </div>
          </div>
        </div>

        {/* 自动清洗和收集参数 - 2列网格 */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* 自动清洗 */}
          <div className="space-y-4">
            <h3 className="text-lg font-semibold text-slate-900 dark:text-white">自动清洗</h3>
            <div className="flex gap-6">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={formData.autoCleaning.innerWall}
                  onChange={(e) =>
                    setFormData((prev) => ({
                      ...prev,
                      autoCleaning: { ...prev.autoCleaning, innerWall: e.target.checked },
                    }))
                  }
                  className="w-4 h-4 text-blue-600 rounded"
                />
                <span className="text-sm text-slate-700 dark:text-slate-300">内壁</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={formData.autoCleaning.outerWall}
                  onChange={(e) =>
                    setFormData((prev) => ({
                      ...prev,
                      autoCleaning: { ...prev.autoCleaning, outerWall: e.target.checked },
                    }))
                  }
                  className="w-4 h-4 text-blue-600 rounded"
                />
                <span className="text-sm text-slate-700 dark:text-slate-300">外壁</span>
              </label>
            </div>
          </div>

          {/* 收集参数 */}
          <div className="space-y-4">
            <h3 className="text-lg font-semibold text-slate-900 dark:text-white">收集</h3>

            {/* 收集起止体积 */}
            <div>
              <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                收集起止体积(mL)
              </label>
              <RangeSlider
                min={0}
                max={10}
                value={[formData.collection.startVolume, formData.collection.endVolume]}
                onChange={(value) =>
                  setFormData((prev) => ({
                    ...prev,
                    collection: { ...prev.collection, startVolume: value[0], endVolume: value[1] },
                  }))
                }
                step={0.1}
              />
            </div>

            {/* 是否分装 */}
            <div>
              <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                *是否分装
              </label>
              <select
                value={formData.collection.dispenseCount}
                onChange={(e) =>
                  setFormData((prev) => ({
                    ...prev,
                    collection: { ...prev.collection, dispenseCount: parseInt(e.target.value) },
                  }))
                }
                className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value={1}>1瓶</option>
                <option value={2}>2瓶</option>
                <option value={3}>3瓶</option>
                <option value={4}>4瓶</option>
                <option value={5}>5瓶</option>
              </select>
            </div>

            {/* 分装体积 */}
            <div>
              <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                #1(mL)
              </label>
              <Stepper
                value={formData.collection.dispenseVolume}
                onChange={(value) =>
                  setFormData((prev) => ({
                    ...prev,
                    collection: { ...prev.collection, dispenseVolume: value },
                  }))
                }
                min={0}
                max={10}
                step={0.001}
                precision={3}
              />
            </div>
          </div>
        </div>


        {/* 操作按钮 */}
        <div className="flex justify-end gap-3 pt-4 border-t border-slate-200 dark:border-slate-700">
          <Button variant="outline" onClick={onCancel}>
            取消
          </Button>
          <Button
            onClick={handleSubmit}
            className="bg-blue-500 hover:bg-blue-600 dark:bg-blue-600 dark:hover:bg-blue-500 text-white"
          >
            <Save className="h-4 w-4 mr-2" />
            保存
          </Button>
        </div>
      </div>
    </div>
  );
}

