"use client";

import { useState, useEffect } from "react";
import { Plus, Save, TestTube, Upload, CheckCircle2, XCircle, Search, Edit, Trash2 } from "lucide-react";
import { Button } from "~/components/ui/button";

interface Equipment {
  id: string;
  name: string;
  model: string;
  manufacturer: string;
  subplatform: string;
  subplatformName: string;
  location: string;
  protocol: string;
  protocolName: string;
  ipAddress: string;
  port: string;
  whitelist: string;
  permissions: string[];
  connectionStatus: "connected" | "disconnected" | "testing";
  responseTime: number | null;
}

const mockEquipments: Equipment[] = [
  {
    id: "EQ001",
    name: "高精度搅拌装机",
    model: "HMS-700-B2",
    manufacturer: "精密仪器公司",
    subplatform: "polymer",
    subplatformName: "聚合物",
    location: "实验室A区，机位3",
    protocol: "modbus",
    protocolName: "Modbus TCP",
    ipAddress: "192.168.1.100",
    port: "502",
    whitelist: "192.168.10.2,192.168.10.3",
    permissions: ["管理员组", "研发团队"],
    connectionStatus: "connected",
    responseTime: 165,
  },
  {
    id: "EQ002",
    name: "高温熔炼炉",
    model: "HTF-2000-G",
    manufacturer: "高温设备制造",
    subplatform: "alloy",
    subplatformName: "功能合金",
    location: "实验室B区，机位1",
    protocol: "opcua",
    protocolName: "OPC UA",
    ipAddress: "192.168.1.101",
    port: "4840",
    whitelist: "192.168.10.2",
    permissions: ["管理员组", "操作员组"],
    connectionStatus: "connected",
    responseTime: 120,
  },
  {
    id: "EQ003",
    name: "电化学工作站",
    model: "ECW-9000-P",
    manufacturer: "电化学科技",
    subplatform: "storage",
    subplatformName: "储能材料",
    location: "实验室C区，机位2",
    protocol: "mqtt",
    protocolName: "MQTT",
    ipAddress: "192.168.1.102",
    port: "1883",
    whitelist: "192.168.10.2,192.168.10.3,192.168.10.4",
    permissions: ["管理员组", "研发团队", "运维部门"],
    connectionStatus: "disconnected",
    responseTime: null,
  },
];

export function EquipmentAccess() {
  const [equipments, setEquipments] = useState<Equipment[]>(mockEquipments);
  const [filteredEquipments, setFilteredEquipments] = useState<Equipment[]>(mockEquipments);
  const [selectedEquipment, setSelectedEquipment] = useState<Equipment | null>(null);
  const [isNewMode, setIsNewMode] = useState(false);
  const [filters, setFilters] = useState({
    name: "",
    subplatform: "",
    protocol: "",
    connectionStatus: "",
  });

  const [formData, setFormData] = useState({
    name: "",
    model: "",
    manufacturer: "",
    subplatform: "",
    location: "",
    protocol: "",
    ipAddress: "",
    port: "",
    whitelist: "",
    permissions: [] as string[],
  });

  const [connectionStatus, setConnectionStatus] = useState<{
    connected: boolean;
    responseTime: number | null;
  }>({
    connected: false,
    responseTime: null,
  });

  const [isTesting, setIsTesting] = useState(false);

  // 应用筛选
  useEffect(() => {
    let filtered = [...equipments];

    if (filters.name) {
      filtered = filtered.filter((eq) =>
        eq.name.toLowerCase().includes(filters.name.toLowerCase()) ||
        eq.model.toLowerCase().includes(filters.name.toLowerCase())
      );
    }
    if (filters.subplatform) {
      filtered = filtered.filter((eq) => eq.subplatform === filters.subplatform);
    }
    if (filters.protocol) {
      filtered = filtered.filter((eq) => eq.protocol === filters.protocol);
    }
    if (filters.connectionStatus) {
      filtered = filtered.filter((eq) => eq.connectionStatus === filters.connectionStatus);
    }

    setFilteredEquipments(filtered);
  }, [filters, equipments]);

  // 选择装备时加载数据到表单
  useEffect(() => {
    if (selectedEquipment) {
      setFormData({
        name: selectedEquipment.name,
        model: selectedEquipment.model,
        manufacturer: selectedEquipment.manufacturer,
        subplatform: selectedEquipment.subplatform,
        location: selectedEquipment.location,
        protocol: selectedEquipment.protocol,
        ipAddress: selectedEquipment.ipAddress,
        port: selectedEquipment.port,
        whitelist: selectedEquipment.whitelist,
        permissions: [...selectedEquipment.permissions],
      });
      setConnectionStatus({
        connected: selectedEquipment.connectionStatus === "connected",
        responseTime: selectedEquipment.responseTime,
      });
      setIsNewMode(false);
    }
  }, [selectedEquipment]);

  const handleFilterChange = (key: string, value: string) => {
    setFilters({ ...filters, [key]: value });
  };

  const handleInputChange = (field: string, value: string) => {
    setFormData({ ...formData, [field]: value });
  };

  const handlePermissionChange = (permission: string, checked: boolean) => {
    if (checked) {
      setFormData({
        ...formData,
        permissions: [...formData.permissions, permission],
      });
    } else {
      setFormData({
        ...formData,
        permissions: formData.permissions.filter((p) => p !== permission),
      });
    }
  };

  const handleCreateNew = () => {
    setSelectedEquipment(null);
    setIsNewMode(true);
    setFormData({
      name: "",
      model: "",
      manufacturer: "",
      subplatform: "",
      location: "",
      protocol: "",
      ipAddress: "",
      port: "",
      whitelist: "",
      permissions: [],
    });
    setConnectionStatus({
      connected: false,
      responseTime: null,
    });
  };

  const handleTestConnection = async () => {
    setIsTesting(true);
    // 模拟连接测试
    setTimeout(() => {
      const connected = Math.random() > 0.3; // 70% 成功率
      setConnectionStatus({
        connected,
        responseTime: connected ? Math.floor(Math.random() * 200) + 50 : null,
      });
      setIsTesting(false);
    }, 1500);
  };

  const handleSave = () => {
    if (isNewMode) {
      // 新建装备
      const newId = `EQ${String(equipments.length + 1).padStart(3, "0")}`;
      const subplatformNames: Record<string, string> = {
        polymer: "聚合物",
        alloy: "功能合金",
        storage: "储能材料",
      };
      const protocolNames: Record<string, string> = {
        modbus: "Modbus TCP",
        opcua: "OPC UA",
        mqtt: "MQTT",
      };

      const newEquipment: Equipment = {
        id: newId,
        name: formData.name,
        model: formData.model,
        manufacturer: formData.manufacturer,
        subplatform: formData.subplatform,
        subplatformName: subplatformNames[formData.subplatform] || formData.subplatform,
        location: formData.location,
        protocol: formData.protocol,
        protocolName: protocolNames[formData.protocol] || formData.protocol,
        ipAddress: formData.ipAddress,
        port: formData.port,
        whitelist: formData.whitelist,
        permissions: formData.permissions,
        connectionStatus: connectionStatus.connected ? "connected" : "disconnected",
        responseTime: connectionStatus.responseTime,
      };

      setEquipments([...equipments, newEquipment]);
      setSelectedEquipment(newEquipment);
    } else if (selectedEquipment) {
      // 更新装备
      const subplatformNames: Record<string, string> = {
        polymer: "聚合物",
        alloy: "功能合金",
        storage: "储能材料",
      };
      const protocolNames: Record<string, string> = {
        modbus: "Modbus TCP",
        opcua: "OPC UA",
        mqtt: "MQTT",
      };

      const updatedEquipment: Equipment = {
        ...selectedEquipment,
        name: formData.name,
        model: formData.model,
        manufacturer: formData.manufacturer,
        subplatform: formData.subplatform,
        subplatformName: subplatformNames[formData.subplatform] || formData.subplatform,
        location: formData.location,
        protocol: formData.protocol,
        protocolName: protocolNames[formData.protocol] || formData.protocol,
        ipAddress: formData.ipAddress,
        port: formData.port,
        whitelist: formData.whitelist,
        permissions: formData.permissions,
        connectionStatus: connectionStatus.connected ? "connected" : "disconnected",
        responseTime: connectionStatus.responseTime,
      };

      setEquipments(
        equipments.map((eq) => (eq.id === selectedEquipment.id ? updatedEquipment : eq))
      );
      setSelectedEquipment(updatedEquipment);
    }
    setIsNewMode(false);
  };

  const handleDelete = (id: string) => {
    if (confirm("确定要删除此装备吗？")) {
      setEquipments(equipments.filter((eq) => eq.id !== id));
      if (selectedEquipment?.id === id) {
        setSelectedEquipment(null);
        setIsNewMode(false);
      }
    }
  };

  const getConnectionStatusClass = (status: string) => {
    const classes: Record<string, string> = {
      connected: "bg-green-100 dark:bg-green-900/50 text-green-600 dark:text-green-400",
      disconnected: "bg-red-100 dark:bg-red-900/50 text-red-600 dark:text-red-400",
      testing: "bg-yellow-100 dark:bg-yellow-900/50 text-yellow-600 dark:text-yellow-400",
    };
    return classes[status] || classes.disconnected;
  };

  const getConnectionStatusText = (status: string) => {
    const texts: Record<string, string> = {
      connected: "已连接",
      disconnected: "未连接",
      testing: "测试中",
    };
    return texts[status] || status;
  };

  const permissionOptions = ["管理员组", "研发团队", "操作员组", "运维部门"];

  return (
    <div className="w-full h-full bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 overflow-y-auto">
      <div className="max-w-7xl mx-auto p-4 md:p-8">
        {/* 页面标题 */}
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl md:text-3xl font-bold text-slate-900 dark:text-white">
            装备接入配置
          </h1>
          <Button
            onClick={handleCreateNew}
            className="bg-blue-500 hover:bg-blue-600 dark:bg-blue-600 dark:hover:bg-blue-500 text-white"
          >
            <Plus className="h-4 w-4 mr-2" />
            新建装备
          </Button>
        </div>

        {/* 筛选面板 */}
        <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 shadow-sm p-4 mb-4">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                装备名称/型号
              </label>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
                <input
                  type="text"
                  value={filters.name}
                  onChange={(e) => handleFilterChange("name", e.target.value)}
                  placeholder="请输入装备名称或型号"
                  className="w-full pl-10 pr-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>
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
                <option value="polymer">聚合物</option>
                <option value="alloy">功能合金</option>
                <option value="storage">储能材料</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                通信协议
              </label>
              <select
                value={filters.protocol}
                onChange={(e) => handleFilterChange("protocol", e.target.value)}
                className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">全部协议</option>
                <option value="modbus">Modbus TCP</option>
                <option value="opcua">OPC UA</option>
                <option value="mqtt">MQTT</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                连接状态
              </label>
              <select
                value={filters.connectionStatus}
                onChange={(e) => handleFilterChange("connectionStatus", e.target.value)}
                className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">全部状态</option>
                <option value="connected">已连接</option>
                <option value="disconnected">未连接</option>
              </select>
            </div>
          </div>
        </div>

        {/* 装备列表和配置面板 */}
        <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 shadow-sm overflow-hidden">
          <div className="flex h-[calc(100vh-300px)] min-h-[600px]">
            {/* 装备列表 */}
            <div className="w-2/5 border-r border-slate-200 dark:border-slate-700 overflow-y-auto">
              <table className="w-full">
                <thead className="bg-slate-50 dark:bg-slate-900/50 sticky top-0">
                  <tr>
                    <th className="px-4 py-3 text-left text-sm font-medium text-slate-600 dark:text-slate-400">
                      装备名称
                    </th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-slate-600 dark:text-slate-400">
                      型号
                    </th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-slate-600 dark:text-slate-400">
                      状态
                    </th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-slate-600 dark:text-slate-400">
                      操作
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
                  {filteredEquipments.map((equipment) => (
                    <tr
                      key={equipment.id}
                      onClick={() => setSelectedEquipment(equipment)}
                      className={`cursor-pointer transition-colors ${
                        selectedEquipment?.id === equipment.id
                          ? "bg-blue-50 dark:bg-blue-950/30"
                          : "hover:bg-slate-50 dark:hover:bg-slate-700/30"
                      }`}
                    >
                      <td className="px-4 py-3 text-sm text-slate-900 dark:text-slate-50">
                        {equipment.name}
                      </td>
                      <td className="px-4 py-3 text-sm text-slate-600 dark:text-slate-400">
                        {equipment.model}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-medium ${getConnectionStatusClass(
                            equipment.connectionStatus
                          )}`}
                        >
                          {getConnectionStatusText(equipment.connectionStatus)}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex gap-2">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedEquipment(equipment);
                            }}
                            className="text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300"
                            title="编辑"
                          >
                            <Edit className="h-4 w-4" />
                          </button>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDelete(equipment.id);
                            }}
                            className="text-red-600 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300"
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

            {/* 配置面板 */}
            <div className="w-3/5 overflow-y-auto p-6 bg-slate-50 dark:bg-slate-900/50">
              {selectedEquipment || isNewMode ? (
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
                          d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
                        />
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                        />
                      </svg>
                      {isNewMode ? "新建装备配置" : `编辑装备配置 - ${selectedEquipment?.name}`}
                    </h2>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {/* 装备名称 */}
                    <div>
                      <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                        装备名称 <span className="text-red-500">*</span>
                      </label>
                      <input
                        type="text"
                        value={formData.name}
                        onChange={(e) => handleInputChange("name", e.target.value)}
                        placeholder="请输入装备名称"
                        className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>

                    {/* 型号 */}
                    <div>
                      <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                        型号 <span className="text-red-500">*</span>
                      </label>
                      <input
                        type="text"
                        value={formData.model}
                        onChange={(e) => handleInputChange("model", e.target.value)}
                        placeholder="请输入型号"
                        className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>

                    {/* 厂商 */}
                    <div>
                      <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                        厂商
                      </label>
                      <input
                        type="text"
                        value={formData.manufacturer}
                        onChange={(e) => handleInputChange("manufacturer", e.target.value)}
                        placeholder="请输入厂商"
                        className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>

                    {/* 所属子平台 */}
                    <div>
                      <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                        所属子平台 <span className="text-red-500">*</span>
                      </label>
                      <select
                        value={formData.subplatform}
                        onChange={(e) => handleInputChange("subplatform", e.target.value)}
                        className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                      >
                        <option value="">请选择子平台</option>
                        <option value="polymer">聚合物</option>
                        <option value="alloy">功能合金</option>
                        <option value="storage">储能材料</option>
                      </select>
                    </div>

                    {/* 安装位置 */}
                    <div>
                      <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                        安装位置
                      </label>
                      <input
                        type="text"
                        value={formData.location}
                        onChange={(e) => handleInputChange("location", e.target.value)}
                        placeholder="实验室A区，机位3"
                        className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>

                    {/* 通信协议 */}
                    <div>
                      <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                        通信协议 <span className="text-red-500">*</span>
                      </label>
                      <select
                        value={formData.protocol}
                        onChange={(e) => handleInputChange("protocol", e.target.value)}
                        className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                      >
                        <option value="">请选择协议</option>
                        <option value="modbus">Modbus TCP</option>
                        <option value="opcua">OPC UA</option>
                        <option value="mqtt">MQTT</option>
                      </select>
                    </div>

                    {/* 协议配置项 */}
                    <div className="md:col-span-2 bg-white dark:bg-slate-800 p-4 rounded-lg border border-slate-200 dark:border-slate-700">
                      <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-3">
                        协议配置项
                      </label>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div>
                          <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">
                            IP地址
                          </label>
                          <input
                            type="text"
                            value={formData.ipAddress}
                            onChange={(e) => handleInputChange("ipAddress", e.target.value)}
                            placeholder="192.168.xxx.xxx"
                            className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                          />
                        </div>
                        <div>
                          <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">
                            端口号
                          </label>
                          <input
                            type="text"
                            value={formData.port}
                            onChange={(e) => handleInputChange("port", e.target.value)}
                            placeholder="502"
                            className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                          />
                        </div>
                      </div>
                    </div>

                    {/* 访问白名单 */}
                    <div className="md:col-span-2">
                      <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                        访问白名单
                      </label>
                      <input
                        type="text"
                        value={formData.whitelist}
                        onChange={(e) => handleInputChange("whitelist", e.target.value)}
                        placeholder="192.168.10.2,192.168.10.3"
                        className="w-full px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                        多个IP地址请用逗号分隔
                      </p>
                    </div>

                    {/* 操作权限分配 */}
                    <div className="md:col-span-2">
                      <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">
                        操作权限分配
                      </label>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                        {permissionOptions.map((permission) => (
                          <label
                            key={permission}
                            className="flex items-center gap-2 cursor-pointer p-2 rounded border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800"
                          >
                            <input
                              type="checkbox"
                              checked={formData.permissions.includes(permission)}
                              onChange={(e) =>
                                handlePermissionChange(permission, e.target.checked)
                              }
                              className="w-4 h-4 text-blue-600 rounded focus:ring-blue-500"
                            />
                            <span className="text-sm text-slate-700 dark:text-slate-300">
                              {permission}
                            </span>
                          </label>
                        ))}
                      </div>
                    </div>
                  </div>

                  {/* 连接状态 */}
                  <div className="text-center">
                    {connectionStatus.connected ? (
                      <div className="flex items-center justify-center gap-2 text-green-600 dark:text-green-400 font-medium">
                        <CheckCircle2 className="h-5 w-5" />
                        <span>
                          连接测试成功 - 响应时间: {connectionStatus.responseTime}ms
                        </span>
                      </div>
                    ) : connectionStatus.responseTime !== null ? (
                      <div className="flex items-center justify-center gap-2 text-red-600 dark:text-red-400 font-medium">
                        <XCircle className="h-5 w-5" />
                        <span>连接测试失败</span>
                      </div>
                    ) : (
                      <div className="text-slate-400 dark:text-slate-500 text-sm">
                        点击"连接测试"按钮测试连接
                      </div>
                    )}
                  </div>

                  {/* 操作按钮 */}
                  <div className="flex justify-center gap-3">
                    <Button
                      variant="outline"
                      onClick={handleTestConnection}
                      disabled={isTesting}
                    >
                      <TestTube className="h-4 w-4 mr-2" />
                      {isTesting ? "测试中..." : "连接测试"}
                    </Button>
                    <Button
                      onClick={handleSave}
                      className="bg-blue-500 hover:bg-blue-600 dark:bg-blue-600 dark:hover:bg-blue-500 text-white"
                    >
                      <Save className="h-4 w-4 mr-2" />
                      保存并生效
                    </Button>
                    <Button variant="outline">
                      <Upload className="h-4 w-4 mr-2" />
                      导入配置模板
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="flex items-center justify-center h-full text-slate-500 dark:text-slate-400">
                  请选择一个装备进行配置，或点击"新建装备"创建新装备
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
