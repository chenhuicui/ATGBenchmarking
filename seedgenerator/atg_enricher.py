#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import re
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional


# ========== 工具函数 ==========

def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


# ========== 从 UI.json 构建索引 ==========

def build_guid_widget_map(ui_data: dict) -> Dict[str, dict]:
    """
    guid -> widget 节点（包含 viewClass/id/idVariable/text/listeners 等）
    """
    guid_map: Dict[str, dict] = {}

    def visit_node(node: dict):
        guid = node.get("guid")
        if guid:
            guid_map[guid] = node

        # fragment 节点
        if "fragmentClass" in node and "layouts" in node:
            for layout in node["layouts"]:
                visit_node(layout)

        # 普通 children
        for child in node.get("children", []):
            visit_node(child)

    for act in ui_data.get("activities", []):
        for layout in act.get("layouts", []):
            visit_node(layout)
        for frag in act.get("orphanedFragments", []):
            for layout in frag.get("layouts", []):
                visit_node(layout)

    return guid_map


def build_listener_index(ui_data: dict) -> Dict[Tuple[str, str], List[dict]]:
    """
    (owner_class, method_name) -> [widget_info, ...]
    owner_class 从 listeners 的签名里解析，例如:
      "<at.jclehner.rxdroid.LockscreenActivity: void onClick(android.view.View)>"
    """
    index: Dict[Tuple[str, str], List[dict]] = {}

    def add_listener(owner: str, method: str, widget_info: dict):
        key = (owner, method)
        index.setdefault(key, []).append(widget_info)

    def walk(owner_guess: Optional[str], node: dict):
        # 解析 listeners
        for l in node.get("listeners", []):
            # formatter 的 listener 可能是 "onClick" / 也可能是完整签名
            if l.startswith("<") and ":" in l:
                m = re.match(r"<([^:]+): [^ ]+ ([^(]+)\(", l)
                if not m:
                    continue
                owner, method = m.group(1), m.group(2)
            else:
                # 退化情况：只有方法名，比如 "onClick"
                if owner_guess is None:
                    continue
                owner, method = owner_guess, l

            widget_info = {
                "viewClass": node.get("viewClass"),
                "id": node.get("id"),
                "idVariable": node.get("idVariable"),
                "guid": node.get("guid"),
                "textAttributes": node.get("textAttributes"),
                "otherAttributes": node.get("otherAttributes"),
            }
            add_listener(owner, method, widget_info)

        # 递归 children / fragment layouts
        for child in node.get("children", []):
            if "fragmentClass" in child and "layouts" in child:
                frag_cls = child["fragmentClass"]
                for layout in child["layouts"]:
                    walk(frag_cls, layout)
            else:
                walk(owner_guess, child)

    # Activity + orphanedFragments
    for act in ui_data.get("activities", []):
        act_name = act["name"]
        for layout in act.get("layouts", []):
            walk(act_name, layout)
        for frag in act.get("orphanedFragments", []):
            frag_cls = frag["fragmentClass"]
            for layout in frag.get("layouts", []):
                walk(frag_cls, layout)

    return index


# ========== 从 api.json 构建索引 ==========

def build_view_api_map(api_data: dict) -> Dict[str, dict]:
    """
    guid -> {listeners: [...], api: [...]}
    """
    m: Dict[str, dict] = {}
    for v in api_data.get("views", []):
        guid = v.get("guid")
        if not guid:
            continue
        m[guid] = {
            "listeners": v.get("listeners", []),
            "api": v.get("api", []),
        }
    return m


def build_activity_api_map(api_data: dict) -> Dict[str, List[str]]:
    """
    activity_name -> API 列表（生命周期/其他调用）
    """
    m: Dict[str, List[str]] = {}
    for act in api_data.get("activityLC", []):
        name = act.get("name")
        if not name:
            continue
        m[name] = act.get("api", [])
    return m


# ========== 富化 ATG ==========

def enrich_atg(
    atg_data: dict,
    listener_index: Dict[Tuple[str, str], List[dict]],
    view_api_map: Dict[str, dict],
    activity_api_map: Dict[str, List[str]],
) -> dict:
    transitions = atg_data.get("transitions", [])
    for t in transitions:
        src = t.get("source")
        method = t.get("method")

        # 1) 通过 (source_class, method_name) 找到对应的 widgets
        widgets = []
        if src and method:
            widgets = listener_index.get((src, method), [])

        # 2) trigger / view_ids / widgets
        if widgets:
            t["trigger"] = t.get("trigger") or ["click"]
            t["view_ids"] = [w["id"] for w in widgets if w.get("id") is not None]
            # 把 view 对应的 API 信息也融合进去
            rich_widgets = []
            for w in widgets:
                guid = w.get("guid")
                v_api = view_api_map.get(guid, {})
                rich_widgets.append(
                    {
                        **w,
                        "viewListenersSimple": v_api.get("listeners", []),
                        "viewApi": v_api.get("api", []),
                    }
                )
            t["widgets"] = rich_widgets
        else:
            t.setdefault("trigger", [])
            t.setdefault("view_ids", [])
            t.setdefault("widgets", [])

        # 3) 为每个 transition 挂上 source activity 的生命周期 API（方便 summary）
        if src in activity_api_map:
            # 可以选择只保留和导航有关的 API
            nav_related = [
                api
                for api in activity_api_map[src]
                if "startActivity" in api
                or "startActivityForResult" in api
                or "sendBroadcast" in api
            ]
            t["activity_nav_apis"] = nav_related

    return atg_data


# ========== CLI 入口 ==========

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Merge mini ATG with formatter ui/api info."
    )
    parser.add_argument("--ui", required=True, help="formatter_ui.json")
    parser.add_argument("--api", required=True, help="formatter_api.json")
    parser.add_argument("--atg", required=True, help="mini_atg.json")
    parser.add_argument("--output", required=True, help="enriched_atg.json")

    args = parser.parse_args()

    ui_data = load_json(Path(args.ui))
    api_data = load_json(Path(args.api))
    atg_data = load_json(Path(args.atg))

    listener_index = build_listener_index(ui_data)
    view_api_map = build_view_api_map(api_data)
    activity_api_map = build_activity_api_map(api_data)

    enriched = enrich_atg(atg_data, listener_index, view_api_map, activity_api_map)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)

    print(f"[+] Enriched ATG written to {out_path}")


if __name__ == "__main__":
    main()