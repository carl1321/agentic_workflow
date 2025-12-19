"use client";

import { useState, useEffect, useRef } from "react";
import { Search, Download, FileText, TrendingUp, BarChart3 } from "lucide-react";
import { Button } from "~/components/ui/button";

interface Experiment {
  id: string;
  name: string;
  taskId: string;
  date: string;
  status: "completed" | "failed";
  parameters: {
    temperature: number[];
    pressure: number[];
    flowRate: number[];
    time: string[];
  };
}

const mockExperiments: Experiment[] = [
  {
    id: "EXP001",
    name: "聚合物复合实验",
    taskId: "#T20231001",
    date: "2023-10-22",
    status: "completed",
    parameters: {
      temperature: [65, 70, 78, 82, 80, 77, 75, 74],
      pressure: [1.2, 1.3, 1.5, 1.6, 1.5, 1.4, 1.3, 1.2],
      flowRate: [1.0, 1.1, 1.2, 1.3, 1.2, 1.1, 1.0, 0.9],
      time: ["8:00", "9:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00"],
    },
  },
  {
    id: "EXP002",
    name: "电池材料充放电",
    taskId: "#T20231003",
    date: "2023-10-23",
    status: "completed",
    parameters: {
      temperature: [25, 28, 32, 35, 33, 30, 28, 26],
      pressure: [0.8, 0.9, 1.0, 1.1, 1.0, 0.9, 0.8, 0.7],
      flowRate: [0.5, 0.6, 0.7, 0.8, 0.7, 0.6, 0.5, 0.4],
      time: ["10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00"],
    },
  },
  {
    id: "EXP003",
    name: "薄膜涂层测试",
    taskId: "#T20231004",
    date: "2023-10-20",
    status: "completed",
    parameters: {
      temperature: [50, 55, 60, 65, 63, 60, 58, 55],
      pressure: [2.0, 2.2, 2.5, 2.8, 2.6, 2.4, 2.2, 2.0],
      flowRate: [1.5, 1.6, 1.7, 1.8, 1.7, 1.6, 1.5, 1.4],
      time: ["8:00", "9:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00"],
    },
  },
];

export function ExperimentResultAnalysis() {
  const [experiments, setExperiments] = useState<Experiment[]>(mockExperiments);
  const [filteredExperiments, setFilteredExperiments] = useState<Experiment[]>(mockExperiments);
  const [selectedExperiment, setSelectedExperiment] = useState<Experiment | null>(mockExperiments[0]);
  const [filters, setFilters] = useState({
    name: "",
    dateFrom: "",
    dateTo: "",
    status: "",
  });

  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<any>(null);
  const correlationChartRef = useRef<HTMLDivElement>(null);
  const correlationChartInstance = useRef<any>(null);

  // 应用筛选
  useEffect(() => {
    let filtered = [...experiments];

    if (filters.name) {
      filtered = filtered.filter((exp) =>
        exp.name.toLowerCase().includes(filters.name.toLowerCase()) ||
        exp.taskId.toLowerCase().includes(filters.name.toLowerCase())
      );
    }
    if (filters.dateFrom) {
      filtered = filtered.filter((exp) => exp.date >= filters.dateFrom);
    }
    if (filters.dateTo) {
      filtered = filtered.filter((exp) => exp.date <= filters.dateTo);
    }
    if (filters.status) {
      filtered = filtered.filter((exp) => exp.status === filters.status);
    }

    setFilteredExperiments(filtered);
    if (selectedExperiment && !filtered.find((e) => e.id === selectedExperiment.id)) {
      setSelectedExperiment(filtered.length > 0 ? filtered[0] : null);
    }
  }, [filters, experiments, selectedExperiment]);

  // 初始化图表
  useEffect(() => {
    let echarts: any;
    let mounted = true;

    import("echarts").then((module) => {
      if (!mounted) return;
      echarts = module.default || module;

      if (chartRef.current && !chartInstance.current) {
        chartInstance.current = echarts.init(chartRef.current);
      }
      if (correlationChartRef.current && !correlationChartInstance.current) {
        correlationChartInstance.current = echarts.init(correlationChartRef.current);
      }
      updateCharts();
    });

    const handleResize = () => {
      chartInstance.current?.resize();
      correlationChartInstance.current?.resize();
    };

    window.addEventListener("resize", handleResize);

    return () => {
      mounted = false;
      window.removeEventListener("resize", handleResize);
      chartInstance.current?.dispose();
      correlationChartInstance.current?.dispose();
    };
  }, []);

  // 更新图表
  useEffect(() => {
    if (selectedExperiment) {
      updateCharts();
    }
  }, [selectedExperiment]);

  const updateCharts = () => {
    if (!selectedExperiment || !chartInstance.current) return;

    const isDark =
      window.matchMedia("(prefers-color-scheme: dark)").matches ||
      document.documentElement.classList.contains("dark");

    // 时间序列图表
    chartInstance.current.setOption({
      grid: { top: 20, right: 20, bottom: 40, left: 60 },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "cross" },
      },
      legend: {
        data: ["温度(℃)", "压力(bar)", "流速(mL/min)"],
        top: 10,
        textStyle: { color: isDark ? "#94a3b8" : "#64748b" },
      },
      xAxis: {
        type: "category",
        data: selectedExperiment.parameters.time,
        axisLabel: { color: isDark ? "#94a3b8" : "#64748b", fontSize: 11 },
      },
      yAxis: [
        {
          type: "value",
          name: "温度(℃)",
          position: "left",
          axisLabel: { color: isDark ? "#94a3b8" : "#64748b" },
          nameTextStyle: { color: isDark ? "#94a3b8" : "#64748b" },
        },
        {
          type: "value",
          name: "压力/流速",
          position: "right",
          axisLabel: { color: isDark ? "#94a3b8" : "#64748b" },
          nameTextStyle: { color: isDark ? "#94a3b8" : "#64748b" },
        },
      ],
      series: [
        {
          name: "温度(℃)",
          type: "line",
          data: selectedExperiment.parameters.temperature,
          smooth: true,
          lineStyle: { width: 2, color: "#3b82f6" },
          itemStyle: { color: "#3b82f6" },
        },
        {
          name: "压力(bar)",
          type: "line",
          yAxisIndex: 1,
          data: selectedExperiment.parameters.pressure,
          smooth: true,
          lineStyle: { width: 2, color: "#10b981" },
          itemStyle: { color: "#10b981" },
        },
        {
          name: "流速(mL/min)",
          type: "line",
          yAxisIndex: 1,
          data: selectedExperiment.parameters.flowRate,
          smooth: true,
          lineStyle: { width: 2, color: "#f59e0b" },
          itemStyle: { color: "#f59e0b" },
        },
      ],
    });

    // 相关性分析图表
    if (correlationChartInstance.current) {
      const temp = selectedExperiment.parameters.temperature;
      const pressure = selectedExperiment.parameters.pressure;
      const flowRate = selectedExperiment.parameters.flowRate;

      correlationChartInstance.current.setOption({
        grid: { top: 20, right: 20, bottom: 40, left: 60 },
        tooltip: {
          trigger: "item",
        },
        xAxis: {
          type: "category",
          data: ["温度-压力", "温度-流速", "压力-流速"],
          axisLabel: { color: isDark ? "#94a3b8" : "#64748b", fontSize: 11 },
        },
        yAxis: {
          type: "value",
          name: "相关系数",
          min: -1,
          max: 1,
          axisLabel: { color: isDark ? "#94a3b8" : "#64748b" },
          nameTextStyle: { color: isDark ? "#94a3b8" : "#64748b" },
        },
        series: [
          {
            type: "bar",
            data: [
              calculateCorrelation(temp, pressure),
              calculateCorrelation(temp, flowRate),
              calculateCorrelation(pressure, flowRate),
            ],
            itemStyle: {
              color: (params: any) => {
                const value = params.value;
                if (value > 0.7) return "#10b981";
                if (value > 0.3) return "#f59e0b";
                return "#ef4444";
              },
            },
          },
        ],
      });
    }
  };

  const calculateCorrelation = (x: number[], y: number[]): number => {
    const n = Math.min(x.length, y.length);
    const xMean = x.slice(0, n).reduce((a, b) => a + b, 0) / n;
    const yMean = y.slice(0, n).reduce((a, b) => a + b, 0) / n;

    let numerator = 0;
    let xSumSq = 0;
    let ySumSq = 0;

    for (let i = 0; i < n; i++) {
      const xDiff = x[i] - xMean;
      const yDiff = y[i] - yMean;
      numerator += xDiff * yDiff;
      xSumSq += xDiff * xDiff;
      ySumSq += yDiff * yDiff;
    }

    const denominator = Math.sqrt(xSumSq * ySumSq);
    return denominator === 0 ? 0 : numerator / denominator;
  };

  const calculateStatistics = (data: number[]) => {
    const sorted = [...data].sort((a, b) => a - b);
    const mean = data.reduce((a, b) => a + b, 0) / data.length;
    const variance = data.reduce((sum, val) => sum + Math.pow(val - mean, 2), 0) / data.length;
    const stdDev = Math.sqrt(variance);
    const median = sorted.length % 2 === 0
      ? (sorted[sorted.length / 2 - 1] + sorted[sorted.length / 2]) / 2
      : sorted[Math.floor(sorted.length / 2)];

    return {
      mean: mean.toFixed(2),
      median: median.toFixed(2),
      stdDev: stdDev.toFixed(2),
      min: Math.min(...data).toFixed(2),
      max: Math.max(...data).toFixed(2),
    };
  };

  const handleGenerateReport = () => {
    // TODO: 实现报告生成功能
    alert("报告生成功能开发中...");
  };

  const handleExportData = () => {
    // TODO: 实现数据导出功能
    alert("数据导出功能开发中...");
  };

  const handleFilterChange = (key: string, value: string) => {
    setFilters({ ...filters, [key]: value });
  };

  return (
    <div className="w-full h-full bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 overflow-y-auto">
      <div className="max-w-7xl mx-auto p-4 md:p-8">
        {/* 页面标题 */}
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl md:text-3xl font-bold text-slate-900 dark:text-white">
            实验结果分析
          </h1>
          <div className="flex gap-2">
            <Button variant="outline" onClick={handleExportData}>
              <Download className="h-4 w-4 mr-2" />
              导出数据
            </Button>
            <Button
              onClick={handleGenerateReport}
              className="bg-blue-500 hover:bg-blue-600 dark:bg-blue-600 dark:hover:bg-blue-500 text-white"
            >
              <FileText className="h-4 w-4 mr-2" />
              生成报告
            </Button>
          </div>
        </div>

        {/* 筛选面板 */}
        <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 shadow-sm p-4 mb-4">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                实验名称/任务ID
              </label>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
                <input
                  type="text"
                  value={filters.name}
                  onChange={(e) => handleFilterChange("name", e.target.value)}
                  placeholder="请输入实验名称或任务ID"
                  className="w-full pl-10 pr-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                开始日期
              </label>
              <input
                type="date"
                value={filters.dateFrom}
                onChange={(e) => handleFilterChange("dateFrom", e.target.value)}
                className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                结束日期
              </label>
              <input
                type="date"
                value={filters.dateTo}
                onChange={(e) => handleFilterChange("dateTo", e.target.value)}
                className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                状态
              </label>
              <select
                value={filters.status}
                onChange={(e) => handleFilterChange("status", e.target.value)}
                className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">全部状态</option>
                <option value="completed">已完成</option>
                <option value="failed">失败</option>
              </select>
            </div>
          </div>
        </div>

        {/* 实验列表和分析结果 */}
        <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 shadow-sm overflow-hidden">
          <div className="flex h-[calc(100vh-300px)] min-h-[600px]">
            {/* 实验列表 */}
            <div className="w-1/3 border-r border-slate-200 dark:border-slate-700 overflow-y-auto">
              <div className="p-4 bg-slate-50 dark:bg-slate-900/50 border-b border-slate-200 dark:border-slate-700">
                <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-300">实验列表</h2>
              </div>
              <div className="divide-y divide-slate-200 dark:divide-slate-700">
                {filteredExperiments.map((experiment) => (
                  <div
                    key={experiment.id}
                    onClick={() => setSelectedExperiment(experiment)}
                    className={`p-4 cursor-pointer transition-colors ${
                      selectedExperiment?.id === experiment.id
                        ? "bg-blue-50 dark:bg-blue-950/30"
                        : "hover:bg-slate-50 dark:hover:bg-slate-700/30"
                    }`}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm font-medium text-slate-900 dark:text-slate-50">
                        {experiment.name}
                      </span>
                      <span
                        className={`text-xs px-2 py-1 rounded-full ${
                          experiment.status === "completed"
                            ? "bg-green-100 dark:bg-green-900/50 text-green-600 dark:text-green-400"
                            : "bg-red-100 dark:bg-red-900/50 text-red-600 dark:text-red-400"
                        }`}
                      >
                        {experiment.status === "completed" ? "已完成" : "失败"}
                      </span>
                    </div>
                    <div className="text-xs text-slate-500 dark:text-slate-400">
                      {experiment.taskId} · {experiment.date}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* 分析结果展示区域 */}
            <div className="w-2/3 overflow-y-auto p-6 bg-slate-50 dark:bg-slate-900/50">
              {selectedExperiment ? (
                <div className="space-y-6">
                  {/* 实验基本信息 */}
                  <div>
                    <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-4">
                      {selectedExperiment.name}
                    </h2>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                      <div>
                        <div className="text-slate-500 dark:text-slate-400">任务ID</div>
                        <div className="text-slate-900 dark:text-slate-50 font-medium">
                          {selectedExperiment.taskId}
                        </div>
                      </div>
                      <div>
                        <div className="text-slate-500 dark:text-slate-400">实验日期</div>
                        <div className="text-slate-900 dark:text-slate-50 font-medium">
                          {selectedExperiment.date}
                        </div>
                      </div>
                      <div>
                        <div className="text-slate-500 dark:text-slate-400">状态</div>
                        <div
                          className={`font-medium ${
                            selectedExperiment.status === "completed"
                              ? "text-green-600 dark:text-green-400"
                              : "text-red-600 dark:text-red-400"
                          }`}
                        >
                          {selectedExperiment.status === "completed" ? "已完成" : "失败"}
                        </div>
                      </div>
                      <div>
                        <div className="text-slate-500 dark:text-slate-400">数据点数</div>
                        <div className="text-slate-900 dark:text-slate-50 font-medium">
                          {selectedExperiment.parameters.time.length}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* 时间序列图表 */}
                  <div>
                    <h3 className="text-base font-semibold text-slate-900 dark:text-white flex items-center gap-2 mb-4">
                      <TrendingUp className="h-5 w-5 text-blue-500" />
                      参数时间序列
                    </h3>
                    <div ref={chartRef} className="h-64 w-full bg-white dark:bg-slate-800 rounded-lg p-2"></div>
                  </div>

                  {/* 统计分析 */}
                  <div>
                    <h3 className="text-base font-semibold text-slate-900 dark:text-white flex items-center gap-2 mb-4">
                      <BarChart3 className="h-5 w-5 text-blue-500" />
                      统计分析
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                      <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
                        <div className="text-sm font-medium text-slate-600 dark:text-slate-400 mb-3">
                          温度统计
                        </div>
                        <div className="space-y-2 text-sm">
                          <div className="flex justify-between">
                            <span className="text-slate-500 dark:text-slate-400">均值:</span>
                            <span className="text-slate-900 dark:text-slate-50">
                              {calculateStatistics(selectedExperiment.parameters.temperature).mean} ℃
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-slate-500 dark:text-slate-400">中位数:</span>
                            <span className="text-slate-900 dark:text-slate-50">
                              {calculateStatistics(selectedExperiment.parameters.temperature).median} ℃
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-slate-500 dark:text-slate-400">标准差:</span>
                            <span className="text-slate-900 dark:text-slate-50">
                              {calculateStatistics(selectedExperiment.parameters.temperature).stdDev}
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-slate-500 dark:text-slate-400">范围:</span>
                            <span className="text-slate-900 dark:text-slate-50">
                              {calculateStatistics(selectedExperiment.parameters.temperature).min} -{" "}
                              {calculateStatistics(selectedExperiment.parameters.temperature).max} ℃
                            </span>
                          </div>
                        </div>
                      </div>

                      <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
                        <div className="text-sm font-medium text-slate-600 dark:text-slate-400 mb-3">
                          压力统计
                        </div>
                        <div className="space-y-2 text-sm">
                          <div className="flex justify-between">
                            <span className="text-slate-500 dark:text-slate-400">均值:</span>
                            <span className="text-slate-900 dark:text-slate-50">
                              {calculateStatistics(selectedExperiment.parameters.pressure).mean} bar
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-slate-500 dark:text-slate-400">中位数:</span>
                            <span className="text-slate-900 dark:text-slate-50">
                              {calculateStatistics(selectedExperiment.parameters.pressure).median} bar
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-slate-500 dark:text-slate-400">标准差:</span>
                            <span className="text-slate-900 dark:text-slate-50">
                              {calculateStatistics(selectedExperiment.parameters.pressure).stdDev}
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-slate-500 dark:text-slate-400">范围:</span>
                            <span className="text-slate-900 dark:text-slate-50">
                              {calculateStatistics(selectedExperiment.parameters.pressure).min} -{" "}
                              {calculateStatistics(selectedExperiment.parameters.pressure).max} bar
                            </span>
                          </div>
                        </div>
                      </div>

                      <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
                        <div className="text-sm font-medium text-slate-600 dark:text-slate-400 mb-3">
                          流速统计
                        </div>
                        <div className="space-y-2 text-sm">
                          <div className="flex justify-between">
                            <span className="text-slate-500 dark:text-slate-400">均值:</span>
                            <span className="text-slate-900 dark:text-slate-50">
                              {calculateStatistics(selectedExperiment.parameters.flowRate).mean} mL/min
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-slate-500 dark:text-slate-400">中位数:</span>
                            <span className="text-slate-900 dark:text-slate-50">
                              {calculateStatistics(selectedExperiment.parameters.flowRate).median} mL/min
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-slate-500 dark:text-slate-400">标准差:</span>
                            <span className="text-slate-900 dark:text-slate-50">
                              {calculateStatistics(selectedExperiment.parameters.flowRate).stdDev}
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-slate-500 dark:text-slate-400">范围:</span>
                            <span className="text-slate-900 dark:text-slate-50">
                              {calculateStatistics(selectedExperiment.parameters.flowRate).min} -{" "}
                              {calculateStatistics(selectedExperiment.parameters.flowRate).max} mL/min
                            </span>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* 相关性分析 */}
                  <div>
                    <h3 className="text-base font-semibold text-slate-900 dark:text-white flex items-center gap-2 mb-4">
                      <BarChart3 className="h-5 w-5 text-blue-500" />
                      参数相关性分析
                    </h3>
                    <div ref={correlationChartRef} className="h-48 w-full bg-white dark:bg-slate-800 rounded-lg p-2"></div>
                  </div>
                </div>
              ) : (
                <div className="flex items-center justify-center h-full text-slate-500 dark:text-slate-400">
                  请选择一个实验查看分析结果
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

