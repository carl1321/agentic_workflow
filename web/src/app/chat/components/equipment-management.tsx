"use client";

import { useState, useEffect, useMemo } from "react";
import { Search, Plus, Trash2, Edit, ChevronLeft, ChevronRight, Filter, X, ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "~/components/ui/button";

interface Equipment {
  id: number;
  name: string;
  model: string;
  subplatform: string;
  subplatformName: string;
  type: string;
  typeName: string;
  status: string;
  statusName: string;
  maintenance: string;
  purchased: string;
  manager: string;
}

const equipmentData: Equipment[] = [
  {
    id: 1,
    name: "反应釜A-100",
    model: "RK-2023-001",
    subplatform: "polymer",
    subplatformName: "聚合物子平台",
    type: "prepare",
    typeName: "制备类",
    status: "running",
    statusName: "运行中",
    maintenance: "2024-03-15",
    purchased: "2023-01-10",
    manager: "张三",
  },
  {
    id: 2,
    name: "电子显微镜B-200",
    model: "EM-2023-002",
    subplatform: "fun_alloy",
    subplatformName: "功能合金子平台",
    type: "characterize",
    typeName: "表征类",
    status: "idle",
    statusName: "待机中",
    maintenance: "2024-02-20",
    purchased: "2023-02-15",
    manager: "李四",
  },
  {
    id: 3,
    name: "光谱分析仪C-300",
    model: "SA-2023-003",
    subplatform: "energy_storage",
    subplatformName: "储能材料子平台",
    type: "characterize",
    typeName: "表征类",
    status: "maintenance",
    statusName: "维护中",
    maintenance: "2024-04-05",
    purchased: "2023-03-20",
    manager: "王五",
  },
  {
    id: 4,
    name: "烧结炉D-400",
    model: "SL-2023-004",
    subplatform: "polymer",
    subplatformName: "聚合物子平台",
    type: "prepare",
    typeName: "制备类",
    status: "fault",
    statusName: "故障",
    maintenance: "2024-01-10",
    purchased: "2023-04-25",
    manager: "赵六",
  },
  {
    id: 5,
    name: "成分检测仪E-500",
    model: "CD-2023-005",
    subplatform: "fun_alloy",
    subplatformName: "功能合金子平台",
    type: "detect",
    typeName: "检测类",
    status: "running",
    statusName: "运行中",
    maintenance: "2024-03-25",
    purchased: "2023-05-30",
    manager: "钱七",
  },
  {
    id: 6,
    name: "薄膜沉积系统F-600",
    model: "TD-2023-006",
    subplatform: "energy_storage",
    subplatformName: "储能材料子平台",
    type: "prepare",
    typeName: "制备类",
    status: "idle",
    statusName: "待机中",
    maintenance: "2024-02-15",
    purchased: "2023-06-05",
    manager: "孙八",
  },
  {
    id: 7,
    name: "力学性能测试仪G-700",
    model: "MP-2023-007",
    subplatform: "polymer",
    subplatformName: "聚合物子平台",
    type: "characterize",
    typeName: "表征类",
    status: "running",
    statusName: "运行中",
    maintenance: "2024-03-10",
    purchased: "2023-07-10",
    manager: "周九",
  },
  {
    id: 8,
    name: "无损探伤仪H-800",
    model: "NDT-2023-008",
    subplatform: "fun_alloy",
    subplatformName: "功能合金子平台",
    type: "detect",
    typeName: "检测类",
    status: "disabled",
    statusName: "已停用",
    maintenance: "2023-12-05",
    purchased: "2022-08-15",
    manager: "吴十",
  },
  {
    id: 9,
    name: "环境模拟试验箱I-900",
    model: "EST-2023-009",
    subplatform: "energy_storage",
    subplatformName: "储能材料子平台",
    type: "detect",
    typeName: "检测类",
    status: "maintenance",
    statusName: "维护中",
    maintenance: "2024-04-10",
    purchased: "2023-09-20",
    manager: "郑十一",
  },
  {
    id: 10,
    name: "高温炉J-1000",
    model: "HF-2023-010",
    subplatform: "polymer",
    subplatformName: "聚合物子平台",
    type: "prepare",
    typeName: "制备类",
    status: "running",
    statusName: "运行中",
    maintenance: "2024-03-05",
    purchased: "2023-10-25",
    manager: "王十二",
  },
];

type SortField = "name" | "maintenance" | null;
type SortOrder = "asc" | "desc";

export function EquipmentManagement() {
  const [equipments, setEquipments] = useState<Equipment[]>(equipmentData);
  const [filteredEquipments, setFilteredEquipments] = useState<Equipment[]>(equipmentData);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [currentPage, setCurrentPage] = useState(1);
  const [isFilterExpanded, setIsFilterExpanded] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [sortField, setSortField] = useState<SortField>(null);
  const [sortOrder, setSortOrder] = useState<SortOrder>("asc");

  // 筛选条件
  const [filters, setFilters] = useState({
    subplatform: "",
    type: "",
    status: "",
    search: "",
  });

  const pageSize = 10;

  // 应用筛选
  useEffect(() => {
    setIsLoading(true);
    setTimeout(() => {
      let filtered = [...equipments];

      if (filters.subplatform) {
        filtered = filtered.filter((item) => item.subplatform === filters.subplatform);
      }
      if (filters.type) {
        filtered = filtered.filter((item) => item.type === filters.type);
      }
      if (filters.status) {
        filtered = filtered.filter((item) => item.status === filters.status);
      }
      if (filters.search) {
        const searchLower = filters.search.toLowerCase();
        filtered = filtered.filter(
          (item) =>
            item.name.toLowerCase().includes(searchLower) ||
            item.model.toLowerCase().includes(searchLower)
        );
      }

      // 应用排序
      if (sortField) {
        filtered.sort((a, b) => {
          let aVal: any;
          let bVal: any;

          if (sortField === "name") {
            aVal = a.name;
            bVal = b.name;
          } else if (sortField === "maintenance") {
            aVal = new Date(a.maintenance).getTime();
            bVal = new Date(b.maintenance).getTime();
          }

          if (sortOrder === "asc") {
            return aVal > bVal ? 1 : aVal < bVal ? -1 : 0;
          } else {
            return aVal < bVal ? 1 : aVal > bVal ? -1 : 0;
          }
        });
      }

      setFilteredEquipments(filtered);
      setIsLoading(false);
      setCurrentPage(1);
    }, 300);
  }, [filters, equipments, sortField, sortOrder]);

  // 分页数据
  const paginatedData = useMemo(() => {
    const startIndex = (currentPage - 1) * pageSize;
    return filteredEquipments.slice(startIndex, startIndex + pageSize);
  }, [filteredEquipments, currentPage]);

  const totalPages = Math.ceil(filteredEquipments.length / pageSize);

  // 表单状态
  const [formData, setFormData] = useState({
    name: "",
    model: "",
    subplatform: "",
    type: "",
    status: "running",
    maintenance: "",
    purchased: "",
    manager: "",
  });

  const [formErrors, setFormErrors] = useState({
    name: "",
    model: "",
  });

  // 处理全选
  const handleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedIds(paginatedData.map((item) => item.id));
    } else {
      setSelectedIds([]);
    }
  };

  // 处理行选择
  const handleRowSelect = (id: number, checked: boolean) => {
    if (checked) {
      setSelectedIds([...selectedIds, id]);
    } else {
      setSelectedIds(selectedIds.filter((itemId) => itemId !== id));
    }
  };

  // 处理筛选
  const handleFilterChange = (key: string, value: string) => {
    setFilters({ ...filters, [key]: value });
  };

  // 重置筛选
  const handleResetFilter = () => {
    setFilters({
      subplatform: "",
      type: "",
      status: "",
      search: "",
    });
  };

  // 处理排序
  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortOrder(sortOrder === "asc" ? "desc" : "asc");
    } else {
      setSortField(field);
      setSortOrder("asc");
    }
  };

  // 打开新建弹窗
  const handleCreate = () => {
    setEditingId(null);
    setFormData({
      name: "",
      model: "",
      subplatform: "",
      type: "",
      status: "running",
      maintenance: "",
      purchased: "",
      manager: "",
    });
    setFormErrors({ name: "", model: "" });
    setShowModal(true);
  };

  // 打开编辑弹窗
  const handleEdit = (equipment: Equipment) => {
    setEditingId(equipment.id);
    setFormData({
      name: equipment.name,
      model: equipment.model,
      subplatform: equipment.subplatform,
      type: equipment.type,
      status: equipment.status,
      maintenance: equipment.maintenance,
      purchased: equipment.purchased,
      manager: equipment.manager,
    });
    setFormErrors({ name: "", model: "" });
    setShowModal(true);
  };

  // 处理删除
  const handleDelete = (id: number) => {
    setSelectedIds([id]);
    setShowDeleteModal(true);
  };

  // 确认删除
  const handleConfirmDelete = () => {
    setEquipments(equipments.filter((item) => !selectedIds.includes(item.id)));
    setSelectedIds([]);
    setShowDeleteModal(false);
  };

  // 处理表单提交
  const handleSubmit = () => {
    const errors = { name: "", model: "" };
    let isValid = true;

    if (!formData.name.trim()) {
      errors.name = "请输入装备名称";
      isValid = false;
    }

    if (!formData.model.trim()) {
      errors.model = "请输入型号";
      isValid = false;
    } else if (!editingId) {
      // 新建时检查型号是否重复
      const isDuplicate = equipments.some((item) => item.model === formData.model);
      if (isDuplicate) {
        errors.model = "型号已存在，请重新输入";
        isValid = false;
      }
    }

    if (!formData.subplatform || !formData.type || !formData.status) {
      isValid = false;
    }

    setFormErrors(errors);

    if (!isValid) {
      return;
    }

    const subplatformNames: Record<string, string> = {
      polymer: "聚合物子平台",
      fun_alloy: "功能合金子平台",
      energy_storage: "储能材料子平台",
    };

    const typeNames: Record<string, string> = {
      prepare: "制备类",
      characterize: "表征类",
      detect: "检测类",
    };

    const statusNames: Record<string, string> = {
      running: "运行中",
      idle: "待机中",
      maintenance: "维护中",
      fault: "故障",
      disabled: "已停用",
    };

    const newEquipment: Equipment = {
      id: editingId || Math.max(...equipments.map((item) => item.id), 0) + 1,
      name: formData.name,
      model: formData.model,
      subplatform: formData.subplatform,
      subplatformName: subplatformNames[formData.subplatform] || "",
      type: formData.type,
      typeName: typeNames[formData.type] || "",
      status: formData.status,
      statusName: statusNames[formData.status] || "",
      maintenance: formData.maintenance,
      purchased: formData.purchased,
      manager: formData.manager,
    };

    if (editingId) {
      setEquipments(
        equipments.map((item) => (item.id === editingId ? newEquipment : item))
      );
    } else {
      setEquipments([...equipments, newEquipment]);
    }

    setShowModal(false);
  };

  // 获取状态标签样式
  const getStatusClass = (status: string) => {
    const classes: Record<string, string> = {
      running: "bg-green-100 dark:bg-green-900/50 text-green-600 dark:text-green-400",
      idle: "bg-blue-100 dark:bg-blue-900/50 text-blue-600 dark:text-blue-400",
      maintenance: "bg-orange-100 dark:bg-orange-900/50 text-orange-600 dark:text-orange-400",
      fault: "bg-red-100 dark:bg-red-900/50 text-red-600 dark:text-red-400",
      disabled: "bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400",
    };
    return classes[status] || classes.disabled;
  };

  const isAllSelected = paginatedData.length > 0 && selectedIds.length === paginatedData.length;

  return (
    <div className="w-full h-full bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 overflow-y-auto">
      <div className="max-w-7xl mx-auto p-4 md:p-8">
        {/* 页面标题 */}
        <h1 className="text-2xl md:text-3xl font-bold mb-6 text-slate-900 dark:text-white">
          装备管理
        </h1>

        {/* 筛选面板 */}
        <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 shadow-sm mb-4">
          {/* 折叠按钮（小屏幕） */}
          <button
            className="lg:hidden w-full flex items-center justify-between p-4 border-b border-slate-200 dark:border-slate-700"
            onClick={() => setIsFilterExpanded(!isFilterExpanded)}
          >
            <div className="flex items-center gap-2">
              <Filter className="h-4 w-4" />
              <span>筛选条件</span>
            </div>
            {isFilterExpanded ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
          </button>

          {/* 筛选内容 */}
          <div
            className={`p-4 ${isFilterExpanded ? "block" : "hidden lg:block"}`}
          >
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
              {/* 所属子平台 */}
              <div>
                <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                  所属子平台
                </label>
                <select
                  value={filters.subplatform}
                  onChange={(e) => handleFilterChange("subplatform", e.target.value)}
                  className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">全部子平台</option>
                  <option value="polymer">聚合物子平台</option>
                  <option value="fun_alloy">功能合金子平台</option>
                  <option value="energy_storage">储能材料子平台</option>
                </select>
              </div>

              {/* 装备类型 */}
              <div>
                <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                  装备类型
                </label>
                <select
                  value={filters.type}
                  onChange={(e) => handleFilterChange("type", e.target.value)}
                  className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">全部类型</option>
                  <option value="prepare">制备类</option>
                  <option value="characterize">表征类</option>
                  <option value="detect">检测类</option>
                </select>
              </div>

              {/* 运行状态 */}
              <div>
                <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                  运行状态
                </label>
                <select
                  value={filters.status}
                  onChange={(e) => handleFilterChange("status", e.target.value)}
                  className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">全部状态</option>
                  <option value="running">运行中</option>
                  <option value="idle">待机中</option>
                  <option value="maintenance">维护中</option>
                  <option value="fault">故障</option>
                  <option value="disabled">已停用</option>
                </select>
              </div>

              {/* 搜索框 */}
              <div>
                <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                  搜索装备名称/型号
                </label>
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
                  <input
                    type="text"
                    value={filters.search}
                    onChange={(e) => handleFilterChange("search", e.target.value)}
                    placeholder="请输入装备名称或型号"
                    className="w-full pl-10 pr-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              </div>
            </div>

            {/* 操作按钮 */}
            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                onClick={handleResetFilter}
                className="text-slate-600 dark:text-slate-400"
              >
                <X className="h-4 w-4 mr-2" />
                重置
              </Button>
            </div>
          </div>
        </div>

        {/* 批量操作栏 */}
        <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 shadow-sm p-4 mb-4 flex justify-between items-center">
          <div className="flex items-center gap-4">
            <span className="text-sm text-slate-600 dark:text-slate-400">
              已选择 {selectedIds.length} 项
            </span>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => setShowDeleteModal(true)}
              disabled={selectedIds.length === 0}
            >
              <Trash2 className="h-4 w-4 mr-2" />
              批量删除
            </Button>
          </div>
          <Button onClick={handleCreate} className="bg-blue-500 hover:bg-blue-600 dark:bg-blue-600 dark:hover:bg-blue-500 text-white">
            <Plus className="h-4 w-4 mr-2" />
            新建装备
          </Button>
        </div>

        {/* 表格容器 */}
        <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 shadow-sm overflow-hidden relative">
          {isLoading && (
            <div className="absolute inset-0 bg-white/80 dark:bg-slate-900/80 flex items-center justify-center z-10">
              <div className="w-5 h-5 border-2 border-slate-200 border-t-blue-500 rounded-full animate-spin"></div>
            </div>
          )}

          {filteredEquipments.length === 0 ? (
            <div className="p-16 text-center">
              <Search className="h-12 w-12 mx-auto mb-4 text-slate-300 dark:text-slate-600" />
              <p className="text-slate-500 dark:text-slate-400">
                当前筛选条件下无匹配装备，请调整筛选参数
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-slate-50 dark:bg-slate-900/50">
                  <tr>
                    <th className="w-12 px-4 py-3 text-left">
                      <input
                        type="checkbox"
                        checked={isAllSelected}
                        onChange={(e) => handleSelectAll(e.target.checked)}
                        className="w-4 h-4 text-blue-600 rounded focus:ring-blue-500"
                      />
                    </th>
                    <th
                      className="px-4 py-3 text-left text-sm font-medium text-slate-600 dark:text-slate-400 cursor-pointer hover:bg-slate-100 dark:hover:bg-slate-800"
                      onClick={() => handleSort("name")}
                    >
                      装备名称
                      {sortField === "name" && (
                        <span className="ml-1">{sortOrder === "asc" ? "↑" : "↓"}</span>
                      )}
                    </th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-slate-600 dark:text-slate-400">
                      型号
                    </th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-slate-600 dark:text-slate-400">
                      所属子平台
                    </th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-slate-600 dark:text-slate-400">
                      运行状态
                    </th>
                    <th
                      className="px-4 py-3 text-left text-sm font-medium text-slate-600 dark:text-slate-400 cursor-pointer hover:bg-slate-100 dark:hover:bg-slate-800"
                      onClick={() => handleSort("maintenance")}
                    >
                      最近一次维护时间
                      {sortField === "maintenance" && (
                        <span className="ml-1">{sortOrder === "asc" ? "↑" : "↓"}</span>
                      )}
                    </th>
                    <th className="px-4 py-3 text-center text-sm font-medium text-slate-600 dark:text-slate-400">
                      操作
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
                  {paginatedData.map((item) => (
                    <tr
                      key={item.id}
                      className={`hover:bg-slate-50 dark:hover:bg-slate-700/30 transition-colors ${
                        selectedIds.includes(item.id)
                          ? "bg-blue-50 dark:bg-blue-950/30"
                          : ""
                      }`}
                    >
                      <td className="px-4 py-3">
                        <input
                          type="checkbox"
                          checked={selectedIds.includes(item.id)}
                          onChange={(e) => handleRowSelect(item.id, e.target.checked)}
                          className="w-4 h-4 text-blue-600 rounded focus:ring-blue-500"
                        />
                      </td>
                      <td className="px-4 py-3 text-sm text-slate-900 dark:text-slate-50">
                        {item.name}
                      </td>
                      <td className="px-4 py-3 text-sm text-blue-600 dark:text-blue-400">
                        {item.model}
                      </td>
                      <td className="px-4 py-3 text-sm text-slate-600 dark:text-slate-400">
                        {item.subplatformName}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-medium ${getStatusClass(
                            item.status
                          )}`}
                        >
                          {item.statusName}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-sm text-center text-slate-600 dark:text-slate-400">
                        {item.maintenance}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-center gap-2">
                          <button
                            onClick={() => handleEdit(item)}
                            className="p-1.5 text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-950/30 rounded transition-colors"
                            title="编辑"
                          >
                            <Edit className="h-4 w-4" />
                          </button>
                          <button
                            onClick={() => handleDelete(item.id)}
                            className="p-1.5 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30 rounded transition-colors"
                            title="删除"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* 分页控件 */}
        {totalPages > 1 && (
          <div className="flex justify-center items-center gap-2 mt-4">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
              disabled={currentPage === 1}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            {Array.from({ length: totalPages }, (_, i) => i + 1)
              .filter((page) => {
                if (totalPages <= 7) return true;
                if (page === 1 || page === totalPages) return true;
                if (Math.abs(page - currentPage) <= 1) return true;
                return false;
              })
              .map((page, index, array) => {
                if (index > 0 && array[index - 1] !== page - 1) {
                  return (
                    <div key={`ellipsis-${page}`} className="flex items-center gap-1">
                      <span className="px-2 text-slate-400">...</span>
                      <Button
                        variant={currentPage === page ? "default" : "outline"}
                        size="sm"
                        onClick={() => setCurrentPage(page)}
                        className={
                          currentPage === page
                            ? "bg-blue-500 hover:bg-blue-600 text-white"
                            : ""
                        }
                      >
                        {page}
                      </Button>
                    </div>
                  );
                }
                return (
                  <Button
                    key={page}
                    variant={currentPage === page ? "default" : "outline"}
                    size="sm"
                    onClick={() => setCurrentPage(page)}
                    className={
                      currentPage === page
                        ? "bg-blue-500 hover:bg-blue-600 text-white"
                        : ""
                    }
                  >
                    {page}
                  </Button>
                );
              })}
            <Button
              variant="outline"
              size="sm"
              onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
              disabled={currentPage === totalPages}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        )}

        {/* 新建/编辑弹窗 */}
        {showModal && (
          <div
            className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
            onClick={() => setShowModal(false)}
          >
            <div
              className="bg-white dark:bg-slate-800 rounded-lg w-full max-w-2xl max-h-[90vh] overflow-y-auto shadow-xl"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between p-6 border-b border-slate-200 dark:border-slate-700">
                <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
                  {editingId ? "编辑装备" : "新建装备"}
                </h2>
                <button
                  onClick={() => setShowModal(false)}
                  className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <div className="p-6 space-y-4">
                <div>
                  <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                    装备名称 <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    value={formData.name}
                    onChange={(e) =>
                      setFormData({ ...formData, name: e.target.value })
                    }
                    className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                  {formErrors.name && (
                    <p className="mt-1 text-sm text-red-500">{formErrors.name}</p>
                  )}
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                    型号 <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    value={formData.model}
                    onChange={(e) =>
                      setFormData({ ...formData, model: e.target.value })
                    }
                    disabled={!!editingId}
                    className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-slate-100 dark:disabled:bg-slate-800 disabled:text-slate-500"
                  />
                  {formErrors.model && (
                    <p className="mt-1 text-sm text-red-500">{formErrors.model}</p>
                  )}
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                    所属子平台 <span className="text-red-500">*</span>
                  </label>
                  <select
                    value={formData.subplatform}
                    onChange={(e) =>
                      setFormData({ ...formData, subplatform: e.target.value })
                    }
                    className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="">请选择子平台</option>
                    <option value="polymer">聚合物子平台</option>
                    <option value="fun_alloy">功能合金子平台</option>
                    <option value="energy_storage">储能材料子平台</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                    装备类型 <span className="text-red-500">*</span>
                  </label>
                  <select
                    value={formData.type}
                    onChange={(e) =>
                      setFormData({ ...formData, type: e.target.value })
                    }
                    className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="">请选择装备类型</option>
                    <option value="prepare">制备类</option>
                    <option value="characterize">表征类</option>
                    <option value="detect">检测类</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                    运行状态 <span className="text-red-500">*</span>
                  </label>
                  <select
                    value={formData.status}
                    onChange={(e) =>
                      setFormData({ ...formData, status: e.target.value })
                    }
                    className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="running">运行中</option>
                    <option value="idle">待机中</option>
                    <option value="maintenance">维护中</option>
                    <option value="fault">故障</option>
                    <option value="disabled">已停用</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                    最近一次维护时间
                  </label>
                  <input
                    type="date"
                    value={formData.maintenance}
                    onChange={(e) =>
                      setFormData({ ...formData, maintenance: e.target.value })
                    }
                    className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                    购置日期
                  </label>
                  <input
                    type="date"
                    value={formData.purchased}
                    onChange={(e) =>
                      setFormData({ ...formData, purchased: e.target.value })
                    }
                    className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                    负责人
                  </label>
                  <input
                    type="text"
                    value={formData.manager}
                    onChange={(e) =>
                      setFormData({ ...formData, manager: e.target.value })
                    }
                    className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              </div>
              <div className="flex justify-end gap-2 p-6 border-t border-slate-200 dark:border-slate-700">
                <Button variant="outline" onClick={() => setShowModal(false)}>
                  取消
                </Button>
                <Button
                  onClick={handleSubmit}
                  className="bg-blue-500 hover:bg-blue-600 dark:bg-blue-600 dark:hover:bg-blue-500 text-white"
                >
                  确定
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* 删除确认弹窗 */}
        {showDeleteModal && (
          <div
            className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
            onClick={() => setShowDeleteModal(false)}
          >
            <div
              className="bg-white dark:bg-slate-800 rounded-lg w-full max-w-md shadow-xl"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between p-6 border-b border-slate-200 dark:border-slate-700">
                <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
                  确认删除
                </h2>
                <button
                  onClick={() => setShowDeleteModal(false)}
                  className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <div className="p-6">
                <p className="text-slate-600 dark:text-slate-400">
                  删除后不可恢复，是否继续？
                </p>
              </div>
              <div className="flex justify-end gap-2 p-6 border-t border-slate-200 dark:border-slate-700">
                <Button variant="outline" onClick={() => setShowDeleteModal(false)}>
                  取消
                </Button>
                <Button variant="destructive" onClick={handleConfirmDelete}>
                  删除
                </Button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

