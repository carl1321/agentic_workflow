"use client";

import { useEffect, useRef } from "react";

// Pulse animation style
const pulseStyle = `
  @keyframes pulse {
    0%, 100% { opacity: 0.6; }
    50% { opacity: 1; }
  }
`;

export function Dashboard() {
  const taskChartRef = useRef<HTMLDivElement>(null);
  const deviceChartRef = useRef<HTMLDivElement>(null);
  const taskChartInstance = useRef<any>(null);
  const deviceChartInstance = useRef<any>(null);

  useEffect(() => {
    let echarts: any;
    let mounted = true;

    // Dynamically import echarts
    import("echarts").then((module) => {
      if (!mounted) return;
      echarts = module.default || module;

      // Initialize task chart
      if (taskChartRef.current && !taskChartInstance.current) {
        const isDark = window.matchMedia("(prefers-color-scheme: dark)").matches || document.documentElement.classList.contains("dark");
        taskChartInstance.current = echarts.init(taskChartRef.current);
        taskChartInstance.current.setOption({
          tooltip: {
            trigger: "item",
            backgroundColor: isDark ? "rgba(30, 41, 59, 0.95)" : "rgba(255, 255, 255, 0.95)",
            borderColor: isDark ? "rgba(100, 116, 139, 0.3)" : "rgba(0, 0, 0, 0.1)",
            textStyle: {
              color: isDark ? "#e2e8f0" : "#1e293b",
            },
            formatter: "{b}: {c} ({d}%)",
          },
          legend: {
            orient: "horizontal",
            bottom: 10,
            textStyle: {
              color: isDark ? "#94a3b8" : "#64748b",
              fontSize: 12,
            },
          },
          color: ["#10b981", "#3b82f6", "#f59e0b", "#8b5cf6"],
          series: [
            {
              name: "任务状态",
              type: "pie",
              radius: ["50%", "75%"],
              center: ["50%", "45%"],
              avoidLabelOverlap: false,
              itemStyle: {
                borderRadius: 8,
                borderColor: isDark ? "#1e293b" : "#ffffff",
                borderWidth: 2,
              },
              label: {
                show: true,
                position: "outside",
                formatter: "{b}\n{d}%",
                fontSize: 12,
                color: isDark ? "#cbd5e1" : "#475569",
                fontWeight: 500,
              },
              labelLine: {
                show: true,
                length: 15,
                length2: 10,
                lineStyle: {
                  color: isDark ? "#475569" : "#cbd5e1",
                },
              },
              emphasis: {
                label: {
                  show: true,
                  fontSize: 14,
                  fontWeight: "bold",
                },
                itemStyle: {
                  shadowBlur: 10,
                  shadowOffsetX: 0,
                  shadowColor: "rgba(0, 0, 0, 0.2)",
                },
              },
              data: [
                { value: 42, name: "已完成" },
                { value: 38, name: "进行中" },
                { value: 19, name: "待审批" },
                { value: 27, name: "排队中" },
              ],
            },
          ],
        });
      }

      // Initialize device chart
      if (deviceChartRef.current && !deviceChartInstance.current) {
        deviceChartInstance.current = echarts.init(deviceChartRef.current);
        deviceChartInstance.current.setOption({
        tooltip: {
          trigger: "axis",
          axisPointer: {
            type: "shadow",
          },
        },
        grid: {
          left: "3%",
          right: "4%",
          bottom: "10%",
          top: "5%",
          containLabel: true,
        },
        xAxis: {
          type: "category",
          data: [
            "H-8791-压力机",
            "C-4523-反应釜",
            "B-3456-孵化器",
            "M-7821-示波器",
            "T-9812-热分析仪",
            "L-1287-离心机",
            "S-3467-分光仪",
          ],
          axisLabel: {
            color: "#94a3b8",
            fontSize: 11,
            rotate: 30,
          },
        },
        yAxis: {
          type: "value",
          name: "使用次数",
          nameTextStyle: {
            color: "#94a3b8",
          },
          axisLabel: {
            color: "#94a3b8",
            formatter: "{value} 次",
          },
          max: 25,
        },
        color: ["#818cf8"],
        series: [
          {
            name: "使用次数",
            type: "bar",
            barWidth: "60%",
            label: {
              show: true,
              position: "top",
              color: "#e2e8f0",
            },
            data: [24, 18, 15, 14, 12, 10, 8],
          },
        ],
        });
      }

      // Handle window resize
      const handleResize = () => {
        taskChartInstance.current?.resize();
        deviceChartInstance.current?.resize();
      };

      window.addEventListener("resize", handleResize);

      return () => {
        mounted = false;
        window.removeEventListener("resize", handleResize);
        taskChartInstance.current?.dispose();
        deviceChartInstance.current?.dispose();
      };
    });

    return () => {
      mounted = false;
      taskChartInstance.current?.dispose();
      deviceChartInstance.current?.dispose();
    };
  }, []);

  return (
    <>
      <style>{pulseStyle}</style>
      <div className="w-full h-full bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50">
        <div className="p-6">
        {/* Header */}
        <div className="mb-6">
          <h2 className="text-xl font-bold text-slate-900 dark:text-white">实验装置调度控制中心</h2>
          <p className="text-slate-600 dark:text-slate-300 text-sm mt-1">实时监控实验装置状态和任务进度</p>
        </div>

        {/* Status Cards - 4 cards like original */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-6">
          {/* 实验装置总数 */}
          <div className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 shadow-sm">
            <div className="border-b border-slate-200 dark:border-slate-700 p-5">
              <div className="flex items-center">
                <div className="h-12 w-12 rounded-full bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center mr-3">
                  <svg
                    className="h-6 w-6 text-blue-500 dark:text-blue-400"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z"
                    />
                  </svg>
                </div>
                <div>
                  <h3 className="text-slate-600 dark:text-slate-300 font-medium text-sm">实验装置总数</h3>
                  <div className="text-3xl font-bold text-slate-900 dark:text-white mt-1">42</div>
                </div>
              </div>
            </div>
            <div className="p-4">
              <div className="flex justify-between text-sm">
                <span className="text-slate-600 dark:text-slate-400 flex items-center">
                  <span className="w-2.5 h-2.5 rounded-full mr-2 bg-green-500"></span>
                  在线: <span className="text-slate-900 dark:text-white ml-1 font-semibold">36</span>
                </span>
                <span className="text-slate-600 dark:text-slate-400 flex items-center">
                  <span className="w-2.5 h-2.5 rounded-full mr-2 bg-slate-400"></span>
                  离线: <span className="text-slate-900 dark:text-white ml-1 font-semibold">6</span>
                </span>
              </div>
            </div>
          </div>

          {/* 当前任务数 */}
          <div className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 shadow-sm">
            <div className="border-b border-slate-200 dark:border-slate-700 p-5">
              <div className="flex items-center">
                <div className="h-12 w-12 rounded-full bg-violet-100 dark:bg-violet-900/30 flex items-center justify-center mr-3">
                  <svg
                    className="h-6 w-6 text-violet-500 dark:text-violet-400"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"
                    />
                  </svg>
                </div>
                <div>
                  <h3 className="text-slate-600 dark:text-slate-300 font-medium text-sm">当前任务数</h3>
                  <div className="text-3xl font-bold text-slate-900 dark:text-white mt-1">24</div>
                </div>
              </div>
            </div>
            <div className="p-4">
              <div className="flex flex-wrap gap-2">
                <span className="px-3 py-1 rounded-full text-xs font-semibold bg-blue-100 dark:bg-blue-900/50 text-blue-600 dark:text-blue-400">
                  进行中: 8
                </span>
                <span className="px-3 py-1 rounded-full text-xs font-semibold bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300">
                  待处理: 9
                </span>
                <span className="px-3 py-1 rounded-full text-xs font-semibold bg-green-100 dark:bg-green-900/50 text-green-600 dark:text-green-400">
                  已完成: 7
                </span>
              </div>
            </div>
          </div>

          {/* 异常报警 */}
          <div className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 shadow-sm">
            <div className="border-b border-slate-200 dark:border-slate-700 p-5">
              <div className="flex items-center">
                <div className="h-12 w-12 rounded-full bg-orange-100 dark:bg-orange-900/30 flex items-center justify-center mr-3">
                  <svg
                    className="h-6 w-6 text-orange-500 dark:text-orange-400"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
                    />
                  </svg>
                </div>
                <div>
                  <h3 className="text-slate-600 dark:text-slate-300 font-medium text-sm">异常报警</h3>
                  <div className="text-3xl font-bold text-slate-900 dark:text-white mt-1">4</div>
                </div>
              </div>
            </div>
            <div className="p-4">
              <div className="flex flex-wrap gap-2">
                <span className="px-3 py-1 rounded-full text-xs font-semibold bg-red-100 dark:bg-red-900/50 text-red-600 dark:text-red-400">
                  紧急: 1
                </span>
                <span className="px-3 py-1 rounded-full text-xs font-semibold bg-yellow-100 dark:bg-yellow-900/50 text-yellow-600 dark:text-yellow-400">
                  警告: 3
                </span>
              </div>
            </div>
          </div>

          {/* 资源使用率 */}
          <div className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 shadow-sm">
            <div className="border-b border-slate-200 dark:border-slate-700 p-5">
              <div className="flex items-center">
                <div className="h-12 w-12 rounded-full bg-sky-100 dark:bg-sky-900/30 flex items-center justify-center mr-3">
                  <svg
                    className="h-6 w-6 text-sky-500 dark:text-sky-400"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M13 10V3L4 14h7v7l9-11h-7z"
                    />
                  </svg>
                </div>
                <div>
                  <h3 className="text-slate-600 dark:text-slate-300 font-medium text-sm">资源使用率</h3>
                  <div className="text-3xl font-bold text-slate-900 dark:text-white mt-1">76%</div>
                </div>
              </div>
            </div>
            <div className="p-4">
              <div className="w-full bg-slate-200 dark:bg-slate-700 h-2 rounded-full">
                <div className="bg-sky-500 h-2 rounded-full" style={{ width: "76%" }}></div>
              </div>
              <div className="text-slate-600 dark:text-slate-400 text-xs mt-2">CPU: 64% | 内存: 82% | 网络: 45%</div>
            </div>
          </div>
        </div>

        {/* Charts */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          <div className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 shadow-sm">
            <div className="flex justify-between items-center border-b border-slate-200 dark:border-slate-700 p-5">
              <h3 className="font-semibold text-slate-900 dark:text-white flex items-center">
                <svg
                  className="h-5 w-5 text-blue-500 dark:text-blue-400 mr-2"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M11 3.055A9.001 9.001 0 1020.945 13H11V3.055z"
                  />
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M20.488 9H15V3.512A9.025 9.025 0 0120.488 9z"
                  />
                </svg>
                任务状态分布
              </h3>
              <div className="text-xs text-slate-600 dark:text-slate-400">本周统计</div>
            </div>
            <div className="p-4">
              <div ref={taskChartRef} className="h-80 w-full"></div>
            </div>
          </div>

          <div className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 shadow-sm">
            <div className="flex justify-between items-center border-b border-slate-200 dark:border-slate-700 p-5">
              <h3 className="font-semibold text-slate-900 dark:text-white flex items-center">
                <svg
                  className="h-5 w-5 text-violet-500 dark:text-violet-400 mr-2"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
                  />
                </svg>
                本周装置使用次数排行
              </h3>
              <div className="text-xs text-slate-600 dark:text-slate-400">本周统计</div>
            </div>
            <div className="p-4">
              <div ref={deviceChartRef} className="h-80 w-full"></div>
            </div>
          </div>
        </div>

        {/* Monitor and Tasks */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Device Monitor */}
          <div className="lg:col-span-1 bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 shadow-sm">
            <h3 className="font-semibold text-slate-900 dark:text-white border-b border-slate-200 dark:border-slate-700 flex items-center p-5">
              <svg
                className="h-5 w-5 text-orange-500 dark:text-orange-400 mr-2"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
                />
              </svg>
              装置实时监控
            </h3>
            <div className="p-4 space-y-4">
              <div className="relative rounded-xl overflow-hidden bg-slate-100 dark:bg-slate-900" style={{ height: "280px" }}>
                <div 
                  className="absolute top-4 right-4 px-3 py-1 rounded-full text-xs font-semibold z-10 bg-blue-500 text-white"
                  style={{ 
                    animation: "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
                  }}
                >
                  进行中
                </div>
                <img
                  src="https://images.unsplash.com/photo-1581091226825-a6a2a5aee158?ixlib=rb-4.0.3&auto=format&fit=crop&w=800&h=500&q=80"
                  alt="实验室压力机"
                  className="w-full h-full object-cover"
                  onError={(e) => {
                    // Fallback to placeholder if image fails to load
                    e.currentTarget.style.display = 'none';
                    const placeholder = e.currentTarget.nextElementSibling;
                    if (placeholder) placeholder.style.display = 'flex';
                  }}
                />
                <div className="w-full h-full flex items-center justify-center" style={{ background: "#121f36", display: 'none' }}>
                  <div className="text-center">
                    <svg
                      className="h-24 w-24 mx-auto mb-2"
                      style={{ color: "#475569" }}
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={1.5}
                        d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
                      />
                    </svg>
                    <div className="text-sm text-slate-500 dark:text-slate-400">监控画面</div>
                  </div>
                </div>
                <div className="absolute bottom-0 left-0 right-0 p-4 bg-black/70 dark:bg-black/80">
                  <div className="font-medium text-white flex items-center">
                    H-8791-压力机
                    <span 
                      className="w-2.5 h-2.5 rounded-full ml-2 bg-blue-500"
                      style={{ animation: "pulse 2s infinite" }}
                    ></span>
                  </div>
                  <div className="text-sm text-slate-200 dark:text-slate-300 mt-1">
                    当前任务: 材料拉伸实验 (剩余45分钟)
                  </div>
                </div>
              </div>

              <div className="relative rounded-xl overflow-hidden bg-slate-100 dark:bg-slate-900" style={{ height: "280px" }}>
                <div className="absolute top-4 right-4 px-3 py-1 rounded-full text-xs font-semibold z-10 bg-green-500 text-white">
                  待机中
                </div>
                <img
                  src="https://images.unsplash.com/photo-1582719471384-894fbb16e074?ixlib=rb-4.0.3&auto=format&fit=crop&w=800&h=500&q=80"
                  alt="实验室反应釜"
                  className="w-full h-full object-cover"
                  onError={(e) => {
                    // Fallback to placeholder if image fails to load
                    e.currentTarget.style.display = 'none';
                    const placeholder = e.currentTarget.nextElementSibling;
                    if (placeholder) placeholder.style.display = 'flex';
                  }}
                />
                <div className="w-full h-full flex items-center justify-center" style={{ background: "#121f36", display: 'none' }}>
                  <div className="text-center">
                    <svg
                      className="h-24 w-24 mx-auto mb-2"
                      style={{ color: "#475569" }}
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={1.5}
                        d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
                      />
                    </svg>
                    <div className="text-sm text-slate-500 dark:text-slate-400">监控画面</div>
                  </div>
                </div>
                <div className="absolute bottom-0 left-0 right-0 p-4 bg-black/70 dark:bg-black/80">
                  <div className="font-medium text-white flex items-center">
                    C-4523-反应釜
                    <span className="w-2.5 h-2.5 rounded-full ml-2 bg-green-500"></span>
                  </div>
                  <div className="text-sm text-slate-200 dark:text-slate-300 mt-1">已完成任务: 纳米结构分析</div>
                </div>
              </div>
            </div>
          </div>

          {/* Task List */}
          <div className="lg:col-span-2 bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 shadow-sm">
            <div className="flex justify-between items-center border-b border-slate-200 dark:border-slate-700 p-5">
              <h3 className="font-semibold text-slate-900 dark:text-white flex items-center">
                <svg
                  className="h-5 w-5 text-sky-500 dark:text-sky-400 mr-2"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"
                  />
                </svg>
                近期实验任务
              </h3>
              <button className="bg-blue-500 hover:bg-blue-600 dark:bg-blue-600 dark:hover:bg-blue-500 text-white py-2 px-4 rounded-lg text-sm flex items-center transition-colors">
                <svg
                  className="h-4 w-4 mr-1"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M12 4v16m8-8H4"
                  />
                </svg>
                新建任务
              </button>
            </div>
            <div className="p-4">
              <div className="overflow-x-auto">
                <table className="min-w-full">
                <thead>
                  <tr className="text-slate-600 dark:text-slate-400 text-left text-sm border-b border-slate-200 dark:border-slate-700">
                    <th className="py-3 px-4">任务ID</th>
                    <th className="py-3 px-4">实验名称</th>
                    <th className="py-3 px-4">使用装置</th>
                    <th className="py-3 px-4">负责人</th>
                    <th className="py-3 px-4">状态</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    {
                      id: "M-1024",
                      name: "纳米材料拉伸测试",
                      device: "万能试验机 #3",
                      owner: "张教授",
                      status: "进行中",
                      statusColor: "bg-blue-900/50 text-blue-400",
                    },
                    {
                      id: "M-1023",
                      name: "高分子材料热变形",
                      device: "高温热压炉 #1",
                      owner: "李博士",
                      status: "进行中",
                      statusColor: "bg-blue-900/50 text-blue-400",
                    },
                    {
                      id: "M-1022",
                      name: "金属疲劳测试",
                      device: "疲劳试验台 #2",
                      owner: "王研究员",
                      status: "排队中",
                      statusColor: "bg-amber-900/50 text-amber-400",
                    },
                    {
                      id: "M-1021",
                      name: "材料成分光谱分析",
                      device: "光谱仪 #5",
                      owner: "刘教授",
                      status: "已完成",
                      statusColor: "bg-green-900/50 text-green-400",
                    },
                    {
                      id: "M-1020",
                      name: "复合材料抗压强度",
                      device: "压力试验机 #4",
                      owner: "陈工程师",
                      status: "排队中",
                      statusColor: "bg-amber-900/50 text-amber-400",
                    },
                    {
                      id: "M-1019",
                      name: "纳米涂层成分分析",
                      device: "电子显微镜 #2",
                      owner: "杨博士",
                      status: "已完成",
                      statusColor: "bg-green-900/50 text-green-400",
                    },
                  ].map((task) => (
                    <tr
                      key={task.id}
                      className="border-b border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700/30 transition-colors"
                    >
                      <td className="py-3 px-4">{task.id}</td>
                      <td className="py-3 px-4">{task.name}</td>
                      <td className="py-3 px-4">{task.device}</td>
                      <td className="py-3 px-4">{task.owner}</td>
                      <td className="py-3 px-4">
                        <span
                          className="px-3 py-1 rounded-full text-xs font-semibold"
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            borderRadius: "20px",
                            fontSize: "12px",
                            fontWeight: 600,
                            ...(task.status === "进行中" ? {
                              background: "rgba(30, 58, 138, 0.3)",
                              color: "#3b82f6",
                            } : task.status === "排队中" ? {
                              background: "rgba(146, 64, 14, 0.3)",
                              color: "#f59e0b",
                            } : {
                              background: "rgba(5, 46, 22, 0.3)",
                              color: "#10b981",
                            }),
                          }}
                        >
                          {task.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    </>
  );
}

