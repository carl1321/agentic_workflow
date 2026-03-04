"use client";

import { ArrowLeft, Play, Loader2, CheckCircle2, AlertCircle, Download, Upload, X, FileText, ChevronRight, History, Trash2 } from "lucide-react";
import { useState, useRef, useEffect } from "react";
import { cn } from "~/lib/utils";
import type { ToolConfig, ToolParameter } from "~/core/config/tools";
import { Button } from "~/components/ui/button";
import { executeTool } from "~/core/api/tools";
import { Markdown } from "~/components/ui/markdown";
import { useConfig } from "~/core/api/hooks";
import type { ModelInfo } from "~/core/config/types";
import {
  saveExtractionRecord,
  getExtractionRecords,
  getExtractionRecord,
  deleteExtractionRecord,
  type DataExtractionRecord,
  type DataExtractionRecordRequest,
} from "~/core/api/data-extraction";
import {
  saveToolRunHistory,
  getToolRunHistoryList,
  deleteToolRunRecord,
  type ToolRunHistoryRecord,
} from "~/core/api/tool-history";
import { toast } from "sonner";

interface ToolExecutorProps {
  tool: ToolConfig;
  onClose: () => void;
  onBack?: () => void;
  onExecute?: (toolId: string, params: Record<string, unknown>) => Promise<string>;
}

export function ToolExecutor({ tool, onClose, onBack, onExecute }: ToolExecutorProps) {
  const { config } = useConfig();
  const [params, setParams] = useState<Record<string, unknown>>(() => {
    const initial: Record<string, unknown> = {};
    tool.parameters.forEach((param) => {
      if (param.default !== undefined) {
        initial[param.name] = param.default;
      }
    });
    return initial;
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  
  // Material extraction specific states
  const [extractionType, setExtractionType] = useState<string>("prompt_extraction");
  const [extractionStep, setExtractionStep] = useState<number>(1); // 1: 类别提取+选择, 2: 数据抽取, 3: 结果展示
  const [extractionProgress, setExtractionProgress] = useState<number>(0);
  const [categories, setCategories] = useState<{
    materials: string[];
    processes: string[];
    properties: string[];
  } | null>(null);
  const [selectedCategories, setSelectedCategories] = useState<{
    materials: string[]; // 单选，只包含一个元素
    processes: string[];
    properties: string[];
  }>({
    materials: [],
    processes: [],
    properties: [],
  });
  const [tableData, setTableData] = useState<Array<{
    material: string;
    process: string;
    property: string;
  }>>([]);
  
  // History records states
  const [historyRecords, setHistoryRecords] = useState<DataExtractionRecord[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [currentRecordId, setCurrentRecordId] = useState<string | null>(null); // Deprecated, use currentTaskId
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(false);

  // PPT generator: step 1=输入主题, 2=确认大纲, 3=下载
  const [pptStep, setPptStep] = useState<1 | 2 | 3>(1);
  const [outlineContent, setOutlineContent] = useState<string>("");
  const [pptDownloadUrl, setPptDownloadUrl] = useState<string | null>(null);
  const [pptPdfDownloadUrl, setPptPdfDownloadUrl] = useState<string | null>(null);
  const [pptSlidesPreviewUrls, setPptSlidesPreviewUrls] = useState<string[]>([]);

  // 文生图 / PPT 生成 历史记录（与 data_extraction 的 historyRecords 分开）
  const [toolHistoryRecords, setToolHistoryRecords] = useState<ToolRunHistoryRecord[]>([]);
  const [showToolHistory, setShowToolHistory] = useState(false);
  const [loadingToolHistory, setLoadingToolHistory] = useState(false);
  
  // Initialize extraction type from params
  useEffect(() => {
    if (tool.id === "data_extraction") {
      const type = (params["extraction_type"] as string) || "prompt_extraction";
      // Only update if type actually changed
      if (extractionType !== type) {
        setExtractionType(type);
        if (type === "material_extraction") {
          // 只在初始化时设置 step 1，如果已经有 step 2 或 step 3 的数据，不要重置
          const currentStep = extractionStep || (params["extraction_step"] as number);
          if (!currentStep || currentStep === 1) {
            setParams((prev) => ({
              ...prev,
              extraction_type: "material_extraction",
              extraction_step: 1,
            }));
          }
        }
      }
    }
  }, [tool.id, params["extraction_type"], extractionType, extractionStep]);

  // Auto-advance to step 3 when step 2 execution completes
  useEffect(() => {
    if (
      tool.id === "data_extraction" &&
      extractionType === "material_extraction" &&
      extractionStep === 2 &&
      !executing && // Execution just completed
      result && // We have a result
      tableData.length >= 0 // tableData has been set (even if empty)
    ) {
      // Check if result contains step 2 data
      try {
        const resultJson = JSON.parse(result);
        if (resultJson.step === 2) {
          // Step 2 just completed, advance to step 3
          console.log("[Data Extraction] Auto-advancing to step 3, tableData length:", tableData.length);
          setExtractionStep(3);
          setParams((prev) => ({
            ...prev,
            extraction_step: 3,
          }));
        }
      } catch (e) {
        // Not JSON, ignore
      }
    }
  }, [tool.id, extractionType, extractionStep, tableData, executing, result]);

  // Get available models from config
  const availableModels: ModelInfo[] = [];
  if (config?.models) {
    Object.values(config.models).forEach((modelList) => {
      if (Array.isArray(modelList)) {
        modelList.forEach((model) => {
          if (typeof model === "object" && model !== null && "name" in model) {
            availableModels.push(model as ModelInfo);
          }
        });
      }
    });
  }

  const validateParams = (): boolean => {
    const newErrors: Record<string, string> = {};
    
    // Special validation for data_extraction
    if (tool.id === "data_extraction") {
      const currentType = (params["extraction_type"] as string) || extractionType || "prompt_extraction";
      
      // Only validate file for prompt extraction mode
      // For material extraction, file is handled by file upload UI
      if (currentType === "prompt_extraction") {
        if (!uploadedFile) {
          newErrors["pdf_file"] = "请上传PDF/XML文件";
        }
        // For prompt extraction, require extraction_prompt and json_schema
        if (!params["extraction_prompt"] || (params["extraction_prompt"] as string).trim() === "") {
          newErrors["extraction_prompt"] = "提示词抽取模式需要填写抽取提示词";
        }
        if (!params["json_schema"] || (params["json_schema"] as string).trim() === "") {
          newErrors["json_schema"] = "提示词抽取模式需要填写JSON格式定义";
        }
      } else if (currentType === "material_extraction") {
        // For material extraction, validate file only if no file uploaded
        if (!uploadedFile) {
          newErrors["pdf_file"] = "请上传PDF/XML文件";
        }
        
        const step = extractionStep || (params["extraction_step"] as number) || 1;
        if (step === 2) {
          // Step 2: material is required (single selection), and at least one process or property
          if (selectedCategories.materials.length === 0) {
            newErrors["materials"] = "必须选择一个材料类别";
          }
          if (selectedCategories.processes.length === 0 && selectedCategories.properties.length === 0) {
            newErrors["categories"] = "必须至少选择一个工艺类别或性能类别";
          }
        }
      }
    } else {
      // For other tools, use standard validation
    tool.parameters.forEach((param) => {
      if (param.required && (params[param.name] === undefined || params[param.name] === "")) {
        newErrors[param.name] = `${param.name} 是必填项`;
      }
    });
    }
    
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    // Validate file type
    const fileName = file.name.toLowerCase();
    const isValidFile = 
      (file.type === "application/pdf" || fileName.endsWith(".pdf")) ||
      (file.type === "application/xml" || file.type === "text/xml" || fileName.endsWith(".xml"));
    
    if (!isValidFile) {
      setError("请上传PDF或XML文件");
      return;
    }

    // Validate file size (max 50MB)
    if (file.size > 50 * 1024 * 1024) {
      setError("文件大小不能超过50MB");
      return;
    }

    setUploadedFile(file);
    setError(null);
    // Clear pdf_file error when file is uploaded
    setErrors((prev) => {
      const newErrors = { ...prev };
      delete newErrors["pdf_file"];
      return newErrors;
    });
    
    // Reset material extraction state when new file is uploaded
    if (tool.id === "data_extraction" && extractionType === "material_extraction") {
      setCategories(null);
      setSelectedCategories({ materials: [], processes: [], properties: [] });
      setTableData([]);
      setExtractionStep(1);
      setExtractionProgress(0);
      setParams((prev) => ({
        ...prev,
        extraction_type: "material_extraction",
        extraction_step: 1,
      }));
      
      // Auto-save file information (Step 1) to generate task_id
      // This ensures task_id is available for subsequent steps
      // Convert file to base64 first, then save directly (avoid state update timing issues)
      try {
        console.log("[File Upload] Converting file to base64 and auto-saving file information (Step 1)...");
        const fileBase64 = await fileToBase64(file);
        const savedRecord = await autoSaveRecord(1, undefined, undefined, undefined, undefined, undefined, file, fileBase64);
        if (savedRecord && savedRecord.task_id) {
          setCurrentTaskId(savedRecord.task_id);
          setCurrentRecordId(savedRecord.id); // Keep for backward compatibility
          console.log("[File Upload] ✅ File information saved, task_id:", savedRecord.task_id);
          toast.success("文件已上传并自动保存任务记录");
        } else {
          console.error("[File Upload] ❌ Failed to save file info, no task_id returned.");
          toast.error("文件上传成功但保存任务记录失败");
        }
      } catch (error) {
        console.error("[File Upload] ❌ Error during auto-save after file upload:", error);
        toast.error("文件上传成功但保存任务记录失败");
      }
    }
  };

  const handleRemoveFile = () => {
    setUploadedFile(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const fileToBase64 = (file: File): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = reader.result as string;
        // Remove data URL prefix (data:application/pdf;base64,)
        const base64 = result.split(",")[1] || result;
        resolve(base64);
      };
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  };

  // Load history records
  const loadHistoryRecords = async () => {
    if (tool.id !== "data_extraction" || extractionType !== "material_extraction") {
      return;
    }
    
    try {
      setLoadingHistory(true);
      const response = await getExtractionRecords(50, 0, "material_extraction");
      setHistoryRecords(response.records);
    } catch (error) {
      console.error("Failed to load history records:", error);
      toast.error("加载历史记录失败");
    } finally {
      setLoadingHistory(false);
    }
  };

  // 文生图 / PPT 生成：加载历史列表
  const loadToolHistoryRecords = async () => {
    if (tool.id !== "image_gen" && tool.id !== "ppt_generator") return;
    try {
      setLoadingToolHistory(true);
      const res = await getToolRunHistoryList(tool.id, 50, 0);
      setToolHistoryRecords(res.records || []);
    } catch (e) {
      console.error("Failed to load tool history:", e);
      toast.error("加载历史记录失败");
    } finally {
      setLoadingToolHistory(false);
    }
  };

  // 从历史记录恢复：文生图 或 PPT
  const restoreFromToolRecord = (record: ToolRunHistoryRecord) => {
    if (tool.id === "image_gen") {
      setResult(record.result_json ?? null);
      setError(null);
      setShowToolHistory(false);
      return;
    }
    if (tool.id === "ppt_generator" && record.result_json) {
      try {
        const data = JSON.parse(record.result_json) as {
          outline?: string;
          pptx_download_url?: string;
          pdf_download_url?: string;
          slides_preview_urls?: string[];
          download_url?: string;
        };
        if (data.outline !== undefined) setOutlineContent(data.outline);
        setPptDownloadUrl(
          data.pptx_download_url
            ? (data.pptx_download_url.startsWith("/") ? data.pptx_download_url : `/${data.pptx_download_url}`)
            : data.download_url
            ? (data.download_url.startsWith("/") ? data.download_url : `/${data.download_url}`)
            : null
        );
        setPptPdfDownloadUrl(
          data.pdf_download_url
            ? (data.pdf_download_url.startsWith("/") ? data.pdf_download_url : `/${data.pdf_download_url}`)
            : null
        );
        setPptSlidesPreviewUrls((data.slides_preview_urls || []).map((u) => (u.startsWith("/") ? u : `/${u}`)));
        setPptStep(3);
        setResult(record.result_json);
        setError(null);
        setShowToolHistory(false);
      } catch {
        toast.error("历史记录格式无效");
      }
    }
  };

  const handleDeleteToolRecord = async (recordId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await deleteToolRunRecord(recordId);
      toast.success("已删除");
      loadToolHistoryRecords();
    } catch {
      toast.error("删除失败");
    }
  };

  // Auto-save extraction record
  const autoSaveRecord = async (
    step: number,
    recordId?: string,
    categoriesData?: { materials: string[]; processes: string[]; properties: string[] } | null,
    tableDataArray?: Array<{ material: string; process: string; property: string }>,
    resultJsonText?: string,
    selectedCategoriesData?: { materials: string[]; processes: string[]; properties: string[] } | null,
    fileObject?: File | null,
    fileBase64String?: string | null
  ) => {
    if (tool.id !== "data_extraction" || extractionType !== "material_extraction") {
      return;
    }

    try {
      // Use provided file object or fall back to state
      const fileToUse = fileObject || uploadedFile;
      // Use provided base64 or convert from file
      const fileBase64 = fileBase64String !== undefined 
        ? (fileBase64String || undefined)
        : (fileToUse ? await fileToBase64(fileToUse) : undefined);
      const taskName = recordId 
        ? undefined 
        : `${fileToUse?.name || "未命名任务"}_${new Date().toLocaleString("zh-CN")}`;

      // Use passed data if available, otherwise fall back to state
      const categoriesToSave = categoriesData !== undefined ? categoriesData : categories;
      const tableDataToSave = tableDataArray !== undefined ? tableDataArray : tableData;
      const resultToSave = resultJsonText !== undefined ? resultJsonText : result;

      // CRITICAL: If we're saving selected_categories, we MUST have categories to validate against
      // If categoriesToSave is not available, try to load from database first
      if (step >= 3 && !categoriesToSave && (selectedCategoriesData || selectedCategories)) {
        console.warn("[Auto Save] ⚠️ No categories available for validation! Attempting to load from database...");
        const taskIdToUse = recordId || currentTaskId || currentRecordId;
        if (taskIdToUse) {
          try {
            const existingRecord = await getExtractionRecord(taskIdToUse);
            if (existingRecord?.categories) {
              console.log("[Auto Save] ✅ Loaded categories from database for validation:", {
                materials: existingRecord.categories.materials?.length || 0,
                processes: existingRecord.categories.processes?.length || 0,
                properties: existingRecord.categories.properties?.length || 0,
              });
              // Use loaded categories for validation
              const categoriesToUse = existingRecord.categories;
              // Re-validate selected categories against loaded categories
              const selectedCategoriesToValidate = selectedCategoriesData !== undefined 
                ? selectedCategoriesData 
                : selectedCategories;
              
              if (selectedCategoriesToValidate) {
                const strictlyValidated = {
                  materials: (selectedCategoriesToValidate.materials || []).filter(cat => 
                    categoriesToUse.materials?.includes(cat)
                  ),
                  processes: (selectedCategoriesToValidate.processes || []).filter(cat => 
                    categoriesToUse.processes?.includes(cat)
                  ),
                  properties: (selectedCategoriesToValidate.properties || []).filter(cat => 
                    categoriesToUse.properties?.includes(cat)
                  ),
                };
                
                // Log if any categories were filtered out
                if (strictlyValidated.materials.length !== (selectedCategoriesToValidate.materials?.length || 0) ||
                    strictlyValidated.processes.length !== (selectedCategoriesToValidate.processes?.length || 0) ||
                    strictlyValidated.properties.length !== (selectedCategoriesToValidate.properties?.length || 0)) {
                  console.error("[Auto Save] ❌ Selected categories do not match categories table! Filtered out:", {
                    original: selectedCategoriesToValidate,
                    validated: strictlyValidated,
                    available: categoriesToUse,
                  });
                }
                
                // Continue with validation using loaded categories
                // We'll use categoriesToUse for the rest of the function
                // But we need to update categoriesToSave
                const updatedCategoriesToSave = categoriesToUse;
                // Continue with the rest of the function using updatedCategoriesToSave
              }
            }
          } catch (error) {
            console.error("[Auto Save] Failed to load categories from database:", error);
          }
        }
      }

      // Determine selected_categories to save
      // Use passed selectedCategoriesData if provided, otherwise use state
      const selectedCategoriesToValidate = selectedCategoriesData !== undefined 
        ? selectedCategoriesData 
        : selectedCategories;

      // Determine data source for logging
      const categoriesSource = categoriesData !== undefined ? "parameter" : "state";
      const tableDataSource = tableDataArray !== undefined ? "parameter" : "state";
      const selectedCategoriesSource = selectedCategoriesData !== undefined ? "parameter" : "state";

      console.log("[Auto Save] 💾 Saving record - Data sources and summary:", {
        step,
        recordId: recordId || currentRecordId || "NEW",
        dataSources: {
          categories: categoriesSource,
          tableData: tableDataSource,
          selectedCategories: selectedCategoriesSource,
        },
        categories: {
          has: !!categoriesToSave,
          count: categoriesToSave ? {
            materials: categoriesToSave.materials?.length || 0,
            processes: categoriesToSave.processes?.length || 0,
            properties: categoriesToSave.properties?.length || 0,
          } : null,
        },
        selectedCategories: {
          has: !!selectedCategoriesToValidate,
          fromState: selectedCategoriesSource === "state",
          fromParameter: selectedCategoriesSource === "parameter",
          count: selectedCategoriesToValidate ? {
            materials: selectedCategoriesToValidate.materials?.length || 0,
            processes: selectedCategoriesToValidate.processes?.length || 0,
            properties: selectedCategoriesToValidate.properties?.length || 0,
          } : null,
        },
        tableData: {
          has: !!tableDataToSave,
          count: tableDataToSave?.length || 0,
          sample: tableDataToSave && tableDataToSave.length > 0 && tableDataToSave[0] ? {
            material: tableDataToSave[0].material?.substring(0, 30) || "",
            process: tableDataToSave[0].process?.substring(0, 30) || "",
            property: (tableDataToSave[0].property?.substring(0, 50) || "") + ((tableDataToSave[0].property?.length || 0) > 50 ? "..." : ""),
          } : null,
        },
        willSave: {
          categories: step >= 2 && !!categoriesToSave,
          selectedCategories: step >= 3 && (selectedCategoriesToValidate && (selectedCategoriesToValidate.materials.length > 0 || selectedCategoriesToValidate.processes.length > 0 || selectedCategoriesToValidate.properties.length > 0)),
          tableData: step >= 3 && !!tableDataToSave && tableDataToSave.length > 0,
        },
      });
      
      // Always validate selectedCategories against available categories before saving
      let selectedCategoriesToSave: typeof selectedCategories | undefined = undefined;
      
      if (selectedCategoriesToValidate && 
          (selectedCategoriesToValidate.materials.length > 0 || 
           selectedCategoriesToValidate.processes.length > 0 || 
           selectedCategoriesToValidate.properties.length > 0)) {
        // Validate selected categories against available categories
        // CRITICAL: Log before validation to see what's being compared
        console.log("[Auto Save] 🔍 Validating selected categories against available categories:", {
          selectedToValidate: {
            materials: selectedCategoriesToValidate.materials,
            processes: selectedCategoriesToValidate.processes,
            properties: selectedCategoriesToValidate.properties,
          },
          availableCategories: categoriesToSave ? {
            materials: categoriesToSave.materials,
            processes: categoriesToSave.processes,
            properties: categoriesToSave.properties,
          } : null,
        });
        
        const validatedSelected = {
          materials: categoriesToSave?.materials 
            ? selectedCategoriesToValidate.materials.filter(cat => {
                const exists = categoriesToSave.materials.includes(cat);
                if (!exists) {
                  console.warn(`[Auto Save] ⚠️ Material category not found in available categories: "${cat}"`);
                  console.warn(`[Auto Save] Available materials:`, categoriesToSave.materials);
                }
                return exists;
              })
            : selectedCategoriesToValidate.materials,
          processes: categoriesToSave?.processes 
            ? selectedCategoriesToValidate.processes.filter(cat => {
                const exists = categoriesToSave.processes.includes(cat);
                if (!exists) {
                  console.warn(`[Auto Save] ⚠️ Process category not found in available categories: "${cat}"`);
                  console.warn(`[Auto Save] Available processes:`, categoriesToSave.processes);
                }
                return exists;
              })
            : selectedCategoriesToValidate.processes,
          properties: categoriesToSave?.properties 
            ? selectedCategoriesToValidate.properties.filter(cat => {
                const exists = categoriesToSave.properties.includes(cat);
                if (!exists) {
                  console.warn(`[Auto Save] ⚠️ Property category not found in available categories: "${cat}"`);
                  console.warn(`[Auto Save] Available properties:`, categoriesToSave.properties);
                }
                return exists;
              })
            : selectedCategoriesToValidate.properties,
        };
        
        console.log("[Auto Save] ✅ Validation result:", {
          original: {
            materials: selectedCategoriesToValidate.materials.length,
            processes: selectedCategoriesToValidate.processes.length,
            properties: selectedCategoriesToValidate.properties.length,
          },
          validated: {
            materials: validatedSelected.materials.length,
            processes: validatedSelected.processes.length,
            properties: validatedSelected.properties.length,
          },
          filteredOut: {
            materials: selectedCategoriesToValidate.materials.length - validatedSelected.materials.length,
            processes: selectedCategoriesToValidate.processes.length - validatedSelected.processes.length,
            properties: selectedCategoriesToValidate.properties.length - validatedSelected.properties.length,
          },
          validatedDetails: {
            materials: validatedSelected.materials,
            processes: validatedSelected.processes,
            properties: validatedSelected.properties,
          },
        });
        
        // Only save if there are validated selections
        if (validatedSelected.materials.length > 0 || 
            validatedSelected.processes.length > 0 || 
            validatedSelected.properties.length > 0) {
          selectedCategoriesToSave = validatedSelected;
          
          // Log if validation removed any categories
          if (validatedSelected.materials.length !== selectedCategoriesToValidate.materials.length ||
              validatedSelected.processes.length !== selectedCategoriesToValidate.processes.length ||
              validatedSelected.properties.length !== selectedCategoriesToValidate.properties.length) {
            console.warn("[Auto Save] Some selected categories were filtered out:", {
              original: selectedCategoriesToValidate,
              validated: validatedSelected,
              available: categoriesToSave,
            });
          }
        }
      }

      console.log("[Auto Save] ✅ Selected categories validation result:", {
        step,
        inputSource: selectedCategoriesSource,
        inputCount: selectedCategoriesToValidate ? {
          materials: selectedCategoriesToValidate.materials?.length || 0,
          processes: selectedCategoriesToValidate.processes?.length || 0,
          properties: selectedCategoriesToValidate.properties?.length || 0,
        } : null,
        validated: {
          has: !!selectedCategoriesToSave,
          count: selectedCategoriesToSave ? {
            materials: selectedCategoriesToSave.materials?.length || 0,
            processes: selectedCategoriesToSave.processes?.length || 0,
            properties: selectedCategoriesToSave.properties?.length || 0,
          } : null,
          materials: selectedCategoriesToSave?.materials || [],
          processes: selectedCategoriesToSave?.processes || [],
          properties: selectedCategoriesToSave?.properties || [],
        },
        availableCategories: categoriesToSave ? {
          materials: categoriesToSave.materials?.length || 0,
          processes: categoriesToSave.processes?.length || 0,
          properties: categoriesToSave.properties?.length || 0,
        } : null,
        willSave: step >= 3 && !!selectedCategoriesToSave,
      });

      const recordData: DataExtractionRecordRequest = {
        task_id: recordId || currentTaskId || currentRecordId || undefined, // Use task_id, fallback to record_id for compatibility
        record_id: recordId || currentRecordId || undefined, // Deprecated, kept for backward compatibility
        task_name: taskName,
        extraction_type: "material_extraction",
        extraction_step: step,
        file_name: fileToUse?.name,
        file_size: fileToUse?.size,
        file_base64: fileBase64, // Save file content for full restore
        model_name: params["model_name"] as string | undefined,
        categories: step >= 2 && categoriesToSave ? categoriesToSave : undefined,
        selected_categories: step >= 3 && selectedCategoriesToSave ? selectedCategoriesToSave : undefined,
        // Allow empty table_data for step 3 (e.g., when saving selected_categories before extraction completes)
        table_data: step >= 3 && tableDataToSave !== undefined ? (Array.isArray(tableDataToSave) ? tableDataToSave : []) : undefined,
        result_json: resultToSave || undefined,
        metadata: {
          pdf_source: fileToUse ? "uploaded_file" : "unknown",
        },
      };

      console.log("[Auto Save] Saving record with data:", {
        step: step,
        taskId: recordId || currentTaskId || currentRecordId || "NEW",
        hasTableData: !!tableDataToSave,
        tableDataCount: tableDataToSave?.length || 0,
        tableDataSample: tableDataToSave && tableDataToSave.length > 0 ? tableDataToSave[0] : null,
        hasSelectedCategories: !!selectedCategoriesToSave,
        recordData: {
          extraction_step: step,
          has_table_data: !!recordData.table_data,
          table_data_type: recordData.table_data ? (Array.isArray(recordData.table_data) ? "array" : typeof recordData.table_data) : "null",
        },
      });
      
      const savedRecord = await saveExtractionRecord(recordData);
      const newTaskId = savedRecord.task_id || savedRecord.id; // Use task_id if available, fallback to id
      setCurrentTaskId(newTaskId);
      setCurrentRecordId(savedRecord.id); // Keep for backward compatibility
      
      // Log detailed save result with verification
      const savedTableData = savedRecord.table_data;
      const savedTableDataCount = savedTableData 
        ? (Array.isArray(savedTableData) ? savedTableData.length : 0)
        : 0;
      const savedSelectedCategories = savedRecord.selected_categories;
      
      console.log("[Auto Save] ✅ Record saved successfully - Verification:", {
        recordId: savedRecord.id,
        taskId: newTaskId,
        step: step,
        savedStep: savedRecord.extraction_step,
        wasUpdate: !!recordId,
        categories: {
          sent: !!categoriesToSave,
          saved: !!savedRecord.categories,
          sentCount: categoriesToSave ? {
            materials: categoriesToSave.materials?.length || 0,
            processes: categoriesToSave.processes?.length || 0,
            properties: categoriesToSave.properties?.length || 0,
          } : null,
          savedCount: savedRecord.categories ? {
            materials: savedRecord.categories.materials?.length || 0,
            processes: savedRecord.categories.processes?.length || 0,
            properties: savedRecord.categories.properties?.length || 0,
          } : null,
        },
        selectedCategories: {
          sent: !!selectedCategoriesToSave,
          saved: !!savedSelectedCategories,
          sentCount: selectedCategoriesToSave ? {
            materials: selectedCategoriesToSave.materials?.length || 0,
            processes: selectedCategoriesToSave.processes?.length || 0,
            properties: selectedCategoriesToSave.properties?.length || 0,
          } : null,
          savedCount: savedSelectedCategories ? {
            materials: savedSelectedCategories.materials?.length || 0,
            processes: savedSelectedCategories.processes?.length || 0,
            properties: savedSelectedCategories.properties?.length || 0,
          } : null,
          match: selectedCategoriesToSave && savedSelectedCategories ? (
            selectedCategoriesToSave.materials?.length === savedSelectedCategories.materials?.length &&
            selectedCategoriesToSave.processes?.length === savedSelectedCategories.processes?.length &&
            selectedCategoriesToSave.properties?.length === savedSelectedCategories.properties?.length
          ) : false,
        },
        tableData: {
          sent: !!tableDataToSave,
          sentCount: tableDataToSave?.length || 0,
          saved: !!savedTableData,
          savedCount: savedTableDataCount,
          match: (tableDataToSave?.length || 0) === savedTableDataCount,
        },
      });
      
      // Log table data sample if available
      if (savedTableDataCount > 0 && Array.isArray(savedTableData)) {
        console.log("[Auto Save] 📊 Saved table data sample (first 3 rows):");
        savedTableData.slice(0, 3).forEach((row: any, index: number) => {
          console.log(`  Row ${index + 1}:`, {
            material: row.material || "N/A",
            process: row.process || "N/A",
            property: row.property || "N/A",
          });
        });
      }
      
      if (!recordId) {
        toast.success("任务已自动保存");
        // Refresh history list
        await loadHistoryRecords();
      } else {
        // Also refresh if it was an update
        await loadHistoryRecords();
      }
      
      // Return the saved record
      return savedRecord;
    } catch (error) {
      console.error("Failed to auto-save record:", error);
      // Show error in console but don't annoy users with toast
      return null;
    }
  };

  // Restore state from record
  const restoreFromRecord = async (record: DataExtractionRecord) => {
    try {
      console.log("[Restore] Starting restore from record:", record.id);
      
      // Get full record with file content
      const fullRecord = await getExtractionRecord(record.id);
      
      console.log("[Restore] Full record loaded:", {
        step: fullRecord.extraction_step,
        hasCategories: !!fullRecord.categories,
        hasSelectedCategories: !!fullRecord.selected_categories,
        hasTableData: !!fullRecord.table_data,
        tableDataCount: fullRecord.table_data?.length || 0,
        hasFile: !!fullRecord.file_base64,
        categories: fullRecord.categories,
        selectedCategories: fullRecord.selected_categories,
      });

      // Restore file first (if available)
      if (fullRecord.file_base64 && fullRecord.file_name) {
        try {
          // Convert base64 to File object
          const byteCharacters = atob(fullRecord.file_base64);
          const byteNumbers = new Array(byteCharacters.length);
          for (let i = 0; i < byteCharacters.length; i++) {
            byteNumbers[i] = byteCharacters.charCodeAt(i);
          }
          const byteArray = new Uint8Array(byteNumbers);
          const blob = new Blob([byteArray]);
          const file = new File([blob], fullRecord.file_name, {
            type: fullRecord.file_name.endsWith(".pdf") ? "application/pdf" : "application/xml",
          });
          setUploadedFile(file);
          console.log("[Restore] File restored:", fullRecord.file_name);
        } catch (e) {
          console.error("Failed to restore file:", e);
        }
      }

      // Restore all states in batch - update all at once to avoid race conditions
      const restoredStep = fullRecord.extraction_step || 1;
      
      // Set extraction type first
      setExtractionType(fullRecord.extraction_type || "material_extraction");
      const taskIdToUse = fullRecord.task_id || fullRecord.id; // Use task_id if available
      setCurrentTaskId(taskIdToUse);
      setCurrentRecordId(fullRecord.id); // Keep for backward compatibility

      // Restore categories (required for step 1+)
      // Categories should come from data_extraction_categories table
      const restoredCategories = fullRecord.categories || null;
      setCategories(restoredCategories);
      console.log("[Restore] Categories restored from categories table:", restoredCategories ? {
        materials: restoredCategories.materials?.length || 0,
        processes: restoredCategories.processes?.length || 0,
        properties: restoredCategories.properties?.length || 0,
        materialsList: restoredCategories.materials || [],
        processesList: restoredCategories.processes || [],
        propertiesList: restoredCategories.properties || [],
      } : "null");

      // Restore selected categories (for step 2+)
      // Selected categories should come from data_extraction_data table
      let restoredSelectedCategories = fullRecord.selected_categories || { materials: [], processes: [], properties: [] };
      console.log("[Restore] Selected categories loaded from data table:", {
        materials: restoredSelectedCategories.materials?.length || 0,
        processes: restoredSelectedCategories.processes?.length || 0,
        properties: restoredSelectedCategories.properties?.length || 0,
        materialsList: restoredSelectedCategories.materials || [],
        processesList: restoredSelectedCategories.processes || [],
        propertiesList: restoredSelectedCategories.properties || [],
      });
      
      // If we have categories, validate selected categories match exactly
      if (restoredCategories) {
        const validatedSelected = {
          materials: (restoredSelectedCategories.materials || []).filter(cat => 
            restoredCategories.materials?.includes(cat)
          ),
          processes: (restoredSelectedCategories.processes || []).filter(cat => 
            restoredCategories.processes?.includes(cat)
          ),
          properties: (restoredSelectedCategories.properties || []).filter(cat => 
            restoredCategories.properties?.includes(cat)
          ),
        };
        
        // If validation removed some categories, log a warning
        if (validatedSelected.materials.length !== (restoredSelectedCategories.materials?.length || 0) ||
            validatedSelected.processes.length !== (restoredSelectedCategories.processes?.length || 0) ||
            validatedSelected.properties.length !== (restoredSelectedCategories.properties?.length || 0)) {
          console.warn("[Restore] Some selected categories don't match available categories:", {
            original: restoredSelectedCategories,
            validated: validatedSelected,
            available: restoredCategories,
          });
        }
        
        restoredSelectedCategories = validatedSelected;
      }
      
      setSelectedCategories(restoredSelectedCategories);
      console.log("[Restore] Selected categories restored and validated:", {
        materials: restoredSelectedCategories.materials?.length || 0,
        processes: restoredSelectedCategories.processes?.length || 0,
        properties: restoredSelectedCategories.properties?.length || 0,
        materialsList: restoredSelectedCategories.materials || [],
        processesList: restoredSelectedCategories.processes || [],
        propertiesList: restoredSelectedCategories.properties || [],
        // Verify mapping: check if selected categories exist in available categories
        mappingValid: restoredCategories ? {
          materials: restoredSelectedCategories.materials.every(cat => restoredCategories.materials?.includes(cat)),
          processes: restoredSelectedCategories.processes.every(cat => restoredCategories.processes?.includes(cat)),
          properties: restoredSelectedCategories.properties.every(cat => restoredCategories.properties?.includes(cat)),
        } : null,
      });

      // Restore table data (for step 3)
      const restoredTableData = fullRecord.table_data || [];
      setTableData(restoredTableData);
      console.log("[Restore] Table data restored:", restoredTableData.length, "rows");

      // Restore result JSON
      setResult(fullRecord.result_json || null);

      // Restore params - update extraction_step here
      setParams((prev) => ({
        ...prev,
        extraction_type: fullRecord.extraction_type || "material_extraction",
        extraction_step: restoredStep,
        model_name: fullRecord.model_name || prev["model_name"],
      }));

      // Set extraction step - this should be set after all other states
      setExtractionStep(restoredStep);
      
      console.log("[Restore] All states restored. Final state:", {
        extractionStep: restoredStep,
        hasCategories: !!restoredCategories,
        categoriesCount: restoredCategories ? {
          materials: restoredCategories.materials?.length || 0,
          processes: restoredCategories.processes?.length || 0,
          properties: restoredCategories.properties?.length || 0,
        } : null,
        selectedCategoriesCount: {
          materials: restoredSelectedCategories.materials?.length || 0,
          processes: restoredSelectedCategories.processes?.length || 0,
          properties: restoredSelectedCategories.properties?.length || 0,
        },
        tableDataCount: restoredTableData.length,
      });

      setShowHistory(false);
      toast.success("已还原任务状态");
    } catch (error) {
      console.error("Failed to restore from record:", error);
      toast.error("还原任务失败");
    }
  };

  // Delete record
  const handleDeleteRecord = async (recordId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm("确定要删除这条记录吗？")) {
      return;
    }

    try {
      await deleteExtractionRecord(recordId);
      toast.success("记录已删除");
      await loadHistoryRecords();
      const taskIdToUse = currentTaskId || currentRecordId;
      if (taskIdToUse === recordId || currentRecordId === recordId) {
        setCurrentTaskId(null);
        setCurrentRecordId(null);
      }
    } catch (error) {
      console.error("Failed to delete record:", error);
      toast.error("删除记录失败");
    }
  };

  // Load history on mount
  useEffect(() => {
    if (tool.id === "data_extraction" && extractionType === "material_extraction") {
      loadHistoryRecords();
    }
  }, [tool.id, extractionType]);

  // Convert MOLECULAR_IMAGE_ID comments to Markdown image syntax
  const processResult = (rawResult: string | null): string => {
    if (!rawResult) return "";
    // Match pattern: <!-- MOLECULAR_IMAGE_ID:uuid -->
    const imageIdPattern = /<!--\s*MOLECULAR_IMAGE_ID:([a-f0-9\-]+)\s*-->/gi;
    return rawResult.replace(imageIdPattern, (match, imageId) => {
      // Replace comment with Markdown image syntax
      return `\n\n![Molecular Structures Grid](/molecular_images/${imageId}.svg)\n\n`;
    });
  };

  const renderResultContent = () => {
    if (!result) return null;

    // 文生图结果：解析 JSON，展示图片与下载链接
    if (tool.id === "image_gen") {
      try {
        const data = JSON.parse(result) as { error?: string; download_url?: string; filename?: string; path?: string };
        if (data.error) {
          return (
            <div className="text-sm text-red-600 dark:text-red-400">{data.error}</div>
          );
        }
        if (data.download_url) {
          const imgUrl = data.download_url.startsWith("/") ? data.download_url : `/${data.download_url}`;
          return (
            <div className="space-y-3">
              <div className="rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden bg-slate-50 dark:bg-slate-900/50 flex justify-center items-center p-4">
                <img
                  src={imgUrl}
                  alt="生成的图片"
                  className="max-w-full max-h-[70vh] w-auto h-auto object-contain"
                />
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <a
                  href={imgUrl}
                  download={data.filename || "image.png"}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1.5 px-3 py-2 rounded-md bg-blue-500 text-white text-sm hover:bg-blue-600 dark:bg-blue-600 dark:hover:bg-blue-500 transition-colors"
                >
                  <Download className="h-4 w-4" />
                  下载图片
                </a>
                <span className="text-xs text-slate-500 dark:text-slate-400">
                  {data.filename || data.path || ""}
                </span>
              </div>
            </div>
          );
        }
      } catch {
        // 解析失败则走默认 Markdown
      }
    }

    // 文献搜索结果：尝试解析为 JSON 列表并表格展示
    if (tool.id === "literature_search") {
      try {
        const parsed = JSON.parse(result);
        if (Array.isArray(parsed) && parsed.length > 0 && typeof parsed[0] === "object") {
          type LitItem = {
            title?: string;
            authors?: string[] | string;
            year?: number;
            url?: string;
            pdf_url?: string;
            source?: string;
            abstract?: string;
          };
          const items = parsed as LitItem[];

          return (
            <div className="space-y-2">
              <div className="max-h-96 overflow-auto border border-slate-200 dark:border-slate-700 rounded-md">
                <table className="min-w-full text-xs">
                  <thead className="bg-slate-50 dark:bg-slate-900">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium text-slate-600 dark:text-slate-300">标题</th>
                      <th className="px-3 py-2 text-left font-medium text-slate-600 dark:text-slate-300">作者</th>
                      <th className="px-3 py-2 text-left font-medium text-slate-600 dark:text-slate-300">年份</th>
                      <th className="px-3 py-2 text-left font-medium text-slate-600 dark:text-slate-300">来源</th>
                      <th className="px-3 py-2 text-left font-medium text-slate-600 dark:text-slate-300">操作</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
                    {items.map((item, idx) => {
                      const authors =
                        Array.isArray(item.authors)
                          ? item.authors.join(", ")
                          : typeof item.authors === "string"
                          ? item.authors
                          : "";
                      return (
                        <tr key={idx} className="hover:bg-slate-50 dark:hover:bg-slate-900/40">
                          <td className="px-3 py-2 align-top">
                            {item.url ? (
                              <a
                                href={item.url}
                                target="_blank"
                                rel="noreferrer"
                                className="text-xs text-blue-600 dark:text-blue-400 hover:underline"
                              >
                                {item.title || "(无标题)"}
                              </a>
                            ) : (
                              <span className="text-xs text-slate-800 dark:text-slate-100">
                                {item.title || "(无标题)"}
                              </span>
                            )}
                          </td>
                          <td className="px-3 py-2 align-top text-xs text-slate-600 dark:text-slate-300">
                            {authors || "-"}
                          </td>
                          <td className="px-3 py-2 align-top text-xs text-slate-600 dark:text-slate-300">
                            {item.year ?? "-"}
                          </td>
                          <td className="px-3 py-2 align-top text-xs text-slate-600 dark:text-slate-300">
                            {item.source || "arxiv"}
                          </td>
                          <td className="px-3 py-2 align-top text-xs">
                            {item.pdf_url ? (
                              <a
                                href={item.pdf_url}
                                target="_blank"
                                rel="noreferrer"
                                className="inline-flex items-center gap-1 text-blue-600 dark:text-blue-400 hover:underline"
                              >
                                <Download className="h-3 w-3" />
                                下载 PDF
                              </a>
                            ) : (
                              <span className="text-slate-400 dark:text-slate-500">无PDF链接</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p className="text-[11px] text-slate-500 dark:text-slate-400">
                提示：点击标题在新标签页打开文献；如有 PDF 链接，可直接点击「下载 PDF」。
              </p>
            </div>
          );
        }
      } catch {
        // 解析失败则回退为 Markdown 渲染
      }
    }

    // 默认：按 Markdown 渲染
    return (
      <div className="text-sm text-green-700 dark:text-green-400">
        <Markdown>{processResult(result)}</Markdown>
      </div>
    );
  };

  const handleExecute = async () => {
    if (!validateParams()) {
      return;
    }

    setExecuting(true);
    setResult(null);
    setError(null);
    setExtractionProgress(0);
    
    // Simulate progress for material extraction
    let progressInterval: NodeJS.Timeout | null = null;
    if (tool.id === "data_extraction" && extractionType === "material_extraction") {
      const currentStep = extractionStep || (params["extraction_step"] as number) || 1;
      if (currentStep === 1) {
        // Simulate progress for category extraction
        progressInterval = setInterval(() => {
          setExtractionProgress((prev) => {
            if (prev >= 90) {
              if (progressInterval) clearInterval(progressInterval);
              return 90;
            }
            return prev + 10;
          });
        }, 200);
      } else if (currentStep === 2) {
        // Simulate progress for data extraction
        progressInterval = setInterval(() => {
          setExtractionProgress((prev) => {
            if (prev >= 90) {
              if (progressInterval) clearInterval(progressInterval);
              return 90;
            }
            return prev + 10;
          });
        }, 300);
      }
    }

    try {
      // Prepare parameters
      const executeParams = { ...params };
      const currentType = (params["extraction_type"] as string) || extractionType || "prompt_extraction";
      const currentStep = extractionStep || (params["extraction_step"] as number) || 1;

      // PPT generator: set params by engine and step
      if (tool.id === "ppt_generator") {
        const engine = (params["engine"] as string) || "slide_deck";
        executeParams["engine"] = engine;
        if (engine === "slide_deck") {
          if (pptStep === 1) {
            executeParams["topic"] = (params["topic"] as string) || "";
            executeParams["content"] = (params["content"] as string) || "";
            executeParams["outline"] = "";
            executeParams["outline_only"] = true;
            executeParams["style"] = params["style"] ?? "blueprint";
            executeParams["audience"] = params["audience"] ?? "general";
            executeParams["lang"] = params["lang"] ?? "auto";
            executeParams["slides"] = params["slides"] ?? 8;
          } else if (pptStep === 2) {
            executeParams["topic"] = "";
            executeParams["content"] = "";
            executeParams["outline"] = outlineContent;
            executeParams["outline_only"] = false;
            executeParams["prompts_only"] = false;
            executeParams["images_only"] = false;
          }
        } else {
          if (pptStep === 1) {
            executeParams["topic"] = (params["topic"] as string) || "";
            executeParams["outline"] = "";
            executeParams["action"] = "outline";
          } else if (pptStep === 2) {
            executeParams["topic"] = "";
            executeParams["outline"] = outlineContent;
            executeParams["action"] = "generate";
          }
        }
      }

      // For data_extraction tool, convert uploaded file to base64
      if (tool.id === "data_extraction" && uploadedFile) {
        try {
          const base64 = await fileToBase64(uploadedFile);
          executeParams["pdf_file_base64"] = base64;
          // Remove pdf_file from params if it exists
          delete executeParams["pdf_file"];
        } catch (e) {
          setError(`文件读取失败: ${(e as Error).message}`);
          setExecuting(false);
          return;
        }
      }

      // Handle material extraction mode
      if (tool.id === "data_extraction" && currentType === "material_extraction") {
        executeParams["extraction_type"] = "material_extraction";
        // CRITICAL: If categories already exist, we should NOT run step 1 again
        // Force step 2 if categories exist (means step 1 was already completed)
        let actualStep = currentStep;
        if (categories && currentStep === 1) {
          console.warn("[Execute] ⚠️ Categories already exist but currentStep is 1. Forcing step 2 to prevent re-extraction.");
          console.warn("[Execute] This should not happen - categories should only be extracted once.");
          actualStep = 2;
          // Also update state to prevent confusion
          setExtractionStep(2);
          setParams((prev) => ({
            ...prev,
            extraction_step: 2,
          }));
        }
        executeParams["extraction_step"] = actualStep;
        console.log("[Execute] Using extraction_step:", actualStep, "(currentStep was:", currentStep, ", categories exist:", !!categories, ")");
        
        if (actualStep === 2) {
          // Step 2: include selected categories
          // CRITICAL: Use exact values from selectedCategories state
          const materialsToSend = selectedCategories.materials || [];
          const processesToSend = selectedCategories.processes || [];
          const propertiesToSend = selectedCategories.properties || [];
          
          console.log("[Execute] 📤 Sending selected categories to backend:", {
            step: actualStep,
            materials: {
              count: materialsToSend.length,
              values: materialsToSend,
              rawLengths: materialsToSend.map(c => c.length),
            },
            processes: {
              count: processesToSend.length,
              values: processesToSend,
              rawLengths: processesToSend.map(c => c.length),
            },
            properties: {
              count: propertiesToSend.length,
              values: propertiesToSend,
              rawLengths: propertiesToSend.map(c => c.length),
            },
            // Verify against available categories
            availableCategories: categories ? {
              materials: categories.materials?.length || 0,
              processes: categories.processes?.length || 0,
              properties: categories.properties?.length || 0,
            } : null,
            // Check if all selected categories exist in available categories
            validation: categories ? {
              materialsValid: materialsToSend.every(c => categories.materials?.includes(c)),
              processesValid: processesToSend.every(c => categories.processes?.includes(c)),
              propertiesValid: propertiesToSend.every(c => categories.properties?.includes(c)),
            } : null,
          });
          
          executeParams["selected_material_categories"] = materialsToSend;
          executeParams["selected_process_categories"] = processesToSend;
          executeParams["selected_property_categories"] = propertiesToSend;
          
          console.log("[Execute] 📤 Execute params with selected categories:", {
            selected_material_categories: executeParams["selected_material_categories"],
            selected_process_categories: executeParams["selected_process_categories"],
            selected_property_categories: executeParams["selected_property_categories"],
          });
        }
      }

      let resultText: string;
      if (onExecute) {
        resultText = await onExecute(tool.id, executeParams);
      } else {
        // 使用工具执行API
        resultText = await executeTool(tool.toolName, executeParams);
      }

      // Handle PPT generator results
      if (tool.id === "ppt_generator") {
        try {
          const data = JSON.parse(resultText) as {
            outline?: string;
            error?: string;
            download_url?: string;
            filename?: string;
            pptx_download_url?: string;
            pdf_download_url?: string;
            slides_preview_urls?: string[];
          };
          if (data.error) {
            setError(data.error);
            setResult(resultText);
          } else if (pptStep === 1 && data.outline !== undefined) {
            setOutlineContent(data.outline);
            setPptStep(2);
            setResult(resultText);
            setError(null);
          } else if (pptStep === 2) {
            const engine = (params["engine"] as string) || "slide_deck";
            if (engine === "slide_deck" && (data.pptx_download_url || data.pdf_download_url)) {
              setPptDownloadUrl(
                data.pptx_download_url
                  ? (data.pptx_download_url.startsWith("/") ? data.pptx_download_url : `/${data.pptx_download_url}`)
                  : null
              );
              setPptPdfDownloadUrl(
                data.pdf_download_url
                  ? (data.pdf_download_url.startsWith("/") ? data.pdf_download_url : `/${data.pdf_download_url}`)
                  : null
              );
              const urls = (data.slides_preview_urls || []).map((u: string) =>
                u.startsWith("/") ? u : `/${u}`
              );
              setPptSlidesPreviewUrls(urls);
              setPptStep(3);
              setResult(resultText);
              setError(null);
              saveToolRunHistory(
                "ppt_generator",
                { topic: params.topic, outline: outlineContent, engine: params.engine },
                resultText
              ).catch(() => {});
            } else if (engine === "simple" && data.download_url) {
              setPptDownloadUrl(
                data.download_url.startsWith("/") ? data.download_url : `/${data.download_url}`
              );
              setPptPdfDownloadUrl(null);
              setPptSlidesPreviewUrls([]);
              setPptStep(3);
              setResult(resultText);
              setError(null);
              saveToolRunHistory(
                "ppt_generator",
                { topic: params.topic, outline: outlineContent, engine: params.engine },
                resultText
              ).catch(() => {});
            } else {
              setResult(resultText);
            }
          } else {
            setResult(resultText);
          }
        } catch {
          setResult(resultText);
        }
      }

      // Handle material extraction results
      if (tool.id === "data_extraction" && currentType === "material_extraction") {
        try {
          const resultJson = JSON.parse(resultText);
          if (resultJson.step === 1) {
            // Step 1: show categories (still in step 1, just show selection UI)
            // CRITICAL: Only process step 1 result if we're actually in step 1
            // If categories already exist, this means we're re-running step 1 incorrectly
            if (categories) {
              console.error("[Execute] ⚠️ Received step 1 result but categories already exist! This should not happen after step 1 is complete.");
              console.error("[Execute] Current extractionStep:", extractionStep, "params extraction_step:", params["extraction_step"]);
              console.error("[Execute] Existing categories:", {
                materials: categories.materials?.length || 0,
                processes: categories.processes?.length || 0,
                properties: categories.properties?.length || 0,
              });
              console.error("[Execute] New categories from backend:", {
                materials: resultJson.categories?.materials?.length || 0,
                processes: resultJson.categories?.processes?.length || 0,
                properties: resultJson.categories?.properties?.length || 0,
              });
              // Don't overwrite existing categories - this is a bug
              setError("错误：检测到重复的主题分析，已跳过。如果问题持续，请刷新页面。");
              setExecuting(false);
              return;
            }
            
            const categoriesData = {
              materials: resultJson.categories?.materials || [],
              processes: resultJson.categories?.processes || [],
              properties: resultJson.categories?.properties || [],
            };
            
            // Log categories to verify they match what will be saved
            console.log("[Step 1] Categories received from backend:", {
              materialsCount: categoriesData.materials.length,
              processesCount: categoriesData.processes.length,
              propertiesCount: categoriesData.properties.length,
              materials: categoriesData.materials,
              processes: categoriesData.processes,
              properties: categoriesData.properties,
            });
            
            setCategories(categoriesData);
            setExtractionProgress(100);
            setResult(resultText);
            // Auto-save step 2 result - pass data directly to avoid async state issue
            // Step 2 means topic analysis is complete, categories are extracted
            autoSaveRecord(2, undefined, categoriesData, undefined, resultText);
            // Stay in step 1 to show category selection (UI step 1, but DB step 2)
          } else if (resultJson.step === 2) {
            // Step 2: show table data, move to step 3
            const data = resultJson.table_data || [];
            console.log("[Data Extraction] 📊 Step 2 completed - Data extraction result received:", {
              step: resultJson.step,
              dataCount: data.length,
              dataType: Array.isArray(data) ? "array" : typeof data,
              firstItem: data.length > 0 ? {
                material: data[0].material,
                process: data[0].process,
                property: data[0].property?.substring(0, 50) + (data[0].property?.length > 50 ? "..." : ""),
              } : null,
              sampleItems: data.length > 0 ? data.slice(0, 3).map((item: any) => ({
                material: item.material,
                process: item.process,
                property: item.property?.substring(0, 30) + (item.property?.length > 30 ? "..." : ""),
              })) : [],
            });
            
            // Validate table data format
            if (!Array.isArray(data)) {
              console.error("[Data Extraction] Invalid table_data format, expected array, got:", typeof data);
              setError("数据格式错误：表格数据应为数组格式");
              setExtractionProgress(0);
              setExecuting(false);
              return;
            }
            
            // 直接更新所有状态，不依赖 useEffect
            setTableData(data);
            setExtractionProgress(100);
            setResult(resultText);
            setError(null);
            
            // 立即更新到 step 3，不等待 useEffect
            setExtractionStep(3);
            setParams((prev) => ({
              ...prev,
              extraction_step: 3,
            }));
            
            console.log("[Data Extraction] Step 2 completed, moved to step 3:", {
              tableDataLength: data.length,
              extractionStep: 3,
              selectedCategories: selectedCategories,
              currentRecordId: currentRecordId,
            });
            
            // Auto-save step 3 result - pass data directly to avoid async state issue
            // Note: selectedCategories will be automatically included in autoSaveRecord
            // Save as step 3 because data extraction is complete and we're now in result display phase
            const saveRecordId = currentTaskId || currentRecordId || undefined;
            console.log("[Data Extraction] Saving step 3 result (data extraction completed):", {
              recordId: saveRecordId,
              tableDataLength: data.length,
              hasCategories: !!categories,
              selectedCategories: selectedCategories,
            });
            try {
              // Save with step 3, which will include table_data and selected_categories
              // Step 3 means data extraction is complete and results are displayed
              // IMPORTANT: Explicitly pass selectedCategories to ensure it's saved
              console.log("[Data Extraction] Preparing to save step 3:", {
                recordId: saveRecordId,
                hasCategories: !!categories,
                hasSelectedCategories: !!selectedCategories,
                selectedCategoriesCount: selectedCategories ? {
                  materials: selectedCategories.materials.length,
                  processes: selectedCategories.processes.length,
                  properties: selectedCategories.properties.length,
                } : null,
                hasTableData: !!data,
                tableDataCount: data.length,
              });
              
              const savedRecord = await autoSaveRecord(3, saveRecordId, categories, data, resultText, selectedCategories);
              if (savedRecord) {
                console.log("[Data Extraction] ✅ Step 3 result saved successfully:", {
                  recordId: savedRecord.id,
                  step: savedRecord.extraction_step,
                  hasTableData: !!savedRecord.table_data,
                  tableDataCount: savedRecord.table_data ? (Array.isArray(savedRecord.table_data) ? savedRecord.table_data.length : "not array") : 0,
                  hasSelectedCategories: !!savedRecord.selected_categories,
                  selectedCategoriesCount: savedRecord.selected_categories ? {
                    materials: savedRecord.selected_categories.materials?.length || 0,
                    processes: savedRecord.selected_categories.processes?.length || 0,
                    properties: savedRecord.selected_categories.properties?.length || 0,
                  } : null,
                });
              } else {
                console.error("[Data Extraction] ❌ Step 3 save returned null");
              }
            } catch (error) {
              console.error("[Data Extraction] ❌ Failed to save step 3 result:", error);
              // Don't block UI, but log the error
            }
          } else {
            console.log("[Data Extraction] Unexpected step in result:", resultJson.step, "result:", resultJson);
            setResult(resultText);
          }
        } catch {
          setResult(resultText);
        }
      } else {
        setResult(resultText);
        if (tool.id === "image_gen" && resultText) {
          try {
            const parsed = JSON.parse(resultText) as { error?: string; download_url?: string };
            if (parsed && !parsed.error && parsed.download_url) {
              saveToolRunHistory("image_gen", { ...params }, resultText).catch(() => {});
            }
          } catch {
            // ignore
          }
        }
      }
    } catch (e) {
      setError((e as Error).message || "工具执行失败");
      setExtractionProgress(0);
    } finally {
      setExecuting(false);
      // Progress will be set to 100 in result handling
    }
  };

  const handleDownloadJson = () => {
    if (!result) return;

    try {
      // Try to parse the result as JSON
      let jsonData: unknown;
      try {
        jsonData = JSON.parse(result);
      } catch {
        // If not valid JSON, wrap it in an object
        jsonData = { result: result };
      }

      // Create a blob and download
      const blob = new Blob([JSON.stringify(jsonData, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `data_extraction_${new Date().getTime()}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error("Failed to download JSON:", e);
      setError("下载JSON文件失败");
    }
  };

  const handleDownloadCsv = () => {
    if (tableData.length === 0) return;

    try {
      // Create CSV content
      const headers = ["材料", "工艺", "性能"];
      const rows = tableData.map((row) => [
        row.material || "",
        row.process || "",
        row.property || "",
      ]);

      const csvContent = [
        headers.join(","),
        ...rows.map((row) => row.map((cell) => `"${cell.replace(/"/g, '""')}"`).join(",")),
      ].join("\n");

      // Create a blob and download
      const blob = new Blob(["\uFEFF" + csvContent], {
        type: "text/csv;charset=utf-8;",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `material_data_${new Date().getTime()}.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error("Failed to download CSV:", e);
      setError("下载CSV文件失败");
    }
  };

  const handleCategoryToggle = (
    categoryType: "materials" | "processes" | "properties",
    category: string
  ) => {
    // Validate that the category exists in the original categories list
    if (!categories) {
      console.error("[Category Toggle] Categories not loaded yet");
      return;
    }
    
    const availableCategories = categories[categoryType] || [];
    if (!availableCategories.includes(category)) {
      console.error("[Category Toggle] Category not found in available categories:", {
        category,
        categoryType,
        availableCategories,
      });
      return;
    }
    
    console.log("[Category Toggle] Toggling category:", {
      categoryType,
      category,
      categoryLength: category.length,
      categoryBytes: new TextEncoder().encode(category).length,
    });
    
    setSelectedCategories((prev) => {
      if (categoryType === "materials") {
        // Materials: single selection (radio button behavior)
        const current = prev[categoryType];
        if (current.includes(category)) {
          // If already selected, don't allow deselecting (must have one selected)
          return prev;
        } else {
          // Replace with new selection - use exact category string from categories
          const exactCategory = availableCategories.find(c => c === category) || category;
          console.log("[Category Toggle] Setting material category:", exactCategory);
          return {
            ...prev,
            [categoryType]: [exactCategory],
          };
        }
      } else {
        // Processes and properties: multiple selection (checkbox behavior)
        const current = prev[categoryType];
        const exactCategory = availableCategories.find(c => c === category) || category;
        const newList = current.includes(exactCategory)
          ? current.filter((c) => c !== exactCategory)
          : [...current, exactCategory];
        console.log("[Category Toggle] Updated list:", {
          categoryType,
          newList,
          exactCategory,
        });
        return {
          ...prev,
          [categoryType]: newList,
        };
      }
    });
  };

  const handleSelectAll = (categoryType: "materials" | "processes" | "properties") => {
    // Materials don't support select all (single selection only)
    if (categoryType === "materials") {
      return;
    }
    
    if (!categories) {
      console.error("[Select All] Categories not loaded yet");
      return;
    }
    
    const allCategories = categories[categoryType] || [];
    const current = selectedCategories[categoryType];
    const allSelected = allCategories.every((cat) => current.includes(cat));
    
    // Use exact categories from the original list
    const exactCategories = [...allCategories];
    console.log("[Select All] Toggling all categories:", {
      categoryType,
      allSelected,
      exactCategories,
    });
    
    setSelectedCategories((prev) => ({
      ...prev,
      [categoryType]: allSelected ? [] : exactCategories,
    }));
  };

  // Handle step click to switch between steps
  const handleStepClick = async (step: number) => {
    const taskIdToUse = currentTaskId || currentRecordId;
    if (!taskIdToUse) {
      toast.error("没有可用的任务记录");
      return;
    }
    
    // Only allow clicking step 2 or 3
    if (step !== 2 && step !== 3) {
      return;
    }
    
    try {
      console.log("[Step Switch] Loading step data:", step, "taskId:", taskIdToUse);
      const record = await getExtractionRecord(taskIdToUse);
      
      if (step === 2) {
        // Display category selection interface
        // Categories should come from data_extraction_categories table
        if (!record.categories) {
          toast.error("未找到类别数据");
          return;
        }
        
        setExtractionStep(2);
        // Load categories from categories table
        setCategories(record.categories);
        console.log("[Step Switch] Categories loaded from categories table:", {
          materials: record.categories.materials?.length || 0,
          processes: record.categories.processes?.length || 0,
          properties: record.categories.properties?.length || 0,
        });
        
        // Load selected categories from data_extraction_data table
        if (record.selected_categories) {
          // Validate selected categories against available categories
          const availableCategories = record.categories;
          const validatedSelected = availableCategories ? {
            materials: (record.selected_categories.materials || []).filter(cat => 
              availableCategories.materials?.includes(cat)
            ),
            processes: (record.selected_categories.processes || []).filter(cat => 
              availableCategories.processes?.includes(cat)
            ),
            properties: (record.selected_categories.properties || []).filter(cat => 
              availableCategories.properties?.includes(cat)
            ),
          } : record.selected_categories;
          setSelectedCategories(validatedSelected);
          console.log("[Step Switch] Selected categories loaded from data table and validated:", {
            materials: validatedSelected.materials.length,
            processes: validatedSelected.processes.length,
            properties: validatedSelected.properties.length,
            materialsList: validatedSelected.materials,
            processesList: validatedSelected.processes,
            propertiesList: validatedSelected.properties,
          });
        } else {
          setSelectedCategories({ materials: [], processes: [], properties: [] });
          console.log("[Step Switch] No selected categories found in data table");
        }
        
        // Clear table data when switching to step 2
        setTableData([]);
        
        setParams((prev) => ({
          ...prev,
          extraction_step: 2,
        }));
        
        console.log("[Step Switch] Switched to step 2, categories loaded:", {
          materials: record.categories.materials?.length || 0,
          processes: record.categories.processes?.length || 0,
          properties: record.categories.properties?.length || 0,
        });
      } else if (step === 3) {
        // Display result table
        if (!record.table_data || !Array.isArray(record.table_data) || record.table_data.length === 0) {
          toast.error("未找到表格数据");
          return;
        }
        
        setExtractionStep(3);
        // Load categories from categories table
        setCategories(record.categories || null);
        // Load selected categories from data_extraction_data table
        const selectedFromData = record.selected_categories || { materials: [], processes: [], properties: [] };
        // Validate selected categories against available categories
        const availableCategories = record.categories;
        const validatedSelected = availableCategories ? {
          materials: (selectedFromData.materials || []).filter(cat => 
            availableCategories.materials?.includes(cat)
          ),
          processes: (selectedFromData.processes || []).filter(cat => 
            availableCategories.processes?.includes(cat)
          ),
          properties: (selectedFromData.properties || []).filter(cat => 
            availableCategories.properties?.includes(cat)
          ),
        } : selectedFromData;
        setSelectedCategories(validatedSelected);
        setTableData(record.table_data);
        console.log("[Step Switch] Step 3 loaded:", {
          categoriesFromCategoriesTable: record.categories ? {
            materials: record.categories.materials?.length || 0,
            processes: record.categories.processes?.length || 0,
            properties: record.categories.properties?.length || 0,
          } : null,
          selectedFromDataTable: {
            materials: validatedSelected.materials.length,
            processes: validatedSelected.processes.length,
            properties: validatedSelected.properties.length,
          },
          tableDataRows: record.table_data.length,
        });
        
        setParams((prev) => ({
          ...prev,
          extraction_step: 3,
        }));
        
        console.log("[Step Switch] Switched to step 3, table data loaded:", {
          tableDataCount: record.table_data.length,
        });
      }
      
      toast.success(`已切换到步骤 ${step}`);
    } catch (error) {
      console.error("[Step Switch] Failed to load step data:", error);
      toast.error("加载步骤数据失败");
    }
  };

  const handleStartExtraction = async () => {
    // Validate: material is required, and at least one process or property
    if (selectedCategories.materials.length === 0) {
      setErrors({ materials: "必须选择一个材料类别" });
      return;
    }
    if (selectedCategories.processes.length === 0 && selectedCategories.properties.length === 0) {
      setErrors({ categories: "必须至少选择一个工艺类别或性能类别" });
      return;
    }
    
    setErrors({});
    
    // Save selected categories before moving to step 2
    try {
      // Validate selected categories match available categories
      const validatedSelectedCategories = {
        materials: selectedCategories.materials.filter(cat => 
          categories?.materials.includes(cat)
        ),
        processes: selectedCategories.processes.filter(cat => 
          categories?.processes.includes(cat)
        ),
        properties: selectedCategories.properties.filter(cat => 
          categories?.properties.includes(cat)
        ),
      };
      
      console.log("[Start Extraction] Saving selected categories before step 2:", {
        original: selectedCategories,
        validated: validatedSelectedCategories,
        categories: categories,
      });
      
      // Update selectedCategories to ensure exact match
      setSelectedCategories(validatedSelectedCategories);
      
      // Save selected_categories immediately to data table (with empty table_data)
      // This ensures selected categories are available when switching between steps
      const taskIdToUse = currentTaskId || currentRecordId;
      if (taskIdToUse && categories) {
        try {
          console.log("[Start Extraction] Saving selected categories to data table (intermediate save):", {
            taskId: taskIdToUse,
            selectedCategories: validatedSelectedCategories,
          });
          // Save with step 3, but with empty table_data - this will be updated when extraction completes
          // This allows selected_categories to be available for step switching
          await autoSaveRecord(3, taskIdToUse, categories, [], undefined, validatedSelectedCategories);
        } catch (error) {
          console.error("[Start Extraction] Failed to save selected categories:", error);
          // Continue even if save fails
        }
      }
      
      console.log("[Start Extraction] Selected categories validated, proceeding to step 2:", {
        materials: validatedSelectedCategories.materials.length,
        processes: validatedSelectedCategories.processes.length,
        properties: validatedSelectedCategories.properties.length,
      });
    } catch (error) {
      console.error("[Start Extraction] Failed to save selected categories:", error);
      // Continue even if save fails
    }
    
    // Update step and params BEFORE calling handleExecute
    // CRITICAL: Set step to 2 explicitly to avoid re-running step 1
    setExtractionStep(2);
    setParams((prev) => ({
      ...prev,
      extraction_step: 2, // Explicitly set to 2 to prevent step 1 re-execution
    }));
    
    // CRITICAL: Wait for state to update, then start extraction with step 2
    // Use a callback to ensure step 2 is used, not relying on async state
    setTimeout(() => {
      // Ensure params are set to step 2 before executing
      setParams((prev) => ({
        ...prev,
        extraction_step: 2, // Force step 2
      }));
      
      console.log("[Start Extraction] Executing with step 2, categories exist:", !!categories);
      
      // Execute with step 2 - handleExecute will use actualStep logic to ensure step 2 is used
      handleExecute();
    }, 150); // Slightly longer delay to ensure state is updated
  };

  const renderParameterInput = (param: ToolParameter) => {
    const value = params[param.name];
    const error = errors[param.name];

    switch (param.type) {
      case "boolean":
        return (
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={value === true}
              onChange={(e) =>
                setParams({ ...params, [param.name]: e.target.checked })
              }
              className="w-4 h-4 text-blue-600 rounded focus:ring-blue-500"
            />
            <span className="text-sm text-slate-700 dark:text-slate-300">
              {param.description}
            </span>
          </label>
        );

      case "number":
        return (
          <div>
            <input
              type="number"
              value={(value as number) || ""}
              onChange={(e) =>
                setParams({
                  ...params,
                  [param.name]: e.target.value ? Number(e.target.value) : undefined,
                })
              }
              placeholder={param.description}
              className={cn(
                "w-full px-3 py-2 text-sm border rounded-lg",
                "bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700",
                "text-slate-900 dark:text-slate-100",
                "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                error && "border-red-500"
              )}
            />
            {error && (
              <p className="mt-1 text-xs text-red-500">{error}</p>
            )}
          </div>
        );

      case "array":
        // If array has enum options, use checkboxes
        if (param.enum && param.enum.length > 0) {
          const selectedValues = Array.isArray(value) ? (value as string[]) : [];
          return (
            <div className="space-y-2">
              {param.enum.map((option) => (
                <label
                  key={option}
                  className="flex items-center gap-2 cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={selectedValues.includes(option)}
                    onChange={(e) => {
                      const newValues = e.target.checked
                        ? [...selectedValues, option]
                        : selectedValues.filter((v) => v !== option);
                      setParams({
                        ...params,
                        [param.name]: newValues,
                      });
                    }}
                    className="w-4 h-4 text-blue-600 border-slate-300 rounded focus:ring-blue-500"
                  />
                  <span className="text-sm text-slate-700 dark:text-slate-300">
                    {option}
                  </span>
                </label>
              ))}
              {error && (
                <p className="mt-1 text-xs text-red-500">{error}</p>
              )}
            </div>
          );
        }
        // Otherwise use textarea for free-form array input
        return (
          <div>
            <textarea
              value={Array.isArray(value) ? value.join("\n") : ""}
              onChange={(e) =>
                setParams({
                  ...params,
                  [param.name]: e.target.value
                    .split("\n")
                    .filter((v) => v.trim())
                    .map((v) => v.trim()),
                })
              }
              placeholder={`每行一个值\n${param.description}`}
              rows={4}
              className={cn(
                "w-full px-3 py-2 text-sm border rounded-lg font-mono",
                "bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700",
                "text-slate-900 dark:text-slate-100",
                "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                error && "border-red-500"
              )}
            />
            {error && (
              <p className="mt-1 text-xs text-red-500">{error}</p>
            )}
          </div>
        );

      case "string":
      default:
        // Special handling for pdf_file parameter: file upload
        if (param.name === "pdf_file" && tool.id === "data_extraction") {
          return (
            <div>
              <input
                type="file"
                ref={fileInputRef}
                accept=".pdf,application/pdf,.xml,application/xml,text/xml"
                onChange={handleFileUpload}
                className="hidden"
                id={`file-input-${param.name}`}
              />
              {uploadedFile ? (
                <div className="space-y-2">
                  <div className="flex items-center gap-2 p-3 border rounded-lg bg-slate-50 dark:bg-slate-800 border-slate-200 dark:border-slate-700">
                    <FileText className="h-4 w-4 text-slate-500" />
                    <span className="flex-1 text-sm text-slate-700 dark:text-slate-300 truncate">
                      {uploadedFile.name} ({(uploadedFile.size / 1024 / 1024).toFixed(2)} MB)
                    </span>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={handleRemoveFile}
                      className="h-6 w-6 p-0"
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  </div>
                  {tool.id === "data_extraction" && extractionType === "material_extraction" && extractionStep === 1 && !categories && (
                    <Button
                      onClick={handleExecute}
                      disabled={executing}
                      className="w-full bg-blue-500 hover:bg-blue-600 text-white"
                    >
                      {executing ? (
                        <>
                          <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                          分析中...
                        </>
                      ) : (
                        <>
                          <Play className="h-4 w-4 mr-2" />
                          主题分析
                        </>
                      )}
                    </Button>
                  )}
                </div>
              ) : (
                <label
                  htmlFor={`file-input-${param.name}`}
                  className={cn(
                    "flex items-center justify-center gap-2 p-4 border-2 border-dashed rounded-lg cursor-pointer",
                    "bg-white dark:bg-slate-800 border-slate-300 dark:border-slate-600",
                    "hover:border-blue-500 hover:bg-blue-50 dark:hover:bg-blue-950/30",
                    "transition-colors",
                    error && "border-red-500"
                  )}
                >
                  <Upload className="h-5 w-5 text-slate-400" />
                  <span className="text-sm text-slate-600 dark:text-slate-400">
                    点击上传PDF或XML文件
                  </span>
                </label>
              )}
              {error && param.name === "pdf_file" && (
                <p className="mt-1 text-xs text-red-500">{error}</p>
              )}
              {errors[param.name] && (
                <p className="mt-1 text-xs text-red-500">{errors[param.name]}</p>
              )}
            </div>
          );
        }
        // Special handling for model_name parameter: use dynamic model list from config
        if (param.name === "model_name" && availableModels.length > 0) {
          return (
            <div>
              <select
                value={value ? (value as string) : ""}
                onChange={(e) => {
                  const newValue = e.target.value;
                  setParams({
                    ...params,
                    [param.name]: newValue === "" ? undefined : newValue,
                  });
                }}
                className={cn(
                  "w-full px-3 py-2 text-sm border rounded-lg",
                  "bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700",
                  "text-slate-900 dark:text-slate-100",
                  "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                  error && "border-red-500"
                )}
              >
                <option value="">使用默认模型</option>
                {availableModels.map((model) => (
                  <option key={model.name} value={model.name}>
                    {model.name} {model.model ? `(${model.model})` : ""}
                  </option>
                ))}
              </select>
              {error && (
                <p className="mt-1 text-xs text-red-500">{error}</p>
              )}
            </div>
          );
        }
        // Standard enum handling
        if (param.enum) {
          return (
            <div>
              <select
                value={(value as string) || ""}
                onChange={(e) =>
                  setParams({ ...params, [param.name]: e.target.value })
                }
                className={cn(
                  "w-full px-3 py-2 text-sm border rounded-lg",
                  "bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700",
                  "text-slate-900 dark:text-slate-100",
                  "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                  error && "border-red-500"
                )}
              >
                <option value="">请选择...</option>
                {param.enum.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
              {error && (
                <p className="mt-1 text-xs text-red-500">{error}</p>
              )}
            </div>
          );
        }
        // Use textarea for multi-line text parameters
        if (
          param.name === "prompt" ||
          param.name === "extraction_prompt" ||
          param.name === "json_schema"
        ) {
          return (
            <div>
              <textarea
                value={(value as string) || ""}
                onChange={(e) =>
                  setParams({ ...params, [param.name]: e.target.value })
                }
                placeholder={param.description}
                rows={param.name === "json_schema" ? 8 : 6}
                className={cn(
                  "w-full px-3 py-2 text-sm border rounded-lg resize-y font-mono",
                  "bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700",
                  "text-slate-900 dark:text-slate-100",
                  "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                  error && "border-red-500"
                )}
              />
              {error && (
                <p className="mt-1 text-xs text-red-500">{error}</p>
              )}
            </div>
          );
        }
        // Standard text input
        return (
          <div>
            <input
              type="text"
              value={(value as string) || ""}
              onChange={(e) =>
                setParams({ ...params, [param.name]: e.target.value })
              }
              placeholder={param.description}
              className={cn(
                "w-full px-3 py-2 text-sm border rounded-lg",
                "bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700",
                "text-slate-900 dark:text-slate-100",
                "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                error && "border-red-500"
              )}
            />
            {error && (
              <p className="mt-1 text-xs text-red-500">{error}</p>
            )}
          </div>
        );
    }
  };

  const Icon = tool.icon;

  return (
    <div className="flex h-full w-full flex-col bg-white dark:bg-slate-900">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-700">
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <Button
            variant="ghost"
            size="icon"
            onClick={onBack || onClose}
            className="h-8 w-8 flex-shrink-0"
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div className="p-2 rounded-lg bg-blue-50 dark:bg-blue-950/30 flex-shrink-0">
            <Icon className="h-5 w-5 text-blue-600 dark:text-blue-400" />
          </div>
          {tool.id === "data_extraction" && extractionType === "material_extraction" && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setShowHistory(!showHistory);
                if (!showHistory) {
                  loadHistoryRecords();
                }
              }}
              className="h-8 flex-shrink-0"
            >
              <History className="h-4 w-4 mr-2" />
              运行历史
            </Button>
          )}
          {(tool.id === "image_gen" || tool.id === "ppt_generator") && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setShowToolHistory(!showToolHistory);
                if (!showToolHistory) {
                  loadToolHistoryRecords();
                }
              }}
              className="h-8 flex-shrink-0"
              title="加载运行历史"
            >
              <History className="h-4 w-4 mr-2" />
              运行历史
            </Button>
          )}
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              {tool.name}
            </h2>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              {tool.description}
            </p>
          </div>
        </div>
      </div>

      {/* History Records Panel */}
      {showHistory && tool.id === "data_extraction" && extractionType === "material_extraction" && (
        <div className="px-6 py-4 border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 max-h-96 overflow-y-auto">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">历史记录</h3>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowHistory(false)}
              className="h-7 text-xs"
            >
              关闭
            </Button>
          </div>
          {loadingHistory ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-blue-500" />
              <span className="ml-2 text-sm text-slate-600 dark:text-slate-400">加载中...</span>
            </div>
          ) : historyRecords.length === 0 ? (
            <div className="text-center py-8 text-slate-500 dark:text-slate-400">
              <p className="text-sm">暂无历史记录</p>
            </div>
          ) : (
            <div className="space-y-2">
              {historyRecords.map((record) => (
                <div
                  key={record.id}
                  onClick={() => restoreFromRecord(record)}
                  className={cn(
                    "p-3 rounded-lg border cursor-pointer transition-colors",
                    "bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700",
                    "hover:bg-slate-50 dark:hover:bg-slate-700",
                    ((currentTaskId && record.task_id && currentTaskId === record.task_id) || 
                     (currentRecordId === record.id)) && "ring-2 ring-blue-500"
                  )}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-sm font-medium text-slate-900 dark:text-slate-100 truncate">
                          {record.task_name || record.file_name || "未命名任务"}
                        </span>
                        <span className={cn(
                          "px-2 py-0.5 rounded text-xs",
                          record.extraction_step === 3
                            ? "bg-green-100 dark:bg-green-900/50 text-green-700 dark:text-green-400"
                            : record.extraction_step === 2
                            ? "bg-blue-100 dark:bg-blue-900/50 text-blue-700 dark:text-blue-400"
                            : "bg-orange-100 dark:bg-orange-900/50 text-orange-700 dark:text-orange-400"
                        )}>
                          步骤 {record.extraction_step}/3
                        </span>
                      </div>
                      <div className="text-xs text-slate-500 dark:text-slate-400 space-y-0.5">
                        {record.file_name && (
                          <div className="flex items-center gap-1">
                            <FileText className="h-3 w-3" />
                            <span className="truncate">{record.file_name}</span>
                            {record.file_size && (
                              <span className="text-slate-400">
                                ({(record.file_size / 1024 / 1024).toFixed(2)} MB)
                              </span>
                            )}
                          </div>
                        )}
                        {record.created_at && (
                          <div>
                            {new Date(record.created_at).toLocaleString("zh-CN")}
                          </div>
                        )}
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={(e) => handleDeleteRecord(record.id, e)}
                      className="h-7 w-7 text-slate-400 hover:text-red-500"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 文生图 / PPT 生成 历史记录面板 */}
      {showToolHistory && (tool.id === "image_gen" || tool.id === "ppt_generator") && (
        <div className="px-6 py-4 border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 max-h-96 overflow-y-auto">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">历史记录</h3>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowToolHistory(false)}
              className="h-7 text-xs"
            >
              关闭
            </Button>
          </div>
          {loadingToolHistory ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-blue-500" />
              <span className="ml-2 text-sm text-slate-600 dark:text-slate-400">加载中...</span>
            </div>
          ) : toolHistoryRecords.length === 0 ? (
            <div className="text-center py-8 text-slate-500 dark:text-slate-400">
              <p className="text-sm">暂无历史记录</p>
            </div>
          ) : (
            <div className="space-y-2">
              {toolHistoryRecords.map((record) => {
                const title =
                  tool.id === "image_gen"
                    ? (record.params_json && typeof record.params_json === "object" && "prompt" in record.params_json
                        ? String((record.params_json as { prompt?: string }).prompt ?? "").slice(0, 40) + "..."
                        : "文生图")
                    : (record.params_json && typeof record.params_json === "object" && "topic" in record.params_json
                        ? String((record.params_json as { topic?: string }).topic ?? "").slice(0, 40) + "..."
                        : "PPT");
                return (
                  <div
                    key={record.id}
                    onClick={() => restoreFromToolRecord(record)}
                    className={cn(
                      "p-3 rounded-lg border cursor-pointer transition-colors",
                      "bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700",
                      "hover:bg-slate-50 dark:hover:bg-slate-700"
                    )}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium text-slate-900 dark:text-slate-100 truncate">
                          {title || "未命名"}
                        </div>
                        {record.created_at && (
                          <div className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                            {new Date(record.created_at).toLocaleString("zh-CN")}
                          </div>
                        )}
                      </div>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={(e) => handleDeleteToolRecord(record.id, e)}
                        className="h-7 w-7 text-slate-400 hover:text-red-500"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="w-full">
          {/* Extraction Type Selector for data_extraction */}
          {tool.id === "data_extraction" && (
            <div className="mb-6 p-4 bg-slate-50 dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
              <label className="block text-sm font-semibold text-slate-900 dark:text-slate-100 mb-3">
                抽取类型
              </label>
              <div className="flex gap-4">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="extraction_type"
                    value="prompt_extraction"
                    checked={extractionType === "prompt_extraction"}
                    onChange={(e) => {
                      setExtractionType(e.target.value);
                      setParams((prev) => ({
                        ...prev,
                        extraction_type: e.target.value,
                      }));
                      setExtractionStep(1);
                      setCategories(null);
                      setSelectedCategories({ materials: [], processes: [], properties: [] });
                      setTableData([]);
                    }}
                    className="w-4 h-4 text-blue-600"
                  />
                  <span className="text-sm text-slate-700 dark:text-slate-300">提示词抽取</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="extraction_type"
                    value="material_extraction"
                    checked={extractionType === "material_extraction"}
                    onChange={(e) => {
                      setExtractionType(e.target.value);
                      setParams((prev) => ({
                        ...prev,
                        extraction_type: e.target.value,
                        extraction_step: 1,
                      }));
                      setExtractionStep(1);
                      setCategories(null);
                      setSelectedCategories({ materials: [], processes: [], properties: [] });
                      setTableData([]);
                    }}
                    className="w-4 h-4 text-blue-600"
                  />
                  <span className="text-sm text-slate-700 dark:text-slate-300">材料数据抽取</span>
                </label>
              </div>
            </div>
          )}

          {/* Step Indicator for Material Extraction */}
          {tool.id === "data_extraction" && extractionType === "material_extraction" && (
            <div className="mb-6 p-4 bg-slate-50 dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
              <div className="flex items-center justify-between">
                {/* Step 1 */}
                <div className="flex items-center flex-1">
                  <div className={cn(
                    "flex items-center justify-center w-8 h-8 rounded-full border-2 shrink-0",
                    extractionStep >= 1 
                      ? "bg-blue-500 border-blue-500 text-white" 
                      : "bg-white dark:bg-slate-800 border-slate-300 dark:border-slate-600 text-slate-500"
                  )}>
                    {extractionStep > 1 ? (
                      <CheckCircle2 className="h-5 w-5" />
                    ) : (
                      <span className="text-sm font-semibold">1</span>
                    )}
                  </div>
                  <div className={cn(
                    "flex-1 h-1 mx-2",
                    extractionStep > 1 ? "bg-blue-500" : "bg-slate-300 dark:bg-slate-600"
                  )} />
                  <span className={cn(
                    "text-sm font-medium shrink-0",
                    extractionStep >= 1 
                      ? "text-blue-600 dark:text-blue-400" 
                      : "text-slate-500"
                  )}>
                    类别选择
                  </span>
                </div>
                
                {/* Step 2 */}
                <div 
                  className={cn(
                    "flex items-center flex-1 cursor-pointer transition-opacity",
                    extractionStep >= 2 && (currentTaskId || currentRecordId)
                      ? "hover:opacity-80" 
                      : "cursor-not-allowed opacity-50"
                  )}
                  onClick={() => {
                    if (extractionStep >= 2 && (currentTaskId || currentRecordId)) {
                      handleStepClick(2);
                    }
                  }}
                >
                  <div className={cn(
                    "flex-1 h-1 mx-2",
                    extractionStep >= 2 ? "bg-blue-500" : "bg-slate-300 dark:bg-slate-600"
                  )} />
                  <div className={cn(
                    "flex items-center justify-center w-8 h-8 rounded-full border-2 shrink-0",
                    extractionStep >= 2 
                      ? "bg-blue-500 border-blue-500 text-white" 
                      : "bg-white dark:bg-slate-800 border-slate-300 dark:border-slate-600 text-slate-500"
                  )}>
                    {extractionStep > 2 ? (
                      <CheckCircle2 className="h-5 w-5" />
                    ) : (
                      <span className="text-sm font-semibold">2</span>
                    )}
                  </div>
                  <div className={cn(
                    "flex-1 h-1 mx-2",
                    extractionStep > 2 ? "bg-blue-500" : "bg-slate-300 dark:bg-slate-600"
                  )} />
                  <span className={cn(
                    "text-sm font-medium shrink-0",
                    extractionStep >= 2 
                      ? "text-blue-600 dark:text-blue-400" 
                      : "text-slate-500"
                  )}>
                    抽取数据
                  </span>
                </div>
                
                {/* Step 3 */}
                <div 
                  className={cn(
                    "flex items-center flex-1 cursor-pointer transition-opacity",
                    extractionStep >= 3 && (currentTaskId || currentRecordId)
                      ? "hover:opacity-80" 
                      : "cursor-not-allowed opacity-50"
                  )}
                  onClick={() => {
                    if (extractionStep >= 3 && (currentTaskId || currentRecordId)) {
                      handleStepClick(3);
                    }
                  }}
                >
                  <div className={cn(
                    "flex-1 h-1 mx-2",
                    extractionStep >= 3 ? "bg-blue-500" : "bg-slate-300 dark:bg-slate-600"
                  )} />
                  <div className={cn(
                    "flex items-center justify-center w-8 h-8 rounded-full border-2 shrink-0",
                    extractionStep >= 3 
                      ? "bg-blue-500 border-blue-500 text-white" 
                      : "bg-white dark:bg-slate-800 border-slate-300 dark:border-slate-600 text-slate-500"
                  )}>
                    {extractionStep >= 3 ? (
                      <CheckCircle2 className="h-5 w-5" />
                    ) : (
                      <span className="text-sm font-semibold">3</span>
                    )}
                  </div>
                  <span className={cn(
                    "text-sm font-medium ml-2 shrink-0",
                    extractionStep >= 3 
                      ? "text-blue-600 dark:text-blue-400" 
                      : "text-slate-500"
                  )}>
                    结果展示
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Progress Bar for Material Extraction */}
          {tool.id === "data_extraction" && extractionType === "material_extraction" && executing && extractionProgress > 0 && (
            <div className="mb-6">
              <div className="w-full bg-slate-200 dark:bg-slate-700 rounded-full h-2.5">
                <div
                  className="bg-blue-500 h-2.5 rounded-full transition-all duration-300"
                  style={{ width: `${extractionProgress}%` }}
                />
              </div>
              <p className="text-sm text-slate-600 dark:text-slate-400 mt-2 text-center">
                {extractionStep === 1 ? "正在分析文献..." : "正在抽取数据..."}
              </p>
            </div>
          )}

          {/* Parameters - show pdf_file, model_name for material extraction mode */}
          {/* Always show parameters for material extraction mode, even before categories are extracted */}
          {tool.id === "data_extraction" && extractionType === "material_extraction" && (
            <div className="space-y-5 mb-6">
              {tool.parameters
                .filter((param) => {
                  // Always hide material extraction specific params (managed by UI)
                  if (param.name === "extraction_step" ||
                      param.name === "selected_material_categories" ||
                      param.name === "selected_process_categories" ||
                      param.name === "selected_property_categories") {
                    return false;
                  }
                  // Hide extraction_type from manual input (we have radio buttons)
                  if (param.name === "extraction_type") {
                    return false;
                  }
                  // Hide prompt extraction params when in material extraction mode
                  if (param.name === "extraction_prompt" || 
                      param.name === "json_schema" || 
                      param.name === "optimize_prompt") {
                    return false;
                  }
                  // Hide pdf_url - only support file upload
                  if (param.name === "pdf_url") {
                    return false;
                  }
                  // Show pdf_file, model_name
                  return true;
                })
                .map((param) => (
                <div key={param.name}>
                  <label className="block text-sm font-semibold text-slate-900 dark:text-slate-100 mb-2">
                    {param.name}
                    {param.required && (
                      <span className="text-red-500 ml-1">*</span>
                    )}
                  </label>
                  {renderParameterInput(param)}
                  {param.description && !param.enum && (
                    <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                      {param.description}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Material Extraction Step 1: Category Extraction + Selection */}
          {/* Show category selection UI if we have categories and step >= 1 */}
          {/* Also show when step >= 2 or 3 to display selected categories */}
          {tool.id === "data_extraction" && extractionType === "material_extraction" && categories && (
            <>
              {/* Show categories if available */}
              {categories && (
            <div className="mb-6 space-y-4">
              <div className="p-4 bg-blue-50 dark:bg-blue-950/30 rounded-lg border border-blue-200 dark:border-blue-800">
                <h3 className="text-sm font-semibold text-blue-900 dark:text-blue-100 mb-4">
                  请基于解析结果选择抽取目标:
                </h3>
                
                {/* Materials - Single Selection */}
                {categories.materials.length > 0 && (
                  <div className="mb-4">
                    <div className="flex items-center justify-between mb-2">
                      <label className="text-sm font-medium text-slate-900 dark:text-slate-100">
                        材料类别 <span className="text-slate-500">已选: {selectedCategories.materials.length}/{categories.materials.length}</span>
                      </label>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {categories.materials.map((cat) => (
                        <label
                          key={cat}
                          className={cn(
                            "flex items-center gap-2 px-3 py-1.5 rounded-md border cursor-pointer transition-colors",
                            selectedCategories.materials.includes(cat)
                              ? "bg-blue-100 dark:bg-blue-900/50 border-blue-500"
                              : "hover:bg-blue-50 dark:hover:bg-blue-900/30 border-slate-300 dark:border-slate-600"
                          )}
                        >
                          <input
                            type="radio"
                            name="material_category"
                            checked={selectedCategories.materials.includes(cat)}
                            onChange={() => handleCategoryToggle("materials", cat)}
                            className="w-4 h-4 text-blue-600"
                          />
                          <span className="text-sm text-slate-700 dark:text-slate-300">{cat}</span>
                        </label>
                      ))}
                    </div>
                    {errors.materials && (
                      <p className="mt-1 text-xs text-red-500">{errors.materials}</p>
                    )}
                  </div>
                )}

                {/* Processes - Multiple Selection */}
                {categories.processes.length > 0 && (
                  <div className="mb-4">
                    <div className="flex items-center justify-between mb-2">
                      <label className="text-sm font-medium text-slate-900 dark:text-slate-100">
                        工艺目标 <span className="text-slate-500">已选: {selectedCategories.processes.length}/{categories.processes.length}</span>
                      </label>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleSelectAll("processes")}
                        className="h-6 text-xs"
                      >
                        {categories.processes.every((cat) => selectedCategories.processes.includes(cat))
                          ? "取消全选"
                          : "全选"}
                      </Button>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {categories.processes.map((cat) => (
                        <label
                          key={cat}
                          className="flex items-center gap-2 px-3 py-1.5 rounded-md border cursor-pointer hover:bg-blue-100 dark:hover:bg-blue-900/30 border-slate-300 dark:border-slate-600"
                        >
                          <input
                            type="checkbox"
                            checked={selectedCategories.processes.includes(cat)}
                            onChange={() => handleCategoryToggle("processes", cat)}
                            className="w-4 h-4 text-blue-600"
                          />
                          <span className="text-sm text-slate-700 dark:text-slate-300">{cat}</span>
                        </label>
                      ))}
                    </div>
                  </div>
                )}

                {/* Properties - Multiple Selection */}
                {categories.properties.length > 0 && (
                  <div className="mb-4">
                    <div className="flex items-center justify-between mb-2">
                      <label className="text-sm font-medium text-slate-900 dark:text-slate-100">
                        性能目标 <span className="text-slate-500">已选: {selectedCategories.properties.length}/{categories.properties.length}</span>
                      </label>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleSelectAll("properties")}
                        className="h-6 text-xs"
                      >
                        {categories.properties.every((cat) => selectedCategories.properties.includes(cat))
                          ? "取消全选"
                          : "全选"}
                      </Button>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {categories.properties.map((cat) => (
                        <label
                          key={cat}
                          className="flex items-center gap-2 px-3 py-1.5 rounded-md border cursor-pointer hover:bg-blue-100 dark:hover:bg-blue-900/30 border-slate-300 dark:border-slate-600"
                        >
                          <input
                            type="checkbox"
                            checked={selectedCategories.properties.includes(cat)}
                            onChange={() => handleCategoryToggle("properties", cat)}
                            className="w-4 h-4 text-blue-600"
                          />
                          <span className="text-sm text-slate-700 dark:text-slate-300">{cat}</span>
                        </label>
                      ))}
                    </div>
                  </div>
                )}

                {errors.categories && (
                  <p className="mt-2 text-xs text-red-500">{errors.categories}</p>
                )}

                {/* Selected Categories Summary */}
                {(selectedCategories.materials.length > 0 || selectedCategories.processes.length > 0 || selectedCategories.properties.length > 0) && (
                  <div className="mt-4 p-3 bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
                    <div className="text-sm font-semibold text-blue-600 dark:text-blue-400 mb-2">
                      已选择的抽取目标
                    </div>
                    <div className="space-y-2 text-sm">
                      {selectedCategories.materials.length > 0 && (
                        <div>
                          <span className="font-medium text-slate-700 dark:text-slate-300">材料类别：</span>
                          <span className="text-slate-600 dark:text-slate-400">{selectedCategories.materials.length}项</span>
                          <div className="flex flex-wrap gap-1 mt-1">
                            {selectedCategories.materials.map((cat) => (
                              <span
                                key={cat}
                                className="px-2 py-0.5 bg-blue-100 dark:bg-blue-900/50 text-blue-700 dark:text-blue-300 rounded text-xs"
                              >
                                {cat}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                      {selectedCategories.processes.length > 0 && (
                        <div>
                          <span className="font-medium text-slate-700 dark:text-slate-300">工艺目标：</span>
                          <span className="text-slate-600 dark:text-slate-400">{selectedCategories.processes.length}项</span>
                          <div className="flex flex-wrap gap-1 mt-1">
                            {selectedCategories.processes.map((cat) => (
                              <span
                                key={cat}
                                className="px-2 py-0.5 bg-purple-100 dark:bg-purple-900/50 text-purple-700 dark:text-purple-300 rounded text-xs"
                              >
                                {cat}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                      {selectedCategories.properties.length > 0 && (
                        <div>
                          <span className="font-medium text-slate-700 dark:text-slate-300">性能目标：</span>
                          <span className="text-slate-600 dark:text-slate-400">{selectedCategories.properties.length}项</span>
                          <div className="flex flex-wrap gap-1 mt-1">
                            {selectedCategories.properties.map((cat) => (
                              <span
                                key={cat}
                                className="px-2 py-0.5 bg-green-100 dark:bg-green-900/50 text-green-700 dark:text-green-300 rounded text-xs"
                              >
                                {cat}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* Only show "开始抽取" button if step === 1 (not restored from step 2/3) */}
                {extractionStep === 1 && (
                  <div className="mt-4 flex justify-end">
                    <Button
                      onClick={handleStartExtraction}
                      disabled={executing}
                      className="bg-blue-500 hover:bg-blue-600 text-white"
                    >
                      {executing ? (
                        <>
                          <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                          抽取中...
                        </>
                      ) : (
                        <>
                          开始抽取
                          <ChevronRight className="h-4 w-4 ml-1" />
                        </>
                      )}
                    </Button>
                  </div>
                )}
                
                {/* Show step info if restored from step 2 or 3 */}
                {extractionStep >= 2 && (
                  <div className="mt-4 p-3 bg-slate-100 dark:bg-slate-700 rounded-lg">
                    <div className="text-sm text-slate-600 dark:text-slate-400">
                      {extractionStep === 2 ? "已选择类别，等待抽取数据..." : "类别已选择，数据已抽取"}
                    </div>
                  </div>
                )}
              </div>
            </div>
              )}
            </>
          )}

          {/* Material Extraction Step 2: Data Extraction Progress or Status */}
          {tool.id === "data_extraction" && extractionType === "material_extraction" && extractionStep === 2 && (
            <>
              {executing ? (
                <div className="mb-6 p-4 bg-slate-50 dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
                  <div className="text-center">
                    <Loader2 className="h-8 w-8 animate-spin text-blue-500 mx-auto mb-2" />
                    <p className="text-sm text-slate-600 dark:text-slate-400">
                      正在抽取数据，请稍候...
                    </p>
                  </div>
                </div>
              ) : (
                // Show status when step 2 is restored but not executing
                <div className="mb-6 p-4 bg-blue-50 dark:bg-blue-950/30 rounded-lg border border-blue-200 dark:border-blue-800">
                  <div className="flex items-center gap-2 mb-2">
                    <CheckCircle2 className="h-5 w-5 text-blue-500" />
                    <span className="text-sm font-semibold text-blue-900 dark:text-blue-100">
                      类别已选择，等待抽取数据
                    </span>
                  </div>
                  {selectedCategories && (
                    <div className="mt-3 space-y-2 text-sm">
                      {selectedCategories.materials.length > 0 && (
                        <div>
                          <span className="font-medium text-slate-700 dark:text-slate-300">已选材料类别：</span>
                          <span className="text-slate-600 dark:text-slate-400 ml-2">
                            {selectedCategories.materials.join(", ")}
                          </span>
                        </div>
                      )}
                      {selectedCategories.processes.length > 0 && (
                        <div>
                          <span className="font-medium text-slate-700 dark:text-slate-300">已选工艺目标：</span>
                          <span className="text-slate-600 dark:text-slate-400 ml-2">
                            {selectedCategories.processes.length} 项
                          </span>
                        </div>
                      )}
                      {selectedCategories.properties.length > 0 && (
                        <div>
                          <span className="font-medium text-slate-700 dark:text-slate-300">已选性能目标：</span>
                          <span className="text-slate-600 dark:text-slate-400 ml-2">
                            {selectedCategories.properties.length} 项
                          </span>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </>
          )}


          {/* Parameters - hide for data_extraction material_extraction and ppt_generator (custom UI) */}
          {!(tool.id === "data_extraction" && extractionType === "material_extraction") && tool.id !== "ppt_generator" && (
            <div className="space-y-5 mb-6">
              {tool.parameters
                .filter((param) => {
                  // Always hide material extraction specific params (managed by UI)
                  if (param.name === "extraction_step" ||
                      param.name === "selected_material_categories" ||
                      param.name === "selected_process_categories" ||
                      param.name === "selected_property_categories") {
                    return false;
                  }
                  // Hide extraction_type from manual input (we have radio buttons)
                  if (param.name === "extraction_type") {
                    return false;
                  }
                  // Hide pdf_url - only support file upload
                  if (param.name === "pdf_url") {
                    return false;
                  }
                  // Show all other params for prompt extraction mode
                  return true;
                })
                .map((param) => (
                <div key={param.name}>
                  <label className="block text-sm font-semibold text-slate-900 dark:text-slate-100 mb-2">
                    {param.name}
                    {param.required && (
                      <span className="text-red-500 ml-1">*</span>
                    )}
                  </label>
                  {renderParameterInput(param)}
                  {param.description && !param.enum && (
                    <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                      {param.description}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Execute Button - hide for data_extraction material_extraction and ppt_generator (custom buttons) */}
          {!(tool.id === "data_extraction" && extractionType === "material_extraction") && tool.id !== "ppt_generator" && (
          <div className="flex items-center justify-end gap-2 mb-6">
            <Button
              onClick={handleExecute}
              disabled={executing}
              className="bg-blue-500 hover:bg-blue-600 text-white"
            >
              {executing ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  执行中...
                </>
              ) : (
                <>
                  <Play className="h-4 w-4 mr-2" />
                  执行
                </>
              )}
            </Button>
          </div>
          )}

          {/* PPT Generator: step 1 = 输入主题, step 2 = 确认大纲, step 3 = 下载 */}
          {tool.id === "ppt_generator" && (
            <div className="space-y-5 mb-6">
              {pptStep === 1 && (
                <>
                  <div>
                    <label className="block text-sm font-semibold text-slate-900 dark:text-slate-100 mb-2">
                      模式
                    </label>
                    <select
                      value={(params["engine"] as string) || "slide_deck"}
                      onChange={(e) => setParams((prev) => ({ ...prev, engine: e.target.value }))}
                      className={cn(
                        "w-full max-w-xs px-3 py-2 text-sm border rounded-lg",
                        "bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700",
                        "text-slate-900 dark:text-slate-100"
                      )}
                    >
                      <option value="slide_deck">整页图幻灯片（PPTX/PDF）</option>
                      <option value="simple">文字型 PPT</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-semibold text-slate-900 dark:text-slate-100 mb-2">
                      一句话主题
                    </label>
                    <input
                      type="text"
                      value={(params["topic"] as string) || ""}
                      onChange={(e) => setParams((prev) => ({ ...prev, topic: e.target.value }))}
                      placeholder="例如：钙钛矿太阳能电池研究进展"
                      className={cn(
                        "w-full px-3 py-2 text-sm border rounded-lg",
                        "bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700",
                        "text-slate-900 dark:text-slate-100",
                        "focus:outline-none focus:ring-2 focus:ring-blue-500"
                      )}
                    />
                  </div>
                  {(params["engine"] as string) === "slide_deck" && (
                    <>
                      <div>
                        <label className="block text-sm font-semibold text-slate-900 dark:text-slate-100 mb-2">
                          长文/Markdown（可选，与主题二选一）
                        </label>
                        <textarea
                          value={(params["content"] as string) || ""}
                          onChange={(e) => setParams((prev) => ({ ...prev, content: e.target.value }))}
                          rows={4}
                          placeholder="可粘贴长文或 Markdown，将据此生成大纲"
                          className={cn(
                            "w-full px-3 py-2 text-sm border rounded-lg",
                            "bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700",
                            "text-slate-900 dark:text-slate-100",
                            "focus:outline-none focus:ring-2 focus:ring-blue-500"
                          )}
                        />
                      </div>
                      <div className="grid grid-cols-2 gap-3 max-w-md">
                        <div>
                          <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">风格</label>
                          <select
                            value={(params["style"] as string) || "blueprint"}
                            onChange={(e) => setParams((prev) => ({ ...prev, style: e.target.value }))}
                            className={cn(
                              "w-full px-2 py-1.5 text-sm border rounded",
                              "bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700"
                            )}
                          >
                            <option value="blueprint">blueprint</option>
                            <option value="minimal">minimal</option>
                            <option value="hand-drawn">hand-drawn</option>
                          </select>
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">受众</label>
                          <select
                            value={(params["audience"] as string) || "general"}
                            onChange={(e) => setParams((prev) => ({ ...prev, audience: e.target.value }))}
                            className={cn(
                              "w-full px-2 py-1.5 text-sm border rounded",
                              "bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700"
                            )}
                          >
                            <option value="general">general</option>
                            <option value="beginners">beginners</option>
                            <option value="intermediate">intermediate</option>
                            <option value="experts">experts</option>
                            <option value="executives">executives</option>
                          </select>
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">页数</label>
                          <input
                            type="number"
                            min={3}
                            max={20}
                            value={(params["slides"] as number) ?? 8}
                            onChange={(e) =>
                              setParams((prev) => ({ ...prev, slides: parseInt(e.target.value, 10) || 8 }))
                            }
                            className={cn(
                              "w-full px-2 py-1.5 text-sm border rounded",
                              "bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700"
                            )}
                          />
                        </div>
                      </div>
                    </>
                  )}
                  <Button
                    onClick={handleExecute}
                    disabled={
                      executing ||
                      !((params["topic"] as string)?.trim() || (params["content"] as string)?.trim())
                    }
                    className="bg-blue-500 hover:bg-blue-600 text-white"
                  >
                    {executing ? (
                      <>
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                        生成中...
                      </>
                    ) : (
                      <>
                        <Play className="h-4 w-4 mr-2" />
                        生成大纲
                      </>
                    )}
                  </Button>
                </>
              )}
              {pptStep === 2 && (
                <>
                  <div>
                    <label className="block text-sm font-semibold text-slate-900 dark:text-slate-100 mb-2">
                      大纲（可编辑后再生成 PPT）
                    </label>
                    <textarea
                      value={outlineContent}
                      onChange={(e) => setOutlineContent(e.target.value)}
                      rows={14}
                      className={cn(
                        "w-full px-3 py-2 text-sm border rounded-lg font-mono",
                        "bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700",
                        "text-slate-900 dark:text-slate-100",
                        "focus:outline-none focus:ring-2 focus:ring-blue-500"
                      )}
                    />
                  </div>
                  <Button
                    onClick={handleExecute}
                    disabled={executing || !outlineContent.trim()}
                    className="bg-blue-500 hover:bg-blue-600 text-white"
                  >
                    {executing ? (
                      <>
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                        生成中...
                      </>
                    ) : (
                      <>
                        <Play className="h-4 w-4 mr-2" />
                        {(params["engine"] as string) === "slide_deck"
                          ? "确认并生成图片与 PPTX/PDF"
                          : "确认生成 PPT"}
                      </>
                    )}
                  </Button>
                </>
              )}
              {pptStep === 3 && (pptDownloadUrl || pptPdfDownloadUrl) && (
                <div className="p-4 rounded-lg border bg-green-50 dark:bg-green-950/20 border-green-200 dark:border-green-800 space-y-4">
                  <p className="text-sm font-semibold text-green-700 dark:text-green-400">
                    {(params["engine"] as string) === "slide_deck" ? "幻灯片已生成" : "PPT 已生成"}
                  </p>
                  {pptSlidesPreviewUrls.length > 0 && (
                    <div>
                      <p className="text-xs font-medium text-slate-600 dark:text-slate-400 mb-2">每页预览</p>
                      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 max-h-64 overflow-y-auto">
                        {pptSlidesPreviewUrls.map((url, i) => (
                          <a
                            key={i}
                            href={url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="block rounded border border-slate-200 dark:border-slate-700 overflow-hidden"
                          >
                            <img
                              src={url}
                              alt={`Slide ${i + 1}`}
                              className="w-full h-24 object-cover object-center"
                            />
                          </a>
                        ))}
                      </div>
                    </div>
                  )}
                  <div className="flex flex-wrap gap-3">
                    {pptDownloadUrl && (
                      <a
                        href={pptDownloadUrl}
                        download
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-2 text-blue-600 dark:text-blue-400 hover:underline"
                      >
                        <Download className="h-4 w-4" />
                        {pptPdfDownloadUrl ? "下载 PPTX" : "下载 PPT"}
                      </a>
                    )}
                    {pptPdfDownloadUrl && (
                      <a
                        href={pptPdfDownloadUrl}
                        download
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-2 text-blue-600 dark:text-blue-400 hover:underline"
                      >
                        <Download className="h-4 w-4" />
                        下载 PDF
                      </a>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Material Extraction Step 3: Result Display */}
          {tool.id === "data_extraction" &&
            extractionType === "material_extraction" &&
            extractionStep === 3 && (
              <div className="mb-6">
                {(() => {
                  console.log("[Data Extraction] Rendering Step 3:", {
                    extractionStep,
                    tableDataLength: tableData?.length || 0,
                    tableData: tableData,
                    hasTableData: tableData && Array.isArray(tableData) && tableData.length > 0,
                    tableDataType: Array.isArray(tableData) ? "array" : typeof tableData,
                  });
                  return null;
                })()}
                <div className="p-4 rounded-lg border bg-green-50 dark:bg-green-950/20 border-green-200 dark:border-green-800">
                  <div className="flex items-center justify-between mb-4">
                    <span className="text-sm font-semibold text-green-700 dark:text-green-400">
                      {tableData && Array.isArray(tableData) && tableData.length > 0 
                        ? `抽取结果（共 ${tableData.length} 条数据）` 
                        : "抽取完成（未找到匹配的数据）"}
                    </span>
                    {tableData && Array.isArray(tableData) && tableData.length > 0 && (
                      <div className="flex gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={handleDownloadCsv}
                          className="h-7 text-xs"
                        >
                          <Download className="h-3 w-3 mr-1" />
                          下载CSV
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={handleDownloadJson}
                          className="h-7 text-xs"
                        >
                          <Download className="h-3 w-3 mr-1" />
                          下载JSON
                        </Button>
                      </div>
                    )}
                  </div>
                  {tableData && Array.isArray(tableData) && tableData.length > 0 ? (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm border-collapse">
                        <thead>
                          <tr className="bg-slate-100 dark:bg-slate-800">
                            <th className="px-4 py-2 text-left border border-slate-300 dark:border-slate-600 font-semibold text-slate-900 dark:text-slate-100">
                              材料
                            </th>
                            <th className="px-4 py-2 text-left border border-slate-300 dark:border-slate-600 font-semibold text-slate-900 dark:text-slate-100">
                              工艺
                            </th>
                            <th className="px-4 py-2 text-left border border-slate-300 dark:border-slate-600 font-semibold text-slate-900 dark:text-slate-100">
                              性能
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {tableData.map((row, index) => (
                            <tr
                              key={index}
                              className="hover:bg-slate-50 dark:hover:bg-slate-800/50"
                            >
                              <td className="px-4 py-2 border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300">
                                {row.material || "-"}
                              </td>
                              <td className="px-4 py-2 border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300">
                                {row.process || "-"}
                              </td>
                              <td className="px-4 py-2 border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300">
                                {row.property || "-"}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div className="text-center py-8 text-slate-500 dark:text-slate-400">
                      <p className="text-sm">未找到与所选类别匹配的数据</p>
                      <p className="text-xs mt-2">请尝试选择其他类别或检查文献内容</p>
                    </div>
                  )}
                </div>
              </div>
            )}

          {/* Result */}
          {(result || error) && (
            <div className="mb-6">
              <div
                className={cn(
                  "p-4 rounded-lg border",
                  error
                    ? "bg-red-50 dark:bg-red-950/20 border-red-200 dark:border-red-800"
                    : "bg-green-50 dark:bg-green-950/20 border-green-200 dark:border-green-800"
                )}
              >
                <div className="flex items-start gap-2">
                  {error ? (
                    <AlertCircle className="h-5 w-5 text-red-500 flex-shrink-0 mt-0.5" />
                  ) : (
                    <CheckCircle2 className="h-5 w-5 text-green-500 flex-shrink-0 mt-0.5" />
                  )}
                  <div className="flex-1">
                    {error ? (
                      <p
                        className={cn(
                          "text-sm whitespace-pre-wrap break-words",
                          "text-red-700 dark:text-red-400"
                        )}
                      >
                        {error}
                      </p>
                    ) : (
                      <div>
                        {/* Don't show result text for material extraction step 2 if we have table data */}
                        {!(
                          tool.id === "data_extraction" &&
                          extractionType === "material_extraction" &&
                          extractionStep === 2 &&
                          tableData.length > 0
                        ) && (
                          <>
                            <div className="flex items-center justify-between mb-2">
                              <span className="text-sm font-semibold text-green-700 dark:text-green-400">
                                执行结果
                              </span>
                              {tool.id === "data_extraction" &&
                                result &&
                                extractionType === "prompt_extraction" && (
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={handleDownloadJson}
                                    className="h-7 text-xs"
                                  >
                                    <Download className="h-3 w-3 mr-1" />
                                    下载JSON
                                  </Button>
                                )}
                            </div>
                            {renderResultContent()}
                          </>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

