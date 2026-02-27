#!/usr/bin/env python3
"""
能带流程完整脚本：生成输入文件 → 提交 HPC → 轮询状态 → 下载 vasprun.xml → 生成能带图。
默认跑完整流程（提交后轮询直到结束、下载 xml、画图）。不依赖前端。

用法:
  # 完整流程：内置 Si2 → 生成输入并写入 out_dir → 提交 → 轮询 → 下载 xml → 画能带图
  uv run python scripts/run_band_workflow.py

  # 指定 POSCAR，完整流程，结果保存到指定目录
  uv run python scripts/run_band_workflow.py --poscar path/to/POSCAR --out-dir ./band_out

  # 只生成输入文件到 out_dir，不提交（检查 KPOINTS/INCAR/submit.sh）
  uv run python scripts/run_band_workflow.py --no-submit

  # 提交但不轮询（只提交，不查状态、不下载、不画图）
  uv run python scripts/run_band_workflow.py --no-poll

  # 只重跑画图：从 out-dir 读取已有 vasprun.xml、KPOINTS，生成 band_structure.png
  uv run python scripts/run_band_workflow.py --out-dir band_workflow_out --plot-only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKILL_PATH = PROJECT_ROOT / "skills" / "vaspilot-skill"


def _ensure_skill():
    if str(SKILL_PATH) not in sys.path:
        sys.path.insert(0, str(SKILL_PATH))
    # 确保从 skill 目录加载 tools，以便 skill_package 和 config 路径正确
    os.chdir(SKILL_PATH)


def _load_tools():
    _ensure_skill()
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "skill_tools_vaspilot",
        SKILL_PATH / "tools.py",
        submodule_search_locations=[str(SKILL_PATH)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load skills/vaspilot-skill/tools.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    tools = mod.get_tools()
    return {t.name: t for t in tools}


def _invoke(tools: dict, name: str, args: dict) -> dict:
    t = tools.get(name)
    if not t or not callable(getattr(t, "invoke", None)):
        return {"error": f"Tool {name} not found"}
    out = t.invoke(args)
    if isinstance(out, str):
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return {"error": out, "raw": out}
    return out if isinstance(out, dict) else {"error": str(out)}


# 内置 Si2 金刚石结构 POSCAR（与页面常用测试一致）
DEFAULT_POSCAR = """Si2
1.0
   5.4299999999999997    0.0000000000000000    0.0000000000000003
   0.0000000000000009    5.4299999999999997    0.0000000000000003
   0.0000000000000000    0.0000000000000000    5.4299999999999997
Si
2
direct
   0.0000000000000000    0.0000000000000000    0.0000000000000000 Si
   0.2500000000000000    0.2500000000000000    0.2500000000000000 Si
"""


def main():
    parser = argparse.ArgumentParser(
        description="能带流程命令行测试：生成输入、提交 HPC、轮询状态、下载并画能带图",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--poscar",
        type=Path,
        default=None,
        help="POSCAR 文件路径；不指定则使用内置 Si2 结构",
    )
    parser.add_argument(
        "--no-submit",
        action="store_true",
        help="只生成输入文件到 out-dir，不提交 HPC",
    )
    parser.add_argument(
        "--no-poll",
        action="store_true",
        help="提交后不轮询、不下载、不画图；默认会轮询状态并下载 vasprun.xml 生成能带图",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=30,
        help="轮询间隔（秒），默认 30",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("band_workflow_out"),
        help="保存生成输入、vasprun.xml、能带图等的目录，默认 band_workflow_out",
    )
    parser.add_argument(
        "--plot-only",
        action="store_true",
        help="只从 out-dir 读取 vasprun.xml、KPOINTS 并生成能带图，不生成输入、不提交、不轮询",
    )
    args = parser.parse_args()

    # 只重跑画图
    if args.plot_only:
        out_dir = (PROJECT_ROOT / args.out_dir).resolve() if not args.out_dir.is_absolute() else args.out_dir.resolve()
        vasprun_file = out_dir / "vasprun.xml"
        kpoints_file = out_dir / "KPOINTS"
        if not vasprun_file.is_file():
            print("错误: 未找到 vasprun.xml，路径:", vasprun_file)
            return 1
        tools = _load_tools()
        vasprun_content = vasprun_file.read_text(encoding="utf-8", errors="replace")
        kpoints_content = (kpoints_file.read_text(encoding="utf-8", errors="replace")) if kpoints_file.is_file() else None
        plot_res = _invoke(tools, "vaspilot_plot_band_structure", {"vasprun_xml_content": vasprun_content, "kpoints_content": kpoints_content or ""})
        if plot_res.get("error"):
            print("画能带图失败:", plot_res.get("error"))
            return 1
        import base64
        b64 = plot_res.get("image_base64")
        if b64:
            png_path = out_dir / "band_structure.png"
            png_path.write_bytes(base64.b64decode(b64))
            print("已保存能带图:", png_path)
        else:
            print("未返回图片数据")
            return 1
        return 0

    # 读取 POSCAR
    if args.poscar and args.poscar.is_file():
        poscar_content = args.poscar.read_text(encoding="utf-8", errors="replace")
        print(f"[1/7] 已从文件读取 POSCAR: {args.poscar} ({len(poscar_content)} 字节)")
    else:
        poscar_content = DEFAULT_POSCAR.strip()
        print("[1/7] 使用内置 Si2 POSCAR")

    tools = _load_tools()
    # 输出目录相对于项目根，避免 chdir(skill) 后写到 skill 下
    out_dir = (PROJECT_ROOT / args.out_dir).resolve() if not args.out_dir.is_absolute() else args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # 生成输入
    print("[2/7] 调用 vaspilot_generate_inputs (calc_type=band) ...")
    gen = _invoke(tools, "vaspilot_generate_inputs", {"poscar_content": poscar_content, "calc_type": "band"})
    if gen.get("error"):
        print("生成输入失败:", gen.get("error"))
        if gen.get("check"):
            print("检查项:", gen.get("check"))
        return 1
    files = gen.get("files")
    if not files or "submit.sh" not in files:
        print("生成输入失败: 返回中无 submit.sh")
        return 1
    print("  生成文件:", list(files.keys()))
    check = gen.get("check", {})
    print("  检查项: submit.sh 含 bash gen_potcar.sh =", check.get("submit_has_bash_gen_potcar"), ", test -f POTCAR =", check.get("submit_has_test_potcar"))

    # 把生成的所有输入文件写入 out_dir（POSCAR, INCAR_*, KPOINTS_*, gen_potcar.sh, submit.sh）
    written = []
    for name, content in files.items():
        if not name or name.startswith(".") or "/" in name or "\\" in name:
            continue
        if not isinstance(content, str):
            continue
        (out_dir / name).write_text(content, encoding="utf-8", newline="\n")
        written.append(name)
    print(f"  已写入目录: {out_dir}  (文件: {written})")

    if args.no_submit:
        print("  (--no-submit) 跳过提交，结束。")
        return 0

    # 获取 HPC 配置
    print("[3/7] 调用 vaspilot_get_hpc_config ...")
    hpc = _invoke(tools, "vaspilot_get_hpc_config", {})
    if hpc.get("error") or not (hpc.get("host") and hpc.get("username")):
        print("获取 HPC 配置失败:", hpc.get("error") or "缺少 host/username")
        return 1
    remote_work_dir = (hpc.get("work_dir") or "").strip() or None
    if not remote_work_dir:
        print("HPC 配置中无 work_dir")
        return 1
    key_path = (hpc.get("key_path") or "").strip() or None
    port = hpc.get("port", 22) or 22
    print("  host =", hpc.get("host"), ", user =", hpc.get("username"), ", work_dir =", remote_work_dir)

    # 提交作业
    print("[4/7] 调用 vaspilot_submit_to_hpc ...")
    submit_args = {
        "files": files,
        "host": hpc["host"],
        "username": hpc["username"],
        "remote_work_dir": remote_work_dir,
        "port": int(port),
    }
    if key_path:
        submit_args["key_path"] = key_path
    else:
        submit_args["password"] = "__use_config__"
    submit_res = _invoke(tools, "vaspilot_submit_to_hpc", submit_args)
    if submit_res.get("error") or not submit_res.get("success"):
        print("提交失败:", submit_res.get("error") or submit_res)
        return 1
    job_id = submit_res.get("job_id")
    remote_dir = submit_res.get("remote_dir")
    print("  提交成功: job_id =", job_id, ", remote_dir =", remote_dir)

    if args.no_poll:
        print("  (--no-poll) 不轮询，结束。job_id =", job_id)
        return 0

    # 轮询状态
    status_args = {
        "job_id": job_id,
        "host": hpc["host"],
        "username": hpc["username"],
        "port": int(port),
    }
    if key_path:
        status_args["key_path"] = key_path
    else:
        status_args["password"] = "__use_config__"

    print("[5/7] 轮询作业状态 (间隔 %ds)，直到 COMPLETED/FAILED ..." % args.poll_interval)
    while True:
        st = _invoke(tools, "vaspilot_job_status", status_args)
        if st.get("error"):
            print("  查询状态失败:", st.get("error"))
            time.sleep(args.poll_interval)
            continue
        status = (st.get("status") or "").strip().upper()
        print("  状态:", status, st.get("node", ""), st.get("time_used", ""))
        if status == "COMPLETED":
            break
        if status == "FAILED":
            print("  作业失败，拉取日志 ...")
            log_args = {"job_id": job_id, "remote_dir": remote_dir, "host": hpc["host"], "username": hpc["username"], "port": int(port)}
            if key_path:
                log_args["key_path"] = key_path
            else:
                log_args["password"] = "__use_config__"
            logs = _invoke(tools, "vaspilot_fetch_job_logs", log_args)
            if not logs.get("error"):
                for k in ["stderr", "stdout", "vasp_scf_log"]:
                    v = logs.get(k, "")
                    if v and v != "(文件不存在或为空)":
                        (out_dir / f"fail_{k}.txt").write_text(v, encoding="utf-8", errors="replace")
                        print("    已保存", f"fail_{k}.txt")
            print("  失败详情已写入", out_dir)
            return 1
        time.sleep(args.poll_interval)

    # 下载 vasprun.xml、KPOINTS
    print("[6/7] 下载 vasprun.xml 与 KPOINTS ...")
    dl_args = {
        "remote_dir": remote_dir,
        "host": hpc["host"],
        "username": hpc["username"],
        "port": int(port),
    }
    if key_path:
        dl_args["key_path"] = key_path
    else:
        dl_args["password"] = "__use_config__"

    vasprun_content = None
    kpoints_content = None
    for fname in ["vasprun.xml", "KPOINTS"]:
        dl = _invoke(tools, "vaspilot_download_remote_file", {**dl_args, "filename": fname})
        if dl.get("error") or not dl.get("success"):
            print("  下载 %s 失败:" % fname, dl.get("error") or "无 content")
            continue
        content = dl.get("content") or ""
        dest = out_dir / fname
        dest.write_text(content, encoding="utf-8", errors="replace")
        print("  已保存", dest)
        if fname == "vasprun.xml":
            vasprun_content = content
        else:
            kpoints_content = content

    if not vasprun_content or len(vasprun_content) < 2000:
        print("  vasprun.xml 缺失或过短，跳过画能带图")
        return 1

    # 画能带图
    print("[7/7] 生成能带图 ...")
    plot_args = {"vasprun_xml_content": vasprun_content}
    if kpoints_content:
        plot_args["kpoints_content"] = kpoints_content
    plot_res = _invoke(tools, "vaspilot_plot_band_structure", plot_args)
    if plot_res.get("error"):
        print("  画能带图失败:", plot_res.get("error"))
        return 1
    import base64
    b64 = plot_res.get("image_base64")
    if b64:
        png_path = out_dir / "band_structure.png"
        png_path.write_bytes(base64.b64decode(b64))
        print("  已保存能带图:", png_path)
    print("  完成。输出目录:", out_dir)
    print("  生成文件: 输入(POSCAR, INCAR_*, KPOINTS_*, gen_potcar.sh, submit.sh) | vasprun.xml | KPOINTS | band_structure.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
