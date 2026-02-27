from typing import Annotated

import logging

from langchain_core.tools import tool

from src.config.loader import get_str_env
from .decorators import log_io

logger = logging.getLogger(__name__)


@tool
@log_io
def phase_diagram_tool(
    chemical_system: Annotated[
        str,
        "Chemical system string like 'Li-Fe-P-O' or 'Li-Fe-O'. Elements are separated by hyphens '-'.",
    ],
    max_entries: Annotated[
        int,
        "Maximum number of entries to fetch from Materials Project (per API call).",
    ] = 128,
) -> str:
    """Analyze the phase diagram stability for a given chemical system using Materials Project data.

    This tool:
    - queries Materials Project for all computed materials in the given chemical system;
    - builds a 0 K convex hull (phase diagram);
    - returns a Markdown summary with:
      - stable phases (on the hull),
      - metastable phases (with energy above hull in eV/atom),
      - links to Materials Project entries when available.

    Requirements:
    - Environment or conf.yaml must provide a valid MP_API_KEY.
    - Packages `mp-api` and `pymatgen` must be installed.
    """
    chemical_system = (chemical_system or "").strip()
    if not chemical_system:
        return "请提供化学体系，例如 `Li-Fe-P-O`。元素之间用短横线 `-` 连接。"

    try:
        # 使用 pymatgen 内置的 MPRester + get_entries_in_chemsys，
        # 它会自动补齐端元（pure elements）条目，避免 Missing terminal entries 报错。
        from pymatgen.ext.matproj import MPRester as PMGMPRester  # type: ignore
        from pymatgen.analysis.phase_diagram import PhaseDiagram  # type: ignore
    except ImportError as e:  # pragma: no cover - import-time dependency
        return (
            "[ERROR] Phase diagram dependencies missing: "
            f"{e}. 请安装 `pymatgen` 后重试。"
        )

    api_key = get_str_env("MP_API_KEY", "")
    if not api_key:
        return (
            "[ERROR] 未找到 Materials Project API 密钥。\n\n"
            "请在环境变量或 `conf.yaml` 的 `ENV.MP_API_KEY` 中配置有效的 MP_API_KEY。"
        )

    # Clamp max_entries to a reasonable range to avoid very large queries
    try:
        max_k = int(max_entries)
    except (TypeError, ValueError):
        max_k = 128
    max_k = max(10, min(max_k, 500))

    logger.info(
        "Phase diagram tool: querying Materials Project (pymatgen MPRester) for system %s (max_entries=%d)",
        chemical_system,
        max_k,
    )

    # 解析 chemical_system -> 元素列表，例如 "Li-Fe-O" -> ["Fe", "Li", "O"]（pymatgen 期望排序的元素列表）
    elements = [e for e in chemical_system.replace(" ", "").split("-") if e]
    if len(elements) < 2:
        return "化学体系格式不正确，请使用类似 `Li-Fe-O` 的形式（至少包含两个元素）。"

    try:
        with PMGMPRester(api_key) as mpr:
            entries = mpr.get_entries_in_chemsys(
                elements,
                # 为了和大多数相图示例保持一致，使用常规晶胞
                conventional_unit_cell=True,
            )
    except Exception as e:
        logger.exception("Failed to query Materials Project (pymatgen MPRester) for %s: %s", chemical_system, e)
        return f"[ERROR] 查询 Materials Project 失败：{e!s}"

    if not entries or len(entries) < 2:
        return (
            f"在 Materials Project 中 `{chemical_system}` 体系的有效材料数量过少（{len(entries) if entries else 0} 个），"
            "无法构建有意义的相图。"
        )

    try:
        pd = PhaseDiagram(entries)
    except Exception as e:
        logger.exception("Failed to build PhaseDiagram for %s: %s", chemical_system, e)
        return f"[ERROR] 构建相图失败：{e!s}"

    # Build lookup from formula to representative material_id(s) using entry_id
    formula_to_ids: dict[str, list[str]] = {}
    from pymatgen.core import Composition  # type: ignore

    for e in entries[:max_k]:
        try:
            comp = e.composition
            if not isinstance(comp, Composition):
                comp = Composition(comp)
            formula = comp.reduced_formula
            mpid = getattr(e, "entry_id", None)
            if mpid:
                formula_to_ids.setdefault(formula, []).append(str(mpid))
        except Exception:
            continue

    stable_rows: list[dict] = []
    unstable_rows: list[dict] = []

    for e in pd.all_entries:
        try:
            formula = e.composition.reduced_formula
            e_above = float(pd.get_e_above_hull(e))
        except Exception:
            continue

        mpids = formula_to_ids.get(formula) or []
        mpid = mpids[0] if mpids else None

        row = {
            "formula": formula,
            "e_above": e_above,
            "mpid": mpid,
        }
        if e_above <= 1e-6:
            stable_rows.append(row)
        else:
            unstable_rows.append(row)

    # Deduplicate by (formula, mpid) and sort
    def _uniq_sort(rows: list[dict], key):
        seen = set()
        out = []
        for r in rows:
            k = (r.get("formula"), r.get("mpid"))
            if k in seen:
                continue
            seen.add(k)
            out.append(r)
        out.sort(key=key)
        return out

    stable_rows = _uniq_sort(stable_rows, key=lambda r: r["formula"])
    unstable_rows = _uniq_sort(unstable_rows, key=lambda r: r["e_above"])

    lines: list[str] = []
    lines.append(f"### 相图分析（体系：`{chemical_system}`）")
    lines.append("")
    lines.append(
        "基于 Materials Project 的 0 K 能量凸包（convex hull）分析，"
        "下列化合物位于/高于能量凸包。"
    )
    lines.append("")

    # Stable phases
    lines.append("#### 稳定相（在能量凸包上）")
    if stable_rows:
        lines.append("")
        lines.append("| 化学式 | Materials Project ID |")
        lines.append("|--------|----------------------|")
        for r in stable_rows:
            mpid = r.get("mpid")
            if mpid:
                link = f"[{mpid}](https://materialsproject.org/materials/{mpid})"
            else:
                link = "-"
            lines.append(f"| {r['formula']} | {link} |")
    else:
        lines.append("")
        lines.append("未找到稳定相。")

    # Metastable phases
    lines.append("")
    lines.append("#### 亚稳相（高于凸包的能量，单位 eV/atom）")
    if unstable_rows:
        lines.append("")
        lines.append("| 化学式 | ΔE above hull (eV/atom) | Materials Project ID |")
        lines.append("|--------|-------------------------|----------------------|")
        for r in unstable_rows[:50]:
            mpid = r.get("mpid")
            if mpid:
                link = f"[{mpid}](https://materialsproject.org/materials/{mpid})"
            else:
                link = "-"
            lines.append(f"| {r['formula']} | {r['e_above']:.3f} | {link} |")
        if len(unstable_rows) > 50:
            lines.append("")
            lines.append(f"_共发现 {len(unstable_rows)} 个亚稳相，这里仅展示前 50 个。_")
    else:
        lines.append("")
        lines.append("未找到明显高于凸包的亚稳相。")

    lines.append("")
    lines.append(
        "> 提示：ΔE above hull 越接近 0，材料在热力学上越可能稳定；"
        "通常 ΔE < 0.05–0.1 eV/atom 仍可能在实验中合成为亚稳相。"
    )

    return "\n".join(lines)

