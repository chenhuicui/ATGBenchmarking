# check_verify_widget_npz_coverage.py
# -*- coding: utf-8 -*-
import os
import numpy as np
import collections
from typing import Dict, List, Set, Tuple, Optional

# ====== 改这里 ======
VERIFY_ROOT = "/Users/cuichenhui/Documents/local-repositories/transition-graph-workspace/dataset/atgs"
WNPZ_DIR = "/Users/cuichenhui/Documents/local-repositories/transition-graph-workspace/dataset/atgs/embeddings/fused_embeddings/dimension_reduced/LINEAR/widget/ab_complete"

# index 目录：你现在 verify_apps 里用的是 atg_index
INDEX_DIR = os.path.join(VERIFY_ROOT, "atg_index")
WIDGET_TXT_DIR = os.path.join(VERIFY_ROOT, "atg_widgets_fixed")
ACT_DIR = os.path.join(VERIFY_ROOT, "atg_activities")

# 扫多少个 app（0=全扫）
SCAN_FIRST_N_APPS = 0
PRINT_PER_APP_TOP_MISSING = 20
PRINT_SAMPLES_PER_APP = 2

EPS = 1e-12
# ====================

def read_lines(p: str) -> List[str]:
    if not p or (not os.path.exists(p)):
        return []
    with open(p, "r", encoding="utf-8", errors="ignore") as f:
        return [x.strip() for x in f if x.strip()]

def try_file(*cands: str) -> Optional[str]:
    for p in cands:
        if p and os.path.exists(p):
            return p
    return None

def list_apps() -> List[str]:
    apps = []
    if os.path.isdir(ACT_DIR):
        for fn in os.listdir(ACT_DIR):
            if not fn.endswith(".txt"):
                continue
            a = fn[:-4]
            if a.endswith("_seed_atg"):
                a = a[:-len("_seed_atg")]
            apps.append(a)
    apps = sorted(set(apps))
    if SCAN_FIRST_N_APPS and SCAN_FIRST_N_APPS > 0:
        apps = apps[:SCAN_FIRST_N_APPS]
    return apps

def parse_index_wids(index_path: str) -> List[str]:
    wids = []
    for ln in read_lines(index_path):
        if "," in ln:
            parts = [p.strip() for p in ln.split(",")]
        elif ";" in ln:
            parts = [p.strip() for p in ln.split(";")]
        else:
            continue
        if len(parts) != 4:
            continue
        wid = parts[2].strip()
        if wid:
            wids.append(wid)
    return wids

def parse_widgets_txt_ids(widget_txt_path: str) -> Set[str]:
    ids = set()
    for ln in read_lines(widget_txt_path):
        if ln.startswith(">"):
            wid = ln[1:].strip()
            if wid:
                ids.add(wid)
    return ids

def load_npz(npz_path: str) -> Dict[str, np.ndarray]:
    z = np.load(npz_path, allow_pickle=True)
    out = {}
    for k in z.files:
        v = z[k]
        if isinstance(v, np.ndarray) and v.ndim == 1:
            out[str(k)] = v.astype(np.float32)
    return out

def all_zero(v: np.ndarray) -> bool:
    return bool(np.all(np.abs(v) < EPS))

def seg_zero_modes(v160: np.ndarray) -> Tuple[bool, bool, bool]:
    a = v160[:64]
    b = v160[64:128]
    c = v160[128:160]
    return (all_zero(a), all_zero(b), all_zero(c))

def main():
    apps = list_apps()
    if not apps:
        print("[ERROR] no apps found from:", ACT_DIR)
        return

    # 全局累计
    g_total_apps = 0
    g_npz_missing = 0

    g_need_wids = 0
    g_missing_wids = 0

    g_need_index_wids = 0
    g_missing_index_wids = 0

    g_npz_keys_total = 0
    g_npz_has_only_none = 0

    # 向量质量统计：三段是否全 0
    g_seg_modes = collections.Counter()  # (name0, sum0, lis0)
    g_vec_count = 0

    for app in apps:
        g_total_apps += 1

        npz_path = os.path.join(WNPZ_DIR, f"{app}.npz")
        wtxt_path = try_file(
            os.path.join(WIDGET_TXT_DIR, f"{app}.txt"),
            os.path.join(WIDGET_TXT_DIR, f"{app}_seed_atg.txt"),
        )
        idx_path = try_file(
            os.path.join(INDEX_DIR, f"{app}.txt"),
            os.path.join(INDEX_DIR, f"{app}_seed_atg.txt"),
        )

        if not os.path.exists(npz_path):
            g_npz_missing += 1
            print(f"\n[APP] {app}")
            print("  MISS npz:", npz_path)
            continue

        npz = load_npz(npz_path)
        keys = sorted(npz.keys())
        g_npz_keys_total += len(keys)
        if len(keys) == 1 and keys[0] == "NONE_WIDGET":
            g_npz_has_only_none += 1

        # 向量维度/三段检查
        bad_dim = 0
        for k, v in npz.items():
            if v.shape[0] != 160:
                bad_dim += 1
                continue
            g_seg_modes[seg_zero_modes(v)] += 1
            g_vec_count += 1

        # 需要覆盖的 wid：来自 widgets.txt 的 >id
        wid_from_txt = parse_widgets_txt_ids(wtxt_path) if wtxt_path else set()
        need_txt = sorted([w for w in wid_from_txt if w != "NONE_WIDGET"])
        miss_txt = sorted([w for w in need_txt if w not in npz])

        g_need_wids += len(need_txt)
        g_missing_wids += len(miss_txt)

        # 需要覆盖的 wid：来自 index 的 wid（排除 NONE_WIDGET）
        idx_wids = []
        if idx_path:
            idx_wids = [w for w in parse_index_wids(idx_path) if w != "NONE_WIDGET"]
        idx_need_uniq = sorted(set(idx_wids))
        idx_miss = sorted([w for w in idx_need_uniq if w not in npz])

        g_need_index_wids += len(idx_need_uniq)
        g_missing_index_wids += len(idx_miss)

        # 输出每个 app 的概览（只在有问题或抽样打印）
        if miss_txt or idx_miss or bad_dim > 0 or len(keys) <= 3:
            print(f"\n[APP] {app}")
            print("  npz_keys:", len(keys), "has_NONE:", ("NONE_WIDGET" in npz))
            print("  bad_dim_vectors:", bad_dim)
            print("  widgets.txt ids:", len(need_txt), "missing:", len(miss_txt))
            if miss_txt:
                print("    miss_from_widgets_txt (top):", miss_txt[:PRINT_PER_APP_TOP_MISSING])
            print("  index uniq_wids:", len(idx_need_uniq), "missing:", len(idx_miss))
            if idx_miss:
                print("    miss_from_index (top):", idx_miss[:PRINT_PER_APP_TOP_MISSING])

        # 随机抽样打印几个 key 的三段 std/zero
        if PRINT_SAMPLES_PER_APP > 0 and len(keys) > 0:
            pick_keys = keys[:min(PRINT_SAMPLES_PER_APP, len(keys))]
            print(f"\n  [SAMPLES] {app} first {len(pick_keys)} keys:", pick_keys)
            for kk in pick_keys:
                v = npz[kk]
                if v.shape[0] != 160:
                    print("   -", kk, "dim=", v.shape[0], "!!")
                    continue
                a0, b0, c0 = seg_zero_modes(v)
                a = v[:64]; b = v[64:128]; c = v[128:160]
                print("   -", kk,
                      "zeros=", (a0, b0, c0),
                      "stds=", (float(a.std()), float(b.std()), float(c.std())),
                      "head(name)=", np.round(a[:6], 4),
                      "head(sum)=", np.round(b[:6], 4),
                      "head(lis)=", np.round(c[:6], 4))

    # 全局汇总
    print("\n==============================")
    print("[GLOBAL SUMMARY]")
    print("==============================")
    print("apps_scanned:", g_total_apps)
    print("npz_missing_apps:", g_npz_missing)
    if g_total_apps > 0:
        print("npz_missing_ratio:", g_npz_missing / g_total_apps)

    if g_total_apps > 0:
        print("\n[npz key stats]")
        print("avg_keys_per_app:", g_npz_keys_total / max(g_total_apps - g_npz_missing, 1))
        print("apps_only_NONE_WIDGET:", g_npz_has_only_none)
        print("ratio_only_NONE_WIDGET:", g_npz_has_only_none / max(g_total_apps - g_npz_missing, 1))

    print("\n[coverage from widgets.txt]")
    print("need_txt_wids:", g_need_wids)
    print("missing_txt_wids:", g_missing_wids)
    print("missing_ratio:", (g_missing_wids / g_need_wids) if g_need_wids else 0.0)

    print("\n[coverage from index]")
    print("need_index_wids:", g_need_index_wids)
    print("missing_index_wids:", g_missing_index_wids)
    print("missing_ratio:", (g_missing_index_wids / g_need_index_wids) if g_need_index_wids else 0.0)

    print("\n[vector segment zero modes] (name_zero, summary_zero, listener_zero)")
    total = sum(g_seg_modes.values())
    for k, v in g_seg_modes.most_common():
        r = v / total if total else 0.0
        print(f"  {k}  count={v}  ratio={r:.4f}")

if __name__ == "__main__":
    main()