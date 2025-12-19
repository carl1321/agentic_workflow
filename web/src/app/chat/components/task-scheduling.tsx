"use client";

import { useState, useEffect, useRef } from "react";
import { Plus, Pause, Settings, Move, Eye, Search, X } from "lucide-react";
import { Button } from "~/components/ui/button";
import { TaskCreationForm } from "./task-creation-form";

interface Task {
  id: string;
  name: string;
  status: "pending" | "running" | "done";
  subplatform: string;
  priority: string;
  equipment: string;
  startTime: string;
  endTime: string;
  operator: string;
  progress: number;
}

const mockTasks: Task[] = [
  {
    id: "#T20231001",
    name: "聚合物复合实验",
    status: "running",
    subplatform: "聚合物",
    priority: "高",
    equipment: "高精度搅拌装机 HMS-700，恒温控制器 TC-120",
    startTime: "2023-10-22 08:30:00",
    endTime: "2023-10-23 14:00:00",
    operator: "李博士",
    progress: 65,
  },
  {
    id: "#T20231002",
    name: "合金疲劳测试",
    status: "pending",
    subplatform: "功能合金",
    priority: "中",
    equipment: "疲劳试验机 FT-500",
    startTime: "2023-10-25 09:00:00",
    endTime: "2023-10-26 18:00:00",
    operator: "王工程师",
    progress: 0,
  },
  {
    id: "#T20231003",
    name: "电池材料充放电",
    status: "running",
    subplatform: "储能材料",
    priority: "高",
    equipment: "电化学工作站 ECW-9000",
    startTime: "2023-10-23 10:00:00",
    endTime: "2023-10-24 16:00:00",
    operator: "张研究员",
    progress: 45,
  },
  {
    id: "#T20231004",
    name: "薄膜涂层测试",
    status: "done",
    subplatform: "聚合物",
    priority: "低",
    equipment: "薄膜沉积系统 TD-600",
    startTime: "2023-10-20 08:00:00",
    endTime: "2023-10-21 17:00:00",
    operator: "赵技术员",
    progress: 100,
  },
  {
    id: "#T20231005",
    name: "金属硬度测试",
    status: "pending",
    subplatform: "功能合金",
    priority: "中",
    equipment: "硬度测试仪 HT-300",
    startTime: "2023-10-26 14:00:00",
    endTime: "2023-10-27 12:00:00",
    operator: "刘助理",
    progress: 0,
  },
];

export function TaskScheduling() {
  const [tasks, setTasks] = useState<Task[]>(mockTasks);
  const [filteredTasks, setFilteredTasks] = useState<Task[]>(mockTasks);
  const [selectedTask, setSelectedTask] = useState<Task | null>(mockTasks[0]);
  const [filters, setFilters] = useState({
    taskId: "",
    name: "",
    status: "",
  });
  const [showCreateModal, setShowCreateModal] = useState(false);
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<any>(null);

  // 应用筛选
  useEffect(() => {
    let filtered = [...tasks];

    if (filters.taskId) {
      filtered = filtered.filter((task) =>
        task.id.toLowerCase().includes(filters.taskId.toLowerCase())
      );
    }
    if (filters.name) {
      filtered = filtered.filter((task) =>
        task.name.toLowerCase().includes(filters.name.toLowerCase())
      );
    }
    if (filters.status) {
      filtered = filtered.filter((task) => task.status === filters.status);
    }

    setFilteredTasks(filtered);
    // 如果选中的任务不在筛选结果中，选择第一个任务
    if (selectedTask && !filtered.find((t) => t.id === selectedTask.id)) {
      setSelectedTask(filtered.length > 0 ? filtered[0] : null);
    }
  }, [filters, tasks, selectedTask]);

  // 初始化图表
  useEffect(() => {
    let echarts: any;
    let mounted = true;

    import("echarts").then((module) => {
      if (!mounted) return;
      echarts = module.default || module;

      if (chartRef.current && !chartInstance.current) {
        chartInstance.current = echarts.init(chartRef.current);
        updateChart();
      }
    });

    // Handle window resize
    const handleResize = () => {
      chartInstance.current?.resize();
    };

    window.addEventListener("resize", handleResize);

    return () => {
      mounted = false;
      window.removeEventListener("resize", handleResize);
      chartInstance.current?.dispose();
    };
  }, []);

  // 更新图表数据
  useEffect(() => {
    if (chartInstance.current && selectedTask) {
      updateChart();
    }
  }, [selectedTask]);

  const updateChart = () => {
    if (!chartInstance.current) return;

    const isDark =
      window.matchMedia("(prefers-color-scheme: dark)").matches ||
      document.documentElement.classList.contains("dark");

    chartInstance.current.setOption({
      grid: { top: 10, right: 10, bottom: 20, left: 40 },
      xAxis: {
        type: "category",
        data: ["8:00", "9:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00"],
        axisLabel: {
          color: isDark ? "#94a3b8" : "#64748b",
          fontSize: 11,
        },
      },
      yAxis: {
        type: "value",
        name: "温度(℃)",
        nameTextStyle: {
          color: isDark ? "#94a3b8" : "#64748b",
        },
        axisLabel: {
          color: isDark ? "#94a3b8" : "#64748b",
        },
      },
      series: [
        {
          data: [65, 70, 78, 82, 80, 77, 75, 74],
          type: "line",
          smooth: true,
          lineStyle: { width: 2, color: "#3b82f6" },
          itemStyle: { color: "#3b82f6" },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                {
                  offset: 0,
                  color: "rgba(59, 130, 246, 0.5)",
                },
                {
                  offset: 1,
                  color: "rgba(59, 130, 246, 0)",
                },
              ],
            },
          },
        },
      ],
    });
  };

  const handleFilterChange = (key: string, value: string) => {
    setFilters({ ...filters, [key]: value });
  };

  const getStatusClass = (status: string) => {
    const classes: Record<string, string> = {
      pending: "bg-orange-100 dark:bg-orange-900/50 text-orange-600 dark:text-orange-400",
      running: "bg-green-100 dark:bg-green-900/50 text-green-600 dark:text-green-400",
      done: "bg-blue-100 dark:bg-blue-900/50 text-blue-600 dark:text-blue-400",
    };
    return classes[status] || classes.pending;
  };

  const getStatusText = (status: string) => {
    const texts: Record<string, string> = {
      pending: "未开始",
      running: "运行中",
      done: "已完成",
    };
    return texts[status] || status;
  };

  const handleCreateTask = (formData: any) => {
    // 生成新的任务ID
    const newTaskId = `#T${new Date().getFullYear()}${String(tasks.length + 1).padStart(4, "0")}`;
    
    // 创建新任务
    const newTask: Task = {
      id: newTaskId,
      name: `新建实验-${new Date().toLocaleDateString()}`,
      status: "pending",
      subplatform: "聚合物", // 默认值，实际应该从表单获取
      priority: "中",
      equipment: "待分配",
      startTime: new Date().toLocaleString("zh-CN"),
      endTime: new Date(Date.now() + 24 * 60 * 60 * 1000).toLocaleString("zh-CN"),
      operator: "当前用户", // 实际应该从用户上下文获取
      progress: 0,
    };

    // 添加到任务列表
    setTasks([...tasks, newTask]);
    setShowCreateModal(false);
    
    // 选中新创建的任务
    setSelectedTask(newTask);
  };

  return (
    <div className="w-full h-full bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 overflow-y-auto">
      <div className="max-w-7xl mx-auto p-4 md:p-8">
        {/* 页面标题 */}
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl md:text-3xl font-bold text-slate-900 dark:text-white">
            任务调度管理
          </h1>
          <Button
            onClick={() => setShowCreateModal(true)}
            className="bg-blue-500 hover:bg-blue-600 dark:bg-blue-600 dark:hover:bg-blue-500 text-white"
          >
            <Plus className="h-4 w-4 mr-2" />
            创建任务
          </Button>
        </div>

        {/* 筛选面板 */}
        <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 shadow-sm p-4 mb-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                任务ID
              </label>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
                <input
                  type="text"
                  value={filters.taskId}
                  onChange={(e) => handleFilterChange("taskId", e.target.value)}
                  placeholder="请输入任务ID"
                  className="w-full pl-10 pr-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                实验名称
              </label>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
                <input
                  type="text"
                  value={filters.name}
                  onChange={(e) => handleFilterChange("name", e.target.value)}
                  placeholder="请输入实验名称"
                  className="w-full pl-10 pr-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
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
                <option value="pending">未开始</option>
                <option value="running">运行中</option>
                <option value="done">已完成</option>
              </select>
            </div>
          </div>
        </div>

        {/* 任务列表和详情面板 */}
        <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 shadow-sm overflow-hidden">
          <div className="flex h-[calc(100vh-300px)] min-h-[600px]">
            {/* 任务列表 */}
            <div className="w-2/5 border-r border-slate-200 dark:border-slate-700 overflow-y-auto">
              <table className="w-full">
                <thead className="bg-slate-50 dark:bg-slate-900/50 sticky top-0">
                  <tr>
                    <th className="px-4 py-3 text-left text-sm font-medium text-slate-600 dark:text-slate-400">
                      任务 ID
                    </th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-slate-600 dark:text-slate-400">
                      实验名称
                    </th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-slate-600 dark:text-slate-400">
                      状态
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
                  {filteredTasks.map((task) => (
                    <tr
                      key={task.id}
                      onClick={() => setSelectedTask(task)}
                      className={`cursor-pointer transition-colors ${
                        selectedTask?.id === task.id
                          ? "bg-blue-50 dark:bg-blue-950/30"
                          : "hover:bg-slate-50 dark:hover:bg-slate-700/30"
                      }`}
                    >
                      <td className="px-4 py-3 text-sm text-slate-900 dark:text-slate-50">
                        {task.id}
                      </td>
                      <td className="px-4 py-3 text-sm text-slate-600 dark:text-slate-400">
                        {task.name}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-medium ${getStatusClass(
                            task.status
                          )}`}
                        >
                          {getStatusText(task.status)}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* 任务详情面板 */}
            <div className="w-3/5 overflow-y-auto p-6 bg-slate-50 dark:bg-slate-900/50">
              {selectedTask ? (
                <div className="space-y-6">
                  <div>
                    <h2 className="text-lg font-semibold text-slate-900 dark:text-white flex items-center gap-2 mb-4">
                      <svg
                        className="h-5 w-5 text-blue-500"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                        />
                      </svg>
                      任务详情 {selectedTask.id}
                    </h2>
                    <div className="space-y-3 text-sm">
                      <p>
                        <strong className="text-slate-700 dark:text-slate-300">实验名称：</strong>
                        <span className="text-slate-600 dark:text-slate-400">
                          {selectedTask.name}
                        </span>
                      </p>
                      <p>
                        <strong className="text-slate-700 dark:text-slate-300">所属子平台：</strong>
                        <span className="text-slate-600 dark:text-slate-400">
                          {selectedTask.subplatform}
                        </span>
                      </p>
                      <p>
                        <strong className="text-slate-700 dark:text-slate-300">优先级：</strong>
                        <span className="text-slate-600 dark:text-slate-400">
                          {selectedTask.priority}
                        </span>
                      </p>
                      <p>
                        <strong className="text-slate-700 dark:text-slate-300">分配装备：</strong>
                        <span className="text-slate-600 dark:text-slate-400">
                          {selectedTask.equipment}
                        </span>
                      </p>
                      <p>
                        <strong className="text-slate-700 dark:text-slate-300">开始时间：</strong>
                        <span className="text-slate-600 dark:text-slate-400">
                          {selectedTask.startTime}
                        </span>
                      </p>
                      <p>
                        <strong className="text-slate-700 dark:text-slate-300">预计完成时间：</strong>
                        <span className="text-slate-600 dark:text-slate-400">
                          {selectedTask.endTime}
                        </span>
                      </p>
                      <p>
                        <strong className="text-slate-700 dark:text-slate-300">操作人：</strong>
                        <span className="text-slate-600 dark:text-slate-400">
                          {selectedTask.operator}
                        </span>
                      </p>
                      <p>
                        <strong className="text-slate-700 dark:text-slate-300">当前进度：</strong>
                        <span className="text-slate-600 dark:text-slate-400">
                          {selectedTask.progress}%
                        </span>
                      </p>
                      <div className="h-2 bg-slate-200 dark:bg-slate-700 rounded-full mt-2">
                        <div
                          className="h-full bg-green-500 rounded-full transition-all"
                          style={{ width: `${selectedTask.progress}%` }}
                        ></div>
                      </div>
                    </div>
                  </div>

                  {/* 操作按钮 */}
                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        // TODO: 实现暂停任务
                      }}
                    >
                      <Pause className="h-4 w-4 mr-2" />
                      暂停任务
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        // TODO: 实现调整参数
                      }}
                    >
                      <Settings className="h-4 w-4 mr-2" />
                      调整参数
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        // TODO: 实现迁移装备
                      }}
                    >
                      <Move className="h-4 w-4 mr-2" />
                      迁移装备
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        // TODO: 实现查看详情
                      }}
                    >
                      <Eye className="h-4 w-4 mr-2" />
                      查看详情
                    </Button>
                  </div>

                  {/* 实验数据监控图表 */}
                  <div>
                    <h3 className="text-base font-semibold text-slate-900 dark:text-white flex items-center gap-2 mb-4">
                      <svg
                        className="h-5 w-5 text-blue-500"
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
                      实验数据监控
                    </h3>
                    <div ref={chartRef} className="h-32 w-full"></div>
                  </div>
                </div>
              ) : (
                <div className="flex items-center justify-center h-full text-slate-500 dark:text-slate-400">
                  请选择一个任务查看详情
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* 创建任务模态框 */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 dark:bg-black/70">
          <div className="relative w-full max-w-5xl max-h-[90vh] bg-white dark:bg-slate-900 rounded-lg shadow-xl overflow-hidden flex flex-col">
            {/* 模态框头部 */}
            <div className="flex items-center justify-between p-4 border-b border-slate-200 dark:border-slate-700">
              <h2 className="text-xl font-semibold text-slate-900 dark:text-white">新建实验</h2>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setShowCreateModal(false)}
                className="h-8 w-8"
              >
                <X className="h-4 w-4" />
              </Button>
            </div>

            {/* 模态框内容 */}
            <div className="flex-1 overflow-y-auto">
              <TaskCreationForm
                onSave={handleCreateTask}
                onCancel={() => setShowCreateModal(false)}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

