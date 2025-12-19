# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


class BreakCondition(BaseModel):
    """循环退出条件"""
    model_config = ConfigDict(populate_by_name=True)
    
    output_variable: str = Field(..., alias="outputVariable")  # 输出变量名（如"score"）
    operator: str  # 比较运算符（">=", "<=", ">", "<", "==", "!="）
    value: Any  # 比较值


class LoopVariableData(BaseModel):
    """循环变量数据"""
    model_config = ConfigDict(populate_by_name=True)
    
    label: str  # 变量标签
    var_type: str = Field(..., alias="varType")  # 变量类型：string, number, object, boolean, array_string, array_number, array_object, array_boolean
    value_type: str = Field(..., alias="valueType")  # 值类型：constant 或 variable
    value: Optional[Any] = None  # 变量值


class WorkflowNodeData(BaseModel):
    """节点数据"""
    model_config = ConfigDict(populate_by_name=True)
    
    label: str
    # Start 节点
    start_inputs: Optional[Dict[str, Any]] = Field(None, alias="startInputs")
    start_input_field: Optional[str] = Field(None, alias="startInputField")
    start_files: Optional[List[str]] = Field(None, alias="startFiles")
    # LLM 节点
    llm_model: Optional[str] = Field(None, alias="llmModel")
    llm_temperature: Optional[float] = Field(None, alias="llmTemperature")
    llm_prompt: Optional[str] = Field(None, alias="llmPrompt")
    llm_system_prompt: Optional[str] = Field(None, alias="llmSystemPrompt")
    llm_resources: Optional[List[Dict[str, Any]]] = Field(None, alias="llmResources")  # 知识库资源
    llm_tools: Optional[List[str]] = Field(None, alias="llmTools")  # 选中的工具名称列表
    # Tool 节点
    tool_name: Optional[str] = Field(None, alias="toolName")
    tool_params: Optional[Dict[str, Any]] = Field(None, alias="toolParams")
    # API 节点
    api_url: Optional[str] = Field(None, alias="apiUrl")
    api_method: Optional[str] = Field(None, alias="apiMethod")
    api_headers: Optional[Dict[str, str]] = Field(None, alias="apiHeaders")
    api_body: Optional[str] = Field(None, alias="apiBody")
    api_key: Optional[str] = Field(None, alias="apiKey")  # API密钥
    # Condition 节点
    condition_expression: Optional[str] = Field(None, alias="conditionExpression")
    # Variable 节点
    variable_name: Optional[str] = Field(None, alias="variableName")
    variable_value: Optional[Any] = Field(None, alias="variableValue")
    # 循环标记：标记节点属于哪个循环（通过 loopId）
    loop_id: Optional[str] = Field(None, alias="loopId")  # 节点所属的循环ID
    # Loop 节点专用字段
    loop_count: Optional[int] = Field(None, alias="loopCount")  # 最大循环次数
    break_conditions: Optional[List[BreakCondition]] = Field(None, alias="breakConditions")  # 退出条件列表
    logical_operator: Optional[str] = Field("and", alias="logicalOperator")  # 逻辑运算符："and" 或 "or"
    start_node_id: Optional[str] = Field(None, alias="startNodeId")  # 循环开始节点ID
    loop_variables: Optional[List[LoopVariableData]] = Field(None, alias="loopVariables")  # 循环变量列表
    # Loop 节点尺寸和位置字段
    loop_width: Optional[int] = Field(None, alias="loopWidth")  # Loop 节点宽度
    loop_height: Optional[int] = Field(None, alias="loopHeight")  # Loop 节点高度
    relative_x: Optional[float] = Field(None, alias="relativeX")  # 节点相对于循环体的 X 位置
    relative_y: Optional[float] = Field(None, alias="relativeY")  # 节点相对于循环体的 Y 位置


class WorkflowNode(BaseModel):
    """工作流节点"""
    id: str
    type: str  # start, end, llm, tool, api, condition, variable, loop
    position: Dict[str, float]  # {x, y}
    data: WorkflowNodeData


class ParameterMapping(BaseModel):
    """参数映射"""
    model_config = ConfigDict(populate_by_name=True)
    
    source_output: Optional[str] = Field(None, alias="sourceOutput")
    target_input: Optional[str] = Field(None, alias="targetInput")


class WorkflowEdge(BaseModel):
    """工作流边/连接"""
    model_config = ConfigDict(populate_by_name=True)
    
    id: str
    source: str
    target: str
    source_handle: Optional[str] = Field(None, alias="sourceHandle")
    target_handle: Optional[str] = Field(None, alias="targetHandle")
    condition: Optional[str] = None  # Condition 节点的条件分支
    parameter_mapping: Optional[ParameterMapping] = Field(None, alias="parameterMapping")  # 参数映射配置


class WorkflowConfigRequest(BaseModel):
    """保存工作流配置请求"""
    model_config = ConfigDict(populate_by_name=True)
    
    id: Optional[str] = None
    name: str
    description: Optional[str] = None
    nodes: List[WorkflowNode]
    edges: List[WorkflowEdge]
    version: Optional[int] = None


class WorkflowConfigResponse(BaseModel):
    """工作流配置响应"""
    model_config = ConfigDict(populate_by_name=True)  # 允许使用字段别名
    
    id: str
    name: str
    description: Optional[str] = None
    nodes: List[WorkflowNode]
    edges: List[WorkflowEdge]
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    version: int
    has_executed: Optional[bool] = False  # 是否已执行
    execution_result: Optional[Dict[str, Any]] = None  # 执行结果（仅在 has_executed=True 时包含）


class WorkflowExecuteRequest(BaseModel):
    """执行工作流请求"""
    model_config = ConfigDict(populate_by_name=True)
    
    workflow_id: str = Field(..., alias="workflowId")
    inputs: Optional[Dict[str, Any]] = None
    files: Optional[List[str]] = None
    thread_id: Optional[str] = Field(None, alias="threadId")


class NodeExecuteRequest(BaseModel):
    """单独执行节点请求"""
    model_config = ConfigDict(populate_by_name=True)
    
    workflow_id: Optional[str] = Field(None, alias="workflowId")
    node_id: str = Field(..., alias="nodeId")
    inputs: Optional[Dict[str, Any]] = None
    # 如果 workflow_id 为空，则使用 node_config 直接执行
    node_config: Optional[Dict[str, Any]] = Field(None, alias="nodeConfig")


class DirectNodeExecuteRequest(BaseModel):
    """直接执行节点请求（不需要工作流 ID）"""
    model_config = ConfigDict(populate_by_name=True)
    
    node_type: str = Field(..., alias="nodeType")
    node_data: Dict[str, Any] = Field(..., alias="nodeData")
    inputs: Optional[Dict[str, Any]] = None


class WorkflowExecuteResponse(BaseModel):
    """工作流执行响应"""
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    execution_time: Optional[float] = None
    node_results: Optional[Dict[str, Any]] = None


class NodeExecuteResponse(BaseModel):
    """节点执行响应"""
    success: bool
    node_id: str
    inputs: Optional[Dict[str, Any]] = None
    outputs: Optional[Any] = None
    error: Optional[str] = None
    execution_time: Optional[float] = None


class ToolDefinition(BaseModel):
    """工具定义"""
    name: str
    description: str
    parameters: List[Dict[str, Any]]


class WorkflowListResponse(BaseModel):
    """工作流列表响应"""
    workflows: List[Dict[str, Any]]

