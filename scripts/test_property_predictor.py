#!/usr/bin/env python3
"""
简单脚本：直接调用分子性质预测模型，便于排查为何工具箱里“分子性质预测”会卡住。

会依次测 HOMO、LUMO、DM、以及 HOMO+LUMO+DM(ALL)，并打印各步耗时。
DM 明显更慢是正常的：DM 使用 remove_hs: false，加载 mol_pre_all_h_220816.pt，
保留氢原子，分子图更大，计算量比 HOMO/LUMO（no_h）大。

用法（在项目根目录下，建议用虚拟环境）：
    .venv/bin/python3 scripts/test_property_predictor.py
"""

import importlib.util
import os
import sys
import time

# 项目根目录
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_predictor_class():
    """
    直接从文件路径加载 Predictor，避免触发 src.tools.__init__ 中对 langchain_core 等依赖的导入。
    """
    prop_path = os.path.join(ROOT_DIR, "src", "tools", "property_predictor", "prop_predictor.py")
    spec = importlib.util.spec_from_file_location("prop_predictor_local", prop_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module spec from {prop_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[arg-type]
    return module.Predictor  # type: ignore[attr-defined]


def main() -> None:
    # 尽量选几个非常简单的 SMILES，方便快速测试
    smiles_list = [
        "CCO",         # 乙醇
        "c1ccccc1",    # 苯
        "CC(=O)O",     # 乙酸
    ]
    print("Will predict properties for SMILES:", smiles_list, flush=True)

    Predictor = _load_predictor_class()
    predictor = Predictor()

    timings = {}
    for props in [
        ("HOMO", dict(HOMO=True, LUMO=False, DM=False)),
        ("LUMO", dict(HOMO=False, LUMO=True, DM=False)),
        ("DM", dict(HOMO=False, LUMO=False, DM=True)),
        ("ALL", dict(HOMO=True, LUMO=True, DM=True)),
    ]:
        label, flags = props
        print("\n=== Testing properties:", label, "===\n", flush=True)
        t0 = time.time()
        try:
            results = predictor.prop_pred(
                smiles_list,
                generated=False,
                **flags,
            )
        except Exception as e:
            print(f"[ERROR] Exception during prop_pred({label}): {e!r}", flush=True)
            continue
        elapsed = time.time() - t0
        timings[label] = elapsed
        print(f"[OK] prop_pred({label}) finished in {elapsed:.2f} s", flush=True)
        print("Result keys:", list(results.keys()), flush=True)
        for k, v in results.items():
            shape = getattr(v, "shape", None)
            print(f"  - {k}: type={type(v)}, shape={shape}", flush=True)

    print("\n" + "=" * 50, flush=True)
    print("Timing summary (DM 使用 remove_hs:false，all_h 模型更重，通常最慢):", flush=True)
    for label, sec in timings.items():
        print(f"  {label}: {sec:.2f} s", flush=True)
    if "DM" in timings and "ALL" in timings:
        print(f"  -> 若 DM 明显更慢，属预期（偶极矩用全氢表示，计算量更大）", flush=True)


if __name__ == "__main__":
    main()

