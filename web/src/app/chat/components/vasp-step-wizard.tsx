"use client";

import { Loader2, ChevronRight, FileCode, Copy, Download, Upload, Send, RefreshCw, Server, Image, FileWarning, CloudDownload } from "lucide-react";
import { useRef, useState, useEffect } from "react";
import { cn } from "~/lib/utils";
import { executeTool } from "~/core/api/tools";
import { Button } from "~/components/ui/button";

const STEPS = [
  { id: 1, label: "作业类型" },
  { id: 2, label: "结构" },
  { id: 3, label: "准备计算" },
  { id: 4, label: "提交" },
  { id: 5, label: "结果" },
];

/** 作业类型：第一步选择，后续用对应 skill 完成（如能带会生成能带图） */
const JOB_TYPES = [
  { value: "relaxation", label: "结构弛豫", desc: "优化晶格与原子位置，得到平衡结构" },
  { value: "scf", label: "自洽 (SCF)", desc: "单点能计算，得到基态电荷密度与能量" },
  { value: "band", label: "能带 (Band)", desc: "沿高对称 k 路径计算能带，可生成能带图" },
  { value: "dos", label: "态密度 (DOS)", desc: "计算态密度，用于分析电子结构" },
] as const;

const SI_PRESET = {
  lattice_params: { a: 5.43, b: 5.43, c: 5.43, alpha: 90, beta: 90, gamma: 90 },
  species: ["Si", "Si", "Si", "Si", "Si", "Si", "Si", "Si"],
  coords: [
    [0, 0, 0],
    [0.25, 0.25, 0.25],
    [0.5, 0.5, 0],
    [0.75, 0.75, 0.25],
    [0.5, 0, 0.5],
    [0.75, 0.25, 0.75],
    [0, 0.5, 0.5],
    [0.25, 0.75, 0.75],
  ],
  coords_are_cartesian: false,
};


export function VaspStepWizard() {
  const [step, setStep] = useState(1);
  const [flowType] = useState<"local">("local");
  const [poscarContent, setPoscarContent] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<Record<string, unknown> | null>(null);
  const [calcType, setCalcType] = useState<string>("relaxation");
  const [files, setFiles] = useState<Record<string, string>>({});
  const [potcarInfo, setPotcarInfo] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [activeFileTab, setActiveFileTab] = useState<string>("INCAR");
  const [uploadedFileName, setUploadedFileName] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // 步骤 4：HPC 提交
  const [hpcHost, setHpcHost] = useState("");
  const [hpcUser, setHpcUser] = useState("");
  const [hpcRemoteDir, setHpcRemoteDir] = useState("");
  const [hpcJobDirName, setHpcJobDirName] = useState("");
  const [hpcPort, setHpcPort] = useState("22");
  const [hpcKeyPath, setHpcKeyPath] = useState("");
  const [hpcPassword, setHpcPassword] = useState("");
  const [submitResult, setSubmitResult] = useState<{ job_id: string; remote_dir: string } | null>(null);
  const [jobStatus, setJobStatus] = useState<Record<string, unknown> | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);
  const [hpcConfigSource, setHpcConfigSource] = useState<string | null>(null);
  const [hpcConfigLoading, setHpcConfigLoading] = useState(false);
  const [hasPasswordFromConfig, setHasPasswordFromConfig] = useState(false);
  const [bandPlotImage, setBandPlotImage] = useState<string | null>(null);
  const [bandPlotLoading, setBandPlotLoading] = useState(false);
  const [downloadedVasprunContent, setDownloadedVasprunContent] = useState<string | null>(null);
  const [downloadedKpointsContent, setDownloadedKpointsContent] = useState<string | null>(null);
  const [downloadVasprunLoading, setDownloadVasprunLoading] = useState(false);
  const [downloadKpointsLoading, setDownloadKpointsLoading] = useState(false);
  const [jobLogs, setJobLogs] = useState<{
    stderr?: string;
    stdout?: string;
    outcar_tail?: string;
    vasp_scf_log?: string;
    vasp_band_log?: string;
  } | null>(null);
  const [logsLoading, setLogsLoading] = useState(false);
  const bandVasprunRef = useRef<HTMLInputElement>(null);
  const bandKpointsRef = useRef<HTMLInputElement>(null);
  const [selectedVasprunName, setSelectedVasprunName] = useState<string | null>(null);
  const [selectedKpointsName, setSelectedKpointsName] = useState<string | null>(null);

  // 进入步骤 4 时从 VASPilot 配置拉取 HPC/SSH 信息并填充表单
  useEffect(() => {
    if (step !== 4) return;
    setHpcConfigLoading(true);
    setHpcConfigSource(null);
    setHasPasswordFromConfig(false);
    executeTool("vaspilot_get_hpc_config", {})
      .then((raw) => {
        const data = JSON.parse(raw || "{}") as {
          host?: string;
          username?: string;
          port?: number;
          work_dir?: string;
          key_path?: string;
          has_password?: boolean;
          source?: string;
          error?: string;
        };
        if (data.error) {
          setHpcConfigSource(`配置读取失败: ${data.error}`);
          return;
        }
        if (data.host !== undefined) setHpcHost(data.host ?? "");
        if (data.username !== undefined) setHpcUser(data.username ?? "");
        if (data.work_dir !== undefined) setHpcRemoteDir(data.work_dir ?? "");
        if (data.port !== undefined) setHpcPort(String(data.port ?? 22));
        if (data.key_path !== undefined) setHpcKeyPath(data.key_path ?? "");
        setHasPasswordFromConfig(Boolean(data.has_password));
        if (data.has_password) setHpcPassword(""); // 留空表示使用配置中的密码
        setHpcConfigSource(data.source ?? "VASPilot 配置");
      })
      .catch((e) => setHpcConfigSource(`配置读取失败: ${(e as Error).message}`))
      .finally(() => setHpcConfigLoading(false));
  }, [step]);

  const handleUploadStructure = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    setLoading(true);
    setPoscarContent(null);
    setAnalysis(null);
    setUploadedFileName(file.name);
    const nameLower = file.name.toLowerCase();
    const isCif = nameLower.endsWith(".cif");
    try {
      const text = await file.text();
      try {
        const raw = await executeTool("vaspilot_load_structure", {
          file_content: text,
          filename: file.name,
        });
        const data = JSON.parse(raw || "{}") as { poscar_content?: string; analysis?: Record<string, unknown>; error?: string };
        if (data.error) throw new Error(data.error);
        if (data.poscar_content) setPoscarContent(data.poscar_content);
        if (data.analysis) setAnalysis(data.analysis);
      } catch (apiErr) {
        const msg = (apiErr as Error).message || "";
        if (isCif && (msg.includes("not found") || msg.includes("vaspilot_load_structure"))) {
          setError("后端尚未加载 vaspilot_load_structure 工具，无法解析 CIF。请重启后端（如 pm2 restart agentic-backend）后重试。");
          return;
        }
        if (!isCif && (msg.includes("not found") || msg.includes("vaspilot_load_structure"))) {
          setPoscarContent(text);
          const raw = await executeTool("vaspilot_analyze_structure", { poscar_content: text });
          const data = JSON.parse(raw || "{}") as Record<string, unknown> & { error?: string };
          if (data.error) throw new Error(data.error);
          setAnalysis(data as Record<string, unknown>);
          return;
        }
        throw apiErr;
      }
    } catch (err) {
      setError((err as Error).message);
      setPoscarContent(null);
      setAnalysis(null);
    } finally {
      setLoading(false);
      e.target.value = "";
    }
  };

  const handleCreateSiPreset = async () => {
    setError(null);
    setLoading(true);
    setUploadedFileName(null);
    try {
      const raw = await executeTool("vaspilot_create_structure", {
        lattice_params: SI_PRESET.lattice_params,
        species: SI_PRESET.species,
        coords: SI_PRESET.coords,
        coords_are_cartesian: SI_PRESET.coords_are_cartesian,
      });
      const data = JSON.parse(raw || "{}") as { poscar_content?: string; analysis?: Record<string, unknown>; error?: string };
      if (data.error) throw new Error(data.error);
      if (data.poscar_content) setPoscarContent(data.poscar_content);
      if (data.analysis) setAnalysis(data.analysis);
    } catch (e) {
      setError((e as Error).message);
      setPoscarContent(null);
      setAnalysis(null);
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateInputs = async () => {
    if (!poscarContent) {
      setError("请先完成「结构」步骤并选择/创建结构");
      return;
    }
    setError(null);
    setLoading(true);
    setFiles({});
    setPotcarInfo(null);
    try {
      const raw = await executeTool("vaspilot_generate_inputs", {
        poscar_content: poscarContent,
        calc_type: calcType,
        kpoints_density: 40,
        job_name: "vasp_job",
      });
      const data = JSON.parse(raw || "{}") as {
        files?: Record<string, string>;
        potcar_info?: Record<string, unknown>;
        error?: string;
      };
      if (data.error) throw new Error(data.error);
      if (data.files) {
        setFiles(data.files);
        const keys = Object.keys(data.files);
        if (keys.length) setActiveFileTab(keys[0]!);
      }
      if (data.potcar_info) setPotcarInfo(data.potcar_info);
    } catch (e) {
      setError((e as Error).message);
      setFiles({});
    } finally {
      setLoading(false);
    }
  };

  const handleSubmitToHpc = async () => {
    if (!files || Object.keys(files).length === 0) {
      setError("请先在步骤 3 生成输入文件");
      return;
    }
    const host = hpcHost.trim();
    const user = hpcUser.trim();
    const remoteDir = hpcRemoteDir.trim();
    if (!host || !user || !remoteDir) {
      setError("请填写 HPC 主机、用户名、远程工作目录");
      return;
    }
    if (!hpcKeyPath.trim() && !hpcPassword && !hasPasswordFromConfig) {
      setError("请填写 SSH 密钥路径或密码，或在 VASPilot 配置中设置密码");
      return;
    }
    setError(null);
    setLoading(true);
    setSubmitResult(null);
    try {
      const raw = await executeTool("vaspilot_submit_to_hpc", {
        files,
        host,
        username: user,
        remote_work_dir: remoteDir,
        job_dir_name: hpcJobDirName.trim() || undefined,
        port: parseInt(hpcPort, 10) || 22,
        key_path: hpcKeyPath.trim() || undefined,
        password: hpcPassword || (hasPasswordFromConfig ? "__use_config__" : undefined),
      });
      const data = JSON.parse(raw || "{}") as {
        success?: boolean;
        job_id?: string;
        remote_dir?: string;
        error?: string;
      };
      if (data.error) throw new Error(data.error);
      if (data.success && data.job_id) {
        setSubmitResult({ job_id: data.job_id, remote_dir: data.remote_dir || "" });
        setJobStatus(null);
        setStep(5);
      } else {
        throw new Error((data as { error?: string }).error || "提交失败");
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleQueryJobStatus = async () => {
    if (!submitResult?.job_id) return;
    const host = hpcHost.trim();
    const user = hpcUser.trim();
    if (!host || !user) {
      setError("请先填写 HPC 主机与用户名（与提交时一致）");
      return;
    }
    if (!hpcKeyPath.trim() && !hpcPassword && !hasPasswordFromConfig) {
      setError("请填写 SSH 密钥路径或密码");
      return;
    }
    setError(null);
    setStatusLoading(true);
    try {
      const raw = await executeTool("vaspilot_job_status", {
        job_id: submitResult.job_id,
        host,
        username: user,
        port: parseInt(hpcPort, 10) || 22,
        key_path: hpcKeyPath.trim() || undefined,
        password: hpcPassword || (hasPasswordFromConfig ? "__use_config__" : undefined),
      });
      const data = JSON.parse(raw || "{}") as Record<string, unknown> & { error?: string };
      if (data.error) throw new Error(data.error);
      setJobStatus(data);
    } catch (e) {
      setError((e as Error).message);
      setJobStatus(null);
    } finally {
      setStatusLoading(false);
    }
  };

  const handleFetchJobLogs = async () => {
    if (!submitResult?.job_id || !submitResult?.remote_dir) return;
    const host = hpcHost.trim();
    const user = hpcUser.trim();
    if (!host || !user) {
      setError("请先填写 HPC 主机与用户名（与提交时一致）");
      return;
    }
    if (!hpcKeyPath.trim() && !hpcPassword && !hasPasswordFromConfig) {
      setError("请填写 SSH 密钥路径或密码");
      return;
    }
    setError(null);
    setLogsLoading(true);
    setJobLogs(null);
    try {
      const raw = await executeTool("vaspilot_fetch_job_logs", {
        job_id: submitResult.job_id,
        remote_dir: submitResult.remote_dir,
        host,
        username: user,
        port: parseInt(hpcPort, 10) || 22,
        key_path: hpcKeyPath.trim() || undefined,
        password: hpcPassword || (hasPasswordFromConfig ? "__use_config__" : undefined),
      });
      const data = JSON.parse(raw || "{}") as {
        stderr?: string;
        stdout?: string;
        outcar_tail?: string;
        vasp_scf_log?: string;
        vasp_band_log?: string;
        error?: string;
      };
      if (data.error) throw new Error(data.error);
      setJobLogs({
        stderr: data.stderr,
        stdout: data.stdout,
        outcar_tail: data.outcar_tail,
        vasp_scf_log: data.vasp_scf_log,
        vasp_band_log: data.vasp_band_log,
      });
    } catch (e) {
      setError((e as Error).message);
      setJobLogs(null);
    } finally {
      setLogsLoading(false);
    }
  };

  const handleDownloadFromHpc = async (filename: "vasprun.xml" | "KPOINTS") => {
    setError(null);
    if (!submitResult?.remote_dir) {
      setError("无法下载：未找到远程目录，请先提交作业后再试");
      return;
    }
    const host = hpcHost.trim();
    const user = hpcUser.trim();
    if (!host || !user) {
      setError("请先填写 HPC 主机与用户名（与提交时一致）");
      return;
    }
    if (!hpcKeyPath.trim() && !hpcPassword && !hasPasswordFromConfig) {
      setError("请填写 SSH 密钥路径或密码");
      return;
    }
    if (filename === "vasprun.xml") setDownloadVasprunLoading(true);
    else setDownloadKpointsLoading(true);
    try {
      const raw = await executeTool("vaspilot_download_remote_file", {
        remote_dir: submitResult.remote_dir,
        filename,
        host,
        username: user,
        port: parseInt(hpcPort, 10) || 22,
        key_path: hpcKeyPath.trim() || undefined,
        password: hpcPassword || (hasPasswordFromConfig ? "__use_config__" : undefined),
      });
      const data = JSON.parse(raw || "{}") as { success?: boolean; content?: string; error?: string };
      if (data.error) throw new Error(data.error);
      if (!data.success || data.content === undefined) throw new Error("下载失败");
      if (filename === "vasprun.xml") {
        setDownloadedVasprunContent(data.content);
      } else {
        setDownloadedKpointsContent(data.content ?? null);
      }
      const blob = new Blob([data.content], { type: "text/plain" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      if (filename === "vasprun.xml") setDownloadVasprunLoading(false);
      else setDownloadKpointsLoading(false);
    }
  };

  const handleGenerateBandPlot = async () => {
    let vasprunText: string;
    let kpointsText: string | undefined;
    if (downloadedVasprunContent) {
      vasprunText = downloadedVasprunContent;
      kpointsText = downloadedKpointsContent ?? undefined;
    } else {
      const vasprunFile = (bandVasprunRef.current?.files ?? [])[0];
      if (!vasprunFile) {
        setError("请先「从 HPC 下载 vasprun.xml」或选择本地上传的 vasprun.xml 文件");
        return;
      }
      vasprunText = await vasprunFile.text();
      const kpointsFile = (bandKpointsRef.current?.files ?? [])[0];
      if (kpointsFile) kpointsText = await kpointsFile.text();
    }
    setError(null);
    setBandPlotLoading(true);
    setBandPlotImage(null);
    try {
      const raw = await executeTool("vaspilot_plot_band_structure", {
        vasprun_xml_content: vasprunText,
        kpoints_content: kpointsText || undefined,
      });
      const data = JSON.parse(raw || "{}") as { success?: boolean; image_base64?: string; error?: string };
      if (data.error) throw new Error(data.error);
      if (data.success && data.image_base64) setBandPlotImage(data.image_base64);
      else throw new Error("未返回能带图");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBandPlotLoading(false);
    }
  };

  const copyToClipboard = (text: string) => {
    void navigator.clipboard.writeText(text);
  };

  const downloadFile = (filename: string, content: string) => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([content], { type: "text/plain" }));
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const fileTabs = Object.keys(files);
  const canAdvanceToStep3 = flowType === "local" && !!poscarContent;

  return (
    <div className="flex h-full flex-col">
      {/* 步骤条 */}
      <div className="flex items-center gap-1 border-b border-slate-200 dark:border-slate-700 px-4 py-3 bg-slate-50/50 dark:bg-slate-900/30">
        {STEPS.map((s, i) => (
          <div key={s.id} className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setStep(s.id)}
              className={cn(
                "px-2 py-1 rounded text-sm font-medium transition-colors",
                step === s.id
                  ? "bg-blue-500 text-white"
                  : s.id < step
                    ? "text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700"
                    : "text-slate-400 dark:text-slate-500"
              )}
            >
              {s.id}. {s.label}
            </button>
            {i < STEPS.length - 1 && (
              <ChevronRight className="h-4 w-4 text-slate-300 dark:text-slate-600" />
            )}
          </div>
        ))}
      </div>

      {error && (
        <div className="px-4 py-2 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 border-b border-red-200 dark:border-red-800">
          {error}
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-4">
        {/* 步骤 1 - 作业类型：选择后按该类型使用对应 skill 完成（如能带会生成能带图） */}
        {step === 1 && (
          <div className="max-w-2xl space-y-4">
            <h2 className="text-lg font-semibold text-slate-800 dark:text-slate-200">第一步：选择作业类型</h2>
            <p className="text-sm text-slate-600 dark:text-slate-400">
              选择要做的计算类型，后续将按此类型生成输入、提交 HPC，并在结果步骤提供对应分析（如能带类型可生成能带图）。
            </p>
            <div className="grid gap-2">
              {JOB_TYPES.map((j) => (
                <label
                  key={j.value}
                  className={cn(
                    "flex items-start gap-3 p-4 rounded-lg border cursor-pointer transition-colors",
                    calcType === j.value
                      ? "border-blue-500 bg-blue-50 dark:bg-blue-950/40 dark:border-blue-600"
                      : "border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:border-slate-300 dark:hover:border-slate-600"
                  )}
                >
                  <input
                    type="radio"
                    name="jobType"
                    value={j.value}
                    checked={calcType === j.value}
                    onChange={() => setCalcType(j.value)}
                    className="mt-1 rounded-full"
                  />
                  <div>
                    <span className="font-medium text-slate-800 dark:text-slate-200">{j.label}</span>
                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{j.desc}</p>
                  </div>
                </label>
              ))}
            </div>
            <Button onClick={() => setStep(2)}>下一步：结构</Button>
          </div>
        )}

        {/* 步骤 2 - 结构：上传文件或使用预设 */}
        {step === 2 && (
          <div className="max-w-2xl space-y-4">
            <h2 className="text-lg font-semibold text-slate-800 dark:text-slate-200">第二步：上传结构文件</h2>
            <p className="text-sm text-slate-600 dark:text-slate-400">
              上传 POSCAR、CIF 等结构文件，解析后将用于生成 VASP 输入；也可使用预设 Si 金刚石结构。
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <input
                ref={fileInputRef}
                type="file"
                accept=".vasp,.poscar,.POSCAR,.cif,.CIF"
                className="hidden"
                onChange={handleUploadStructure}
              />
              <Button
                type="button"
                variant="outline"
                onClick={() => fileInputRef.current?.click()}
                disabled={loading}
              >
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                上传结构文件
              </Button>
              <span className="text-sm text-slate-500 dark:text-slate-400">支持 POSCAR、CIF</span>
              <span className="text-slate-300 dark:text-slate-600">|</span>
              <Button variant="outline" onClick={handleCreateSiPreset} disabled={loading}>
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                预设 Si 金刚石
              </Button>
            </div>
            {uploadedFileName && !analysis && !loading && (
              <p className="text-sm text-amber-600 dark:text-amber-400">已选文件：{uploadedFileName}，解析失败或格式不支持，请重试或换用预设。</p>
            )}
            {analysis && (
              <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 p-4 space-y-2">
                <h3 className="text-sm font-medium text-slate-700 dark:text-slate-300">
                  结构信息 {uploadedFileName ? `（${uploadedFileName}）` : "（预设 Si）"}
                </h3>
                <pre className="text-xs text-slate-600 dark:text-slate-400 overflow-x-auto whitespace-pre-wrap max-h-48">
                  {JSON.stringify(analysis, null, 2)}
                </pre>
                <Button onClick={() => setStep(3)}>使用此结构，下一步：生成输入文件</Button>
              </div>
            )}
            {!analysis && !loading && (
              <p className="text-sm text-slate-500 dark:text-slate-400">
                请先上传结构文件或点击「预设 Si 金刚石」，再进入下一步生成 INCAR、KPOINTS、POSCAR 等。
              </p>
            )}
          </div>
        )}

        {/* 步骤 3 - 生成输入文件 */}
        {step === 3 && (
          <div className="max-w-3xl space-y-4">
            <h2 className="text-lg font-semibold text-slate-800 dark:text-slate-200">第三步：生成输入文件</h2>
            {!canAdvanceToStep3 && (
              <p className="text-sm text-amber-600 dark:text-amber-400">请先在步骤 2 中上传结构文件或使用预设结构。</p>
            )}
            {canAdvanceToStep3 && (
              <>
                <p className="text-sm text-slate-600 dark:text-slate-400">
                  按步骤 1 选择的作业类型（<strong>{JOB_TYPES.find((j) => j.value === calcType)?.label ?? calcType}</strong>）生成 INCAR、KPOINTS、POSCAR、gen_potcar.sh、submit.sh。
                </p>
                <div className="flex flex-wrap items-center gap-3">
                  <Button onClick={handleGenerateInputs} disabled={loading}>
                    {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileCode className="h-4 w-4" />}
                    生成输入
                  </Button>
                </div>
                {potcarInfo && (
                  <div className="rounded border border-slate-200 dark:border-slate-700 p-3 text-sm">
                    <span className="font-medium text-slate-700 dark:text-slate-300">POTCAR 信息：</span>
                    <pre className="mt-1 text-xs text-slate-600 dark:text-slate-400 overflow-x-auto">
                      {JSON.stringify(potcarInfo, null, 2)}
                    </pre>
                  </div>
                )}
                {fileTabs.length > 0 && (
                  <>
                    <div className="rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
                      <div className="flex flex-wrap gap-1 p-2 bg-slate-100 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700">
                        {fileTabs.map((name) => (
                          <button
                            key={name}
                            type="button"
                            onClick={() => setActiveFileTab(name)}
                            className={cn(
                              "px-3 py-1.5 rounded text-sm",
                              activeFileTab === name
                                ? "bg-white dark:bg-slate-700 shadow text-slate-900 dark:text-slate-100"
                                : "text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700"
                            )}
                          >
                            {name}
                          </button>
                        ))}
                      </div>
                      <div className="relative bg-slate-900 text-slate-100 p-3 min-h-[200px]">
                        <div className="absolute top-2 right-2 flex gap-1">
                          <Button
                            size="sm"
                            variant="secondary"
                            className="h-7 text-xs"
                            onClick={() => copyToClipboard(files[activeFileTab] ?? "")}
                          >
                            <Copy className="h-3 w-3 mr-1" />
                            复制
                          </Button>
                          <Button
                            size="sm"
                            variant="secondary"
                            className="h-7 text-xs"
                            onClick={() => downloadFile(activeFileTab, files[activeFileTab] ?? "")}
                          >
                            <Download className="h-3 w-3 mr-1" />
                            下载
                          </Button>
                        </div>
                        <pre className="text-xs overflow-auto pr-24 whitespace-pre-wrap font-mono">
                          {(files[activeFileTab] ?? "").slice(0, 5000)}
                          {(files[activeFileTab] ?? "").length > 5000 ? "\n\n... (已截断，请下载查看)" : ""}
                        </pre>
                      </div>
                    </div>
                    <Button onClick={() => setStep(4)} className="mt-4">
                      <Send className="h-4 w-4 mr-2" />
                      下一步：提交到 HPC
                    </Button>
                  </>
                )}
              </>
            )}
          </div>
        )}

        {/* 步骤 4 - 提交到 HPC */}
        {step === 4 && (
          <div className="max-w-2xl space-y-4">
            <h2 className="text-lg font-semibold text-slate-800 dark:text-slate-200">第四步：提交到 HPC</h2>
            <p className="text-sm text-slate-600 dark:text-slate-400">
              填写 HPC 登录信息与远程目录，将已生成的输入文件上传并提交 Slurm 作业。
            </p>
            {hpcConfigLoading && (
              <p className="text-sm text-slate-500 dark:text-slate-400 flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                正在读取 VASPilot 主机配置…
              </p>
            )}
            {hpcConfigSource && !hpcConfigLoading && (
              <div className="flex items-center gap-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 px-3 py-2 text-sm text-slate-700 dark:text-slate-300">
                <Server className="h-4 w-4 shrink-0 text-slate-500" />
                <span>
                  以下信息来自 <strong>{hpcConfigSource}</strong>，可直接提交或修改后提交。
                </span>
              </div>
            )}
            {fileTabs.length === 0 ? (
              <p className="text-sm text-amber-600 dark:text-amber-400">请先在步骤 3 生成输入文件。</p>
            ) : (
              <div className="grid gap-4 rounded-lg border border-slate-200 dark:border-slate-700 p-4 bg-slate-50/50 dark:bg-slate-800/30">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label className="text-sm font-medium text-slate-700 dark:text-slate-300">HPC 主机 *</label>
                    <input
                      type="text"
                      value={hpcHost}
                      onChange={(e) => setHpcHost(e.target.value)}
                      placeholder="例如 login.cluster.edu"
                      className="mt-1 w-full rounded border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 px-2 py-1.5 text-sm"
                    />
                  </div>
                  <div>
                    <label className="text-sm font-medium text-slate-700 dark:text-slate-300">用户名 *</label>
                    <input
                      type="text"
                      value={hpcUser}
                      onChange={(e) => setHpcUser(e.target.value)}
                      placeholder="SSH 用户名"
                      className="mt-1 w-full rounded border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 px-2 py-1.5 text-sm"
                    />
                  </div>
                </div>
                <div>
                  <label className="text-sm font-medium text-slate-700 dark:text-slate-300">远程工作目录 *</label>
                  <input
                    type="text"
                    value={hpcRemoteDir}
                    onChange={(e) => setHpcRemoteDir(e.target.value)}
                    placeholder="例如 /home/username/vasp_runs"
                    className="mt-1 w-full rounded border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 px-2 py-1.5 text-sm"
                  />
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label className="text-sm font-medium text-slate-700 dark:text-slate-300">作业子目录名（可选）</label>
                    <input
                      type="text"
                      value={hpcJobDirName}
                      onChange={(e) => setHpcJobDirName(e.target.value)}
                      placeholder="不填则自动生成 vasp_job_日期时间"
                      className="mt-1 w-full rounded border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 px-2 py-1.5 text-sm"
                    />
                  </div>
                  <div>
                    <label className="text-sm font-medium text-slate-700 dark:text-slate-300">SSH 端口</label>
                    <input
                      type="text"
                      value={hpcPort}
                      onChange={(e) => setHpcPort(e.target.value)}
                      placeholder="22"
                      className="mt-1 w-full rounded border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 px-2 py-1.5 text-sm"
                    />
                  </div>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label className="text-sm font-medium text-slate-700 dark:text-slate-300">SSH 私钥路径（可选）</label>
                    <input
                      type="text"
                      value={hpcKeyPath}
                      onChange={(e) => setHpcKeyPath(e.target.value)}
                      placeholder="例如 ~/.ssh/id_rsa"
                      className="mt-1 w-full rounded border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 px-2 py-1.5 text-sm"
                    />
                  </div>
                  <div>
                    <label className="text-sm font-medium text-slate-700 dark:text-slate-300">SSH 密码（可选）</label>
                    <input
                      type="password"
                      value={hpcPassword}
                      onChange={(e) => setHpcPassword(e.target.value)}
                      placeholder={hasPasswordFromConfig ? "已配置密码，留空即使用配置" : "与密钥二选一"}
                      className="mt-1 w-full rounded border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 px-2 py-1.5 text-sm"
                    />
                  </div>
                </div>
                <Button onClick={handleSubmitToHpc} disabled={loading}>
                  {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Send className="h-4 w-4 mr-2" />}
                  上传并提交
                </Button>
              </div>
            )}
          </div>
        )}

        {/* 步骤 5 - 结果 */}
        {step === 5 && (
          <div className="max-w-2xl space-y-4">
            <h2 className="text-lg font-semibold text-slate-800 dark:text-slate-200">第五步：查看结果</h2>
            {submitResult ? (
              <>
                <div className="rounded-lg border border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-950/30 p-4">
                  <p className="text-sm font-medium text-green-800 dark:text-green-200">作业已提交</p>
                  <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
                    作业 ID：<strong>{submitResult.job_id}</strong>
                  </p>
                  <p className="text-xs text-slate-500 dark:text-slate-500 mt-1">
                    远程目录：{submitResult.remote_dir}
                  </p>
                </div>
                <p className="text-sm text-slate-600 dark:text-slate-400">
                  请登录 HPC 使用 <code className="bg-slate-200 dark:bg-slate-700 px-1 rounded">squeue -j {submitResult.job_id}</code> 或
                  <code className="bg-slate-200 dark:bg-slate-700 px-1 rounded ml-1">sacct -j {submitResult.job_id}</code> 查看状态；计算完成后在远程目录查看 OUTCAR、vasprun.xml 等。
                </p>
                <div className="flex flex-wrap items-center gap-3">
                  <Button variant="outline" onClick={handleQueryJobStatus} disabled={statusLoading}>
                    {statusLoading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <RefreshCw className="h-4 w-4 mr-2" />}
                    查询作业状态
                  </Button>
                  <span className="text-xs text-slate-500 dark:text-slate-400">
                    需与提交时使用相同的主机、用户名和认证方式
                  </span>
                </div>
                {jobStatus && (
                  <div className="rounded border border-slate-200 dark:border-slate-700 p-3 text-sm">
                    <span className="font-medium text-slate-700 dark:text-slate-300">当前状态：</span>
                    <pre className="mt-1 text-xs text-slate-600 dark:text-slate-400 overflow-auto">
                      {JSON.stringify(jobStatus, null, 2)}
                    </pre>
                  </div>
                )}
                <div className="flex flex-wrap items-center gap-2">
                  <Button variant="outline" size="sm" onClick={handleFetchJobLogs} disabled={logsLoading}>
                    {logsLoading ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <FileWarning className="h-4 w-4 mr-1" />}
                    查看远程错误/日志
                  </Button>
                  <span className="text-xs text-slate-500 dark:text-slate-400">
                    拉取 vasp_*.err、vasp_*.out 及 OUTCAR 尾部，用于排查 FAILED 作业
                  </span>
                </div>
                {jobLogs && (
                  <div className="rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-950/20 p-4 space-y-3">
                    <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-200">远程日志</h3>
                    <div>
                      <p className="text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">vasp_{submitResult?.job_id}.err（标准错误，优先查看）</p>
                      <pre className="text-xs bg-slate-900 text-slate-100 p-3 rounded overflow-auto max-h-48 whitespace-pre-wrap">
                        {jobLogs.stderr ?? "(无)"}
                      </pre>
                    </div>
                    <div>
                      <p className="text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">vasp_{submitResult?.job_id}.out（标准输出）</p>
                      <pre className="text-xs bg-slate-900 text-slate-100 p-3 rounded overflow-auto max-h-32 whitespace-pre-wrap">
                        {jobLogs.stdout ?? "(无)"}
                      </pre>
                    </div>
                    <div>
                      <p className="text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">OUTCAR 最后 80 行</p>
                      <pre className="text-xs bg-slate-900 text-slate-100 p-3 rounded overflow-auto max-h-48 whitespace-pre-wrap">
                        {jobLogs.outcar_tail ?? "(无)"}
                      </pre>
                    </div>
                    {(jobLogs.vasp_scf_log || jobLogs.vasp_band_log) && (
                      <>
                        <div>
                          <p className="text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">vasp_scf.log 最后 150 行（VASP 未产生 OUTCAR 时优先查看）</p>
                          <pre className="text-xs bg-slate-900 text-slate-100 p-3 rounded overflow-auto max-h-56 whitespace-pre-wrap">
                            {jobLogs.vasp_scf_log ?? "(无)"}
                          </pre>
                        </div>
                        <div>
                          <p className="text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">vasp_band.log 最后 150 行</p>
                          <pre className="text-xs bg-slate-900 text-slate-100 p-3 rounded overflow-auto max-h-56 whitespace-pre-wrap">
                            {jobLogs.vasp_band_log ?? "(无)"}
                          </pre>
                        </div>
                      </>
                    )}
                  </div>
                )}
                {calcType === "band" && (
                  <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-4 space-y-3">
                    <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-200 flex items-center gap-2">
                      <Image className="h-4 w-4" />
                      生成能带图
                    </h3>
                    <p className="text-xs text-slate-600 dark:text-slate-400">
                      计算完成后，点击下方按钮从当前作业的 HPC 远程目录下载 vasprun.xml 与 KPOINTS（会同时保存到本机并用于绘图）；或本地上传后生成能带图。
                    </p>
                    <div className="flex flex-wrap items-center gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        type="button"
                        onClick={() => void handleDownloadFromHpc("vasprun.xml")}
                        disabled={downloadVasprunLoading}
                      >
                        {downloadVasprunLoading ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <CloudDownload className="h-4 w-4 mr-1" />}
                        {downloadVasprunLoading ? "拉取中…" : "从 HPC 下载 vasprun.xml"}
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        type="button"
                        onClick={() => void handleDownloadFromHpc("KPOINTS")}
                        disabled={downloadKpointsLoading}
                      >
                        {downloadKpointsLoading ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <CloudDownload className="h-4 w-4 mr-1" />}
                        {downloadKpointsLoading ? "拉取中…" : "从 HPC 下载 KPOINTS"}
                      </Button>
                      {(downloadedVasprunContent || downloadedKpointsContent) && (
                        <span className="text-xs text-green-600 dark:text-green-400">
                          已拉取 {[downloadedVasprunContent && "vasprun.xml", downloadedKpointsContent && "KPOINTS"].filter(Boolean).join("、")}，可直接点击「生成能带图」
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-slate-500 dark:text-slate-500">或本地上传：</p>
                    <div className="flex flex-wrap items-center gap-2">
                      <input
                        ref={bandVasprunRef}
                        type="file"
                        accept=".xml,.XML,application/xml"
                        className="hidden"
                        onChange={(e) => setSelectedVasprunName(e.target.files?.[0]?.name ?? null)}
                      />
                      <input
                        ref={bandKpointsRef}
                        type="file"
                        accept="*"
                        className="hidden"
                        onChange={(e) => setSelectedKpointsName(e.target.files?.[0]?.name ?? null)}
                      />
                      <Button
                        variant="outline"
                        size="sm"
                        type="button"
                        onClick={() => bandVasprunRef.current?.click()}
                      >
                        选择 vasprun.xml
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        type="button"
                        onClick={() => bandKpointsRef.current?.click()}
                      >
                        选择 KPOINTS（可选）
                      </Button>
                      {(selectedVasprunName || selectedKpointsName) && (
                        <span className="text-xs text-green-600 dark:text-green-400">
                          已选择：{[selectedVasprunName, selectedKpointsName].filter(Boolean).join("、")}
                        </span>
                      )}
                      <Button
                        size="sm"
                        type="button"
                        onClick={() => void handleGenerateBandPlot()}
                        disabled={bandPlotLoading || (!downloadedVasprunContent && !selectedVasprunName)}
                      >
                        {bandPlotLoading ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <Image className="h-4 w-4 mr-1" />}
                        生成能带图
                      </Button>
                    </div>
                    {!downloadedVasprunContent && !selectedVasprunName && (
                      <p className="text-xs text-amber-600 dark:text-amber-400">
                        请先「从 HPC 下载 vasprun.xml」或点击「选择 vasprun.xml」选择本机文件后再点「生成能带图」。
                      </p>
                    )}
                    {bandPlotImage && (
                      <div className="mt-2">
                        <img
                          src={`data:image/png;base64,${bandPlotImage}`}
                          alt="能带图"
                          className="max-w-full rounded border border-slate-200 dark:border-slate-600"
                        />
                      </div>
                    )}
                  </div>
                )}
              </>
            ) : (
              <p className="text-sm text-slate-500 dark:text-slate-400">
                尚未提交作业。请先在步骤 4 填写 HPC 信息并点击「上传并提交」。
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
