#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mini_atg_analyzer_v6.py

主要改进：
- 修复 <include layout="@layout/xxx"> 解析，递归展开 include 的 layout
- 解析 R$layout.smali + R$id.smali：
    * layoutId -> layoutName
    * viewIdInt -> viewIdName
- 从 smali 解析代码侧的 onClick 绑定：
    * findViewById + setOnClickListener(Activity implements View.OnClickListener)
    * 初始得到 method "onClick" -> [view_ids]
- 构建类内调用图，将 "onClick" 的触发关系向下游 helper 方法传播：
    * 比如 onClick -> launchActivityAndFinishSelf
    * 则 launchActivityAndFinishSelf 里的 startActivity transition 也带上 trigger/view_ids
- Intent 解析：
    * 继续支持 Intent.<init>(Context, Target.class)
    * 支持 Intent.setClass(Context, Target.class) / Intent.setClassName(..., "pkg.Target")
"""

import argparse
import json
import re
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Dict, List, Tuple, Optional, Set


ANDROID_NS = "http://schemas.android.com/apk/res/android"
ANDROID_NAME = f"{{{ANDROID_NS}}}name"
ANDROID_TEXT = f"{{{ANDROID_NS}}}text"
ANDROID_ONCLICK = f"{{{ANDROID_NS}}}onClick"


# -----------------------
# 工具 & 公共函数
# -----------------------

def desc_to_dotted(desc: str) -> str:
    if not desc.startswith("L") or not desc.endswith(";"):
        return desc
    return desc[1:-1].replace("/", ".")


def dotted_to_desc(name: str) -> str:
    return f"L{name.replace('.', '/')};"


def split_dalvik_types(type_desc: str) -> List[str]:
    res: List[str] = []
    i = 0
    while i < len(type_desc):
        c = type_desc[i]
        if c in ("B", "C", "D", "F", "I", "J", "S", "Z", "V"):
            res.append(c)
            i += 1
        elif c == "L":
            j = i + 1
            while j < len(type_desc) and type_desc[j] != ";":
                j += 1
            j += 1
            res.append(type_desc[i:j])
            i = j
        elif c == "[":
            j = i + 1
            while j < len(type_desc) and type_desc[j] == "[":
                j += 1
            if j < len(type_desc) and type_desc[j] == "L":
                k = j + 1
                while k < len(type_desc) and type_desc[k] != ";":
                    k += 1
                k += 1
                res.append(type_desc[i:k])
                i = k
            else:
                res.append(type_desc[i:j + 1])
                i = j + 1
        else:
            res.append(c)
            i += 1
    return [t for t in res if t]


def norm_tag(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


# -----------------------
# Manifest 解析
# -----------------------

def parse_manifest(apk_root: Path) -> Dict:
    manifest_path = apk_root / "AndroidManifest.xml"
    if not manifest_path.exists():
        raise FileNotFoundError(f"AndroidManifest.xml not found in {apk_root}")

    tree = ET.parse(manifest_path)
    root = tree.getroot()
    pkg = root.attrib.get("package", "")

    activities = []
    for app in root.findall("application"):
        for act in list(app.findall("activity")) + list(app.findall("activity-alias")):
            name = act.attrib.get(ANDROID_NAME)
            if not name:
                continue
            if name.startswith("."):
                full_name = pkg + name
            elif "." not in name:
                full_name = pkg + "." + name
            else:
                full_name = name

            is_launcher = False
            for iflt in act.findall("intent-filter"):
                for cat in iflt.findall("category"):
                    if cat.attrib.get(ANDROID_NAME) == "android.intent.category.LAUNCHER":
                        is_launcher = True
                        break
                if is_launcher:
                    break

            activities.append({
                "name": full_name,
                "is_launcher": is_launcher,
            })

    return {
        "package": pkg,
        "activities": activities,
    }


# -----------------------
# Smali 索引
# -----------------------

def index_smali_files(apk_root: Path) -> Dict[str, Path]:
    class_to_path: Dict[str, Path] = {}
    for smali_dir in apk_root.iterdir():
        if not smali_dir.is_dir() or not smali_dir.name.startswith("smali"):
            continue
        for smali in smali_dir.rglob("*.smali"):
            try:
                with smali.open("r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith(".class "):
                            m = re.search(r"\s(L[^;]+;)", line)
                            if m:
                                desc = m.group(1)
                                dotted = desc_to_dotted(desc)
                                class_to_path[dotted] = smali
                            break
            except Exception:
                continue
    return class_to_path


# -----------------------
# 解析 R$layout / R$id
# -----------------------

def parse_layout_ids(apk_root: Path) -> Dict[int, str]:
    id_to_name: Dict[int, str] = {}
    for smali_dir in apk_root.iterdir():
        if not smali_dir.is_dir() or not smali_dir.name.startswith("smali"):
            continue
        for smali in smali_dir.rglob("R$layout.smali"):
            try:
                with smali.open("r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        m = re.match(r"\.field\s+public\s+static\s+final\s+(\w+):I\s*=\s*(0x[0-9a-fA-F]+)", line)
                        if not m:
                            continue
                        layout_name, value_hex = m.groups()
                        try:
                            value_int = int(value_hex, 16)
                        except ValueError:
                            continue
                        id_to_name[value_int] = layout_name
            except Exception:
                continue
    return id_to_name


def parse_view_ids(apk_root: Path) -> Dict[int, str]:
    """
    解析 R$id.smali，将 viewIdInt -> "btn_0" 这样的名字。
    """
    id_to_name: Dict[int, str] = {}
    for smali_dir in apk_root.iterdir():
        if not smali_dir.is_dir() or not smali_dir.name.startswith("smali"):
            continue
        for smali in smali_dir.rglob("R$id.smali"):
            try:
                with smali.open("r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        m = re.match(r"\.field\s+public\s+static\s+final\s+(\w+):I\s*=\s*(0x[0-9a-fA-F]+)", line)
                        if not m:
                            continue
                        view_name, value_hex = m.groups()
                        try:
                            value_int = int(value_hex, 16)
                        except ValueError:
                            continue
                        id_to_name[value_int] = view_name
            except Exception:
                continue
    return id_to_name


# -----------------------
# layout XML 解析
# -----------------------

def parse_layout_xml_files(apk_root: Path) -> Dict[str, Path]:
    name_to_path: Dict[str, Path] = {}
    res_dir = apk_root / "res"
    if not res_dir.exists():
        return name_to_path

    for sub in res_dir.iterdir():
        if not sub.is_dir() or not sub.name.startswith("layout"):
            continue
        for xml_path in sub.glob("*.xml"):
            layout_name = xml_path.stem
            if layout_name not in name_to_path:
                name_to_path[layout_name] = xml_path
    return name_to_path


def extract_widgets_from_layout(
    xml_path: Path,
    layout_name_to_xml: Dict[str, Path],
    visited: Optional[Set[Path]] = None
) -> List[Dict]:
    """
    从一个 layout xml 中递归提取所有带 android:id 的控件：
      - 普通控件：任何 tag 有 android:id 就收
      - <include layout="@layout/xxx">:
          * 递归展开被 include 的 layout
          * include 自己若有 android:id 也收一条
    返回列表元素：{id, class, text, onclick}
    """
    widgets: List[Dict] = []
    if visited is None:
        visited = set()
    if xml_path in visited:
        return widgets
    visited.add(xml_path)

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except Exception:
        return widgets

    def dfs(elem: ET.Element):
        tag_name = norm_tag(elem.tag)

        # 处理 <include>
        if tag_name == "include":
            # 注意：这里 layout 是无命名空间属性 "layout"
            layout_attr = elem.attrib.get("layout")
            if layout_attr and layout_attr.startswith("@layout/"):
                inc_name = layout_attr.split("/")[-1]
                inc_path = layout_name_to_xml.get(inc_name)
                if inc_path and inc_path.exists():
                    widgets.extend(extract_widgets_from_layout(inc_path, layout_name_to_xml, visited))

            # include 自己如果有 id 也记录
            id_attr = elem.attrib.get(f"{{{ANDROID_NS}}}id")
            if id_attr:
                id_name = id_attr.split("/")[-1]
                widgets.append({
                    "id": id_name,
                    "class": tag_name,
                    "text": elem.attrib.get(ANDROID_TEXT),
                    "onclick": elem.attrib.get(ANDROID_ONCLICK),
                })
            return

        # 普通控件
        id_attr = elem.attrib.get(f"{{{ANDROID_NS}}}id")
        if id_attr:
            id_name = id_attr.split("/")[-1]
            widgets.append({
                "id": id_name,
                "class": tag_name,
                "text": elem.attrib.get(ANDROID_TEXT),
                "onclick": elem.attrib.get(ANDROID_ONCLICK),
            })

        for child in list(elem):
            dfs(child)

    dfs(root)
    return widgets


# -----------------------
# Intent helper 分析（返回 Intent 的方法）
# -----------------------

def analyze_intent_helpers(apk_root: Path) -> Dict[str, str]:
    """
    扫描所有返回 Intent 的方法，识别：
      - Intent.<init>(Context, Target.class)
      - Intent.setClass(...)
      - Intent.setClassName(pkg, "Target") / setClassName("pkg.Target")
    输出：
      "Lpkg/Foo;->createIntent(... )Landroid/content/Intent;" -> "Lpkg/TargetActivity;"
    """
    helper_targets: Dict[str, str] = {}

    for smali_dir in apk_root.iterdir():
        if not smali_dir.is_dir() or not smali_dir.name.startswith("smali"):
            continue
        for smali_path in smali_dir.rglob("*.smali"):
            try:
                with smali_path.open("r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
            except Exception:
                continue

            current_class_desc: Optional[str] = None
            for line in lines:
                line = line.strip()
                if line.startswith(".class "):
                    m = re.search(r"\s(L[^;]+;)", line)
                    if m:
                        current_class_desc = m.group(1)
                    break
            if not current_class_desc:
                continue

            i = 0
            while i < len(lines):
                line = lines[i].strip()
                if not line.startswith(".method "):
                    i += 1
                    continue

                header_rest = line[len(".method "):].strip()
                parts = header_rest.split()
                sig_part = parts[-1]
                m_sig = re.match(r"([^\(]+)(\([^\)]*\)(.+))", sig_part)
                if not m_sig:
                    i += 1
                    continue
                method_name = m_sig.group(1)
                full_desc = m_sig.group(2)
                ret_str = full_desc[full_desc.find(")") + 1:]

                body_lines: List[str] = []
                i += 1
                while i < len(lines):
                    l2 = lines[i]
                    body_lines.append(l2)
                    if l2.strip().startswith(".end method"):
                        break
                    i += 1

                if ret_str != "Landroid/content/Intent;":
                    i += 1
                    continue

                class_const_map: Dict[str, str] = {}
                intent_ctor_map: Dict[str, str] = {}
                intent_target_cls_map: Dict[str, str] = {}
                string_const_map: Dict[str, str] = {}

                for idx, bline in enumerate(body_lines):
                    s = bline.strip()

                    m_str = re.match(r"const-string(?:/jumbo)?\s+(\S+),\s+\"([^\"]*)\"", s)
                    if m_str:
                        reg, txt = m_str.groups()
                        string_const_map[reg] = txt
                        continue

                    m_cc = re.match(r"const-class\s+(\S+),\s+(L[^;]+;)", s)
                    if m_cc:
                        reg, cls_desc = m_cc.groups()
                        class_const_map[reg] = cls_desc
                        continue

                    m_inv = re.match(
                        r"(invoke-(virtual|direct|static|interface|super)(?:/range)?)\s*\{([^\}]*)\},\s+([^\s]+)",
                        s
                    )
                    if not m_inv:
                        continue

                    invoke_kind = m_inv.group(2)
                    regs_str = m_inv.group(3)
                    method_full = m_inv.group(4)
                    regs = [r.strip() for r in regs_str.split(",") if r.strip()]
                    m_sig2 = re.match(r"(L[^;]+;)->([^\(]+)\(([^)]*)\)(.+)", method_full)
                    if not m_sig2:
                        continue
                    owner_desc, callee_name, arg_types_str2, ret_type2 = m_sig2.groups()
                    arg_types2 = split_dalvik_types(arg_types_str2)
                    is_static_call = (invoke_kind == "static")

                    # Intent.<init> / setClass
                    if owner_desc == "Landroid/content/Intent;" and callee_name in ("<init>", "setClass"):
                        if not regs:
                            continue
                        intent_reg = regs[0]
                        class_index = None
                        for a_idx, t in enumerate(arg_types2):
                            if t == "Ljava/lang/Class;":
                                class_index = a_idx
                                break
                        if class_index is not None:
                            arg_reg_index = (0 if is_static_call else 1) + class_index
                            if 0 <= arg_reg_index < len(regs):
                                class_reg = regs[arg_reg_index]
                                intent_ctor_map[intent_reg] = class_reg
                        continue

                    # Intent.setClassName(...)
                    if owner_desc == "Landroid/content/Intent;" and callee_name == "setClassName":
                        if not regs:
                            continue
                        intent_reg = regs[0]
                        str_indices = [i for i, t in enumerate(arg_types2) if t == "Ljava/lang/String;"]
                        target_str_reg = None
                        if str_indices:
                            class_idx = str_indices[-1]
                            arg_reg_index = (0 if is_static_call else 1) + class_idx
                            if 0 <= arg_reg_index < len(regs):
                                target_str_reg = regs[arg_reg_index]
                        if target_str_reg and target_str_reg in string_const_map:
                            class_name = string_const_map[target_str_reg]
                            # 这里只能得到一个字符串，先做简单的绝对类名处理
                            if "." not in class_name:
                                # 没有包名，不太好恢复，先忽略
                                pass
                            else:
                                cls_desc = dotted_to_desc(class_name)
                                intent_target_cls_map[intent_reg] = cls_desc
                        continue

                target_cls_desc: Optional[str] = None
                for intent_reg, class_reg in intent_ctor_map.items():
                    cls_desc = class_const_map.get(class_reg)
                    if cls_desc:
                        target_cls_desc = cls_desc
                        break
                if target_cls_desc is None:
                    for intent_reg, cls_desc in intent_target_cls_map.items():
                        target_cls_desc = cls_desc
                        break

                if target_cls_desc:
                    full_call_sig = f"{current_class_desc}->{method_name}{full_desc}"
                    helper_targets[full_call_sig] = target_cls_desc

                i += 1

    return helper_targets


# -----------------------
# Activity 分析
# -----------------------

def analyze_activity_smali(
    smali_path: Path,
    activity_name_dotted: str,
    helper_targets: Dict[str, str],
    layout_id_to_name: Dict[int, str],
    view_id_to_name: Dict[int, str],
) -> Tuple[Set[str], List[Dict], Dict[str, List[str]]]:
    """
    分析一个 Activity：
      - 解析 setContentView -> 用到哪些 layout
      - 解析 startActivity / startActivityForResult -> transitions（含 method 名）
      - 解析 findViewById + setOnClickListener -> 初始方法 "onClick" -> [view_ids]
      - 构建类内调用图，把 onClick 的触发关系传播到 helper 方法
    返回：
      (layouts_used, transitions_with_method, method_to_view_ids_map)
    """
    try:
        with smali_path.open("r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception:
        return set(), [], {}

    layouts_used: Set[str] = set()
    transitions: List[Dict] = []

    current_class_desc: Optional[str] = None
    for line in lines:
        if line.strip().startswith(".class "):
            m = re.search(r"\s(L[^;]+;)", line)
            if m:
                current_class_desc = m.group(1)
            break
    if not current_class_desc:
        current_class_desc = dotted_to_desc(activity_name_dotted)

    # 全类范围：
    method_to_viewids_initial: Dict[str, List[str]] = {}   # 初始：通常只有 onClick -> view_ids
    method_calls_internal: Dict[str, Set[str]] = {}        # method -> {callee_method}

    pkg_name = activity_name_dotted.rsplit(".", 1)[0]

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line.startswith(".method "):
            i += 1
            continue

        header_rest = line[len(".method "):].strip()
        parts = header_rest.split()
        sig_part = parts[-1]
        m_sig = re.match(r"([^\(]+)(\([^\)]*\)(.+))", sig_part)
        if not m_sig:
            i += 1
            continue
        method_name = m_sig.group(1)
        full_desc = m_sig.group(2)

        body_lines: List[str] = []
        i += 1
        while i < len(lines):
            l2 = lines[i]
            body_lines.append(l2)
            if l2.strip().startswith(".end method"):
                break
            i += 1

        reg_int_values: Dict[str, int] = {}
        class_const_map: Dict[str, str] = {}
        intent_ctor_map: Dict[str, str] = {}
        intent_target_cls_map: Dict[str, str] = {}
        helper_result_targets: Dict[str, str] = {}
        string_const_map: Dict[str, str] = {}
        view_reg_to_id: Dict[str, str] = {}  # vX -> "btn_0"
        internal_callees: Set[str] = set()

        body_len = len(body_lines)
        idx = 0
        while idx < body_len:
            raw = body_lines[idx]
            s = raw.strip()

            # const + const-string
            m_const = re.match(r"const(?:/\d+)?\s+(\S+),\s+(0x[0-9a-fA-F]+|\d+)", s)
            if m_const:
                reg, value_str = m_const.groups()
                try:
                    value = int(value_str, 16) if value_str.startswith("0x") else int(value_str)
                    reg_int_values[reg] = value
                except ValueError:
                    pass
                idx += 1
                continue

            m_str = re.match(r"const-string(?:/jumbo)?\s+(\S+),\s+\"([^\"]*)\"", s)
            if m_str:
                reg, txt = m_str.groups()
                string_const_map[reg] = txt
                idx += 1
                continue

            # const-class
            m_cc = re.match(r"const-class\s+(\S+),\s+(L[^;]+;)", s)
            if m_cc:
                reg, cls_desc = m_cc.groups()
                class_const_map[reg] = cls_desc
                idx += 1
                continue

            # move-result-object（helper 返回的 Intent）
            m_mro = re.match(r"move-result-object\s+(\S+)", s)
            if m_mro:
                reg = m_mro.group(1)
                # 这里的 helper_result_targets 实际上需要在前一个 invoke 的时候记录 pending；
                # 为了简化，我们在这里不单独处理 pending，保持前面 helper 分析的结果为主。
                idx += 1
                continue

            # 通用 invoke
            m_inv = re.match(
                r"(invoke-(virtual|direct|static|interface|super)(?:/range)?)\s*\{([^\}]*)\},\s+([^\s]+)",
                s
            )
            if not m_inv:
                idx += 1
                continue

            invoke_kind = m_inv.group(2)
            regs_str = m_inv.group(3)
            method_full = m_inv.group(4)
            regs = [r.strip() for r in regs_str.split(",") if r.strip()]

            m_sig2 = re.match(r"(L[^;]+;)->([^\(]+)\(([^)]*)\)(.+)", method_full)
            if not m_sig2:
                idx += 1
                continue
            owner_desc, callee_name, arg_types_str2, ret_type2 = m_sig2.groups()
            arg_types2 = split_dalvik_types(arg_types_str2)
            is_static_call = (invoke_kind == "static")

            # 记录类内调用：当前方法 -> callee_method
            if owner_desc == current_class_desc:
                internal_callees.add(callee_name)

            full_call_sig = f"{owner_desc}->{callee_name}({arg_types_str2}){ret_type2}"

            # helper 返回 Intent 的情况（简单地：如果 helper_targets 里有记录）
            target_cls_desc_for_helper = helper_targets.get(full_call_sig)
            if target_cls_desc_for_helper:
                # 下一条 move-result-object vX 会把这个 Intent 放到 vX；这里只是记录，稍后再整体使用。
                # 为了简单，这里不区分 reg，直接忽略，交给 helper 本身的返回 Intent 解析。
                # 所以这里不更新 helper_result_targets。
                pass

            # Intent.<init> / setClass
            if owner_desc == "Landroid/content/Intent;" and callee_name in ("<init>", "setClass"):
                if regs:
                    intent_reg = regs[0]
                    class_index = None
                    for a_idx, t in enumerate(arg_types2):
                        if t == "Ljava/lang/Class;":
                            class_index = a_idx
                            break
                    if class_index is not None:
                        arg_reg_index = (0 if is_static_call else 1) + class_index
                        if 0 <= arg_reg_index < len(regs):
                            class_reg = regs[arg_reg_index]
                            intent_ctor_map[intent_reg] = class_reg
                idx += 1
                continue

            # Intent.setClassName(...)
            if owner_desc == "Landroid/content/Intent;" and callee_name == "setClassName":
                if regs:
                    intent_reg = regs[0]
                    str_indices = [ii for ii, t in enumerate(arg_types2) if t == "Ljava/lang/String;"]
                    target_str_reg = None
                    if str_indices:
                        class_idx = str_indices[-1]
                        arg_reg_index = (0 if is_static_call else 1) + class_idx
                        if 0 <= arg_reg_index < len(regs):
                            target_str_reg = regs[arg_reg_index]
                    if target_str_reg and target_str_reg in string_const_map:
                        class_name = string_const_map[target_str_reg]
                        if "." not in class_name:
                            # 没有包名时，尝试用当前包名拼一下
                            fqcn = pkg_name + "." + class_name
                        elif class_name.startswith("."):
                            fqcn = pkg_name + class_name
                        else:
                            fqcn = class_name
                        cls_desc = dotted_to_desc(fqcn)
                        intent_target_cls_map[intent_reg] = cls_desc
                idx += 1
                continue

            # setContentView(I)V
            if callee_name == "setContentView" and "(I)V" in method_full:
                if len(arg_types2) >= 1:
                    arg_index = 0
                    reg_index = (0 if is_static_call else 1) + arg_index
                    if 0 <= reg_index < len(regs):
                        layout_reg = regs[reg_index]
                        value = reg_int_values.get(layout_reg)
                        if value is not None:
                            layout_name = layout_id_to_name.get(value)
                            if layout_name:
                                layouts_used.add(layout_name)
                idx += 1
                continue

            # findViewById(I)Landroid/view/View;
            if callee_name == "findViewById" and ret_type2 == "Landroid/view/View;":
                # 只有一个 int 参数
                if len(arg_types2) == 1 and arg_types2[0] == "I":
                    arg_index = 0
                    reg_index = (0 if is_static_call else 1) + arg_index
                    if 0 <= reg_index < len(regs):
                        id_reg = regs[reg_index]
                        id_int = reg_int_values.get(id_reg)
                        if id_int is not None and id_int in view_id_to_name:
                            view_id_name = view_id_to_name[id_int]
                            # 下一行通常是 move-result-object vX
                            if idx + 1 < body_len:
                                next_s = body_lines[idx + 1].strip()
                                m_move = re.match(r"move-result-object\s+(\S+)", next_s)
                                if m_move:
                                    view_reg = m_move.group(1)
                                    view_reg_to_id[view_reg] = view_id_name
                idx += 1
                continue

            # setOnClickListener(Landroid/view/View$OnClickListener;)V
            if callee_name == "setOnClickListener":
                # View.setOnClickListener(View.OnClickListener)
                # regs[0] = this(View), regs[1] = listener
                if regs:
                    view_reg = regs[0]
                    view_id_name = view_reg_to_id.get(view_reg)
                    if view_id_name:
                        # 简单模式：listener 如果是 p0，认为是 Activity 自己实现了 View.OnClickListener -> 回调 onClick
                        listener_reg = None
                        # 查找第一个 View.OnClickListener 参数
                        for a_idx, t in enumerate(arg_types2):
                            if t == "Landroid/view/View$OnClickListener;":
                                arg_reg_index = (0 if is_static_call else 1) + a_idx
                                if 0 <= arg_reg_index < len(regs):
                                    listener_reg = regs[arg_reg_index]
                                break
                        if listener_reg and listener_reg.startswith("p0"):
                            # 认为是 this（Activity），回调方法名 onClick
                            method_to_viewids_initial.setdefault("onClick", []).append(view_id_name)
                idx += 1
                continue

            # startActivity / startActivityForResult
            is_start_activity = callee_name in ("startActivity", "startActivityForResult")
            if is_start_activity:
                intent_param_index = None
                for a_idx, t in enumerate(arg_types2):
                    if t == "Landroid/content/Intent;":
                        intent_param_index = a_idx
                        break
                if intent_param_index is not None:
                    reg_index = (0 if is_static_call else 1) + intent_param_index
                    if 0 <= reg_index < len(regs):
                        intent_reg = regs[reg_index]
                        target_desc: Optional[str] = None

                        # 1) helper-based（如果有的话）
                        # 这里严格依赖 helper_targets 已经包含了完整签名；大部分 app 没有使用就略过。

                        # 2) Intent.<init> / setClass -> class_const_map
                        class_reg = intent_ctor_map.get(intent_reg)
                        if class_reg:
                            target_desc = class_const_map.get(class_reg)

                        # 3) Intent.setClassName -> intent_target_cls_map
                        if target_desc is None:
                            target_desc = intent_target_cls_map.get(intent_reg)

                        transitions.append({
                            "source": activity_name_dotted,
                            "target": desc_to_dotted(target_desc) if target_desc else None,
                            "kind": callee_name,
                            "trigger": [],
                            "view_ids": [],
                            "location": {
                                "smali": str(smali_path),
                                "line_index": idx,
                            },
                            "method": method_name,
                        })
                idx += 1
                continue

            idx += 1

        # 把当前方法的内部调用关系记录下来
        if internal_callees:
            method_calls_internal[method_name] = internal_callees

    # ------- 在类级别做一次 trigger 传播（onClick -> helper） -------

    # 初始 map：可能只有 onClick -> [btn_0, btn_1, ...]
    method_trigger_map: Dict[str, List[str]] = {}
    for m, ids in method_to_viewids_initial.items():
        dedup = sorted(set(ids))
        method_trigger_map[m] = dedup

    # 从每个有 trigger 的方法出发，沿调用图向下游传播
    def propagate_from(method: str, ids: List[str], visited: Set[str]):
        if method in visited:
            return
        visited.add(method)
        callees = method_calls_internal.get(method, set())
        for cal in callees:
            existing = method_trigger_map.get(cal, [])
            new_ids = [x for x in ids if x not in existing]
            if new_ids:
                merged = existing + new_ids
                method_trigger_map[cal] = merged
                propagate_from(cal, merged, visited)

    for m, ids in list(method_trigger_map.items()):
        propagate_from(m, ids, set())

    return layouts_used, transitions, method_trigger_map


# -----------------------
# 主流程
# -----------------------

def build_atg(apk_root: Path) -> Dict:
    manifest_info = parse_manifest(apk_root)
    pkg = manifest_info["package"]
    manifest_activities = manifest_info["activities"]

    class_to_smali = index_smali_files(apk_root)
    layout_id_to_name = parse_layout_ids(apk_root)
    view_id_to_name = parse_view_ids(apk_root)
    layout_name_to_xml = parse_layout_xml_files(apk_root)

    helper_targets = analyze_intent_helpers(apk_root)

    activities_output: List[Dict] = []
    transitions_output: List[Dict] = []

    for act in manifest_activities:
        act_name = act["name"]
        is_launcher = act["is_launcher"]
        smali_path = class_to_smali.get(act_name)

        layouts_used: Set[str] = set()
        transitions_for_act: List[Dict] = []
        method_trigger_map_code: Dict[str, List[str]] = {}

        if smali_path and smali_path.exists():
            layouts_used, transitions_for_act, method_trigger_map_code = analyze_activity_smali(
                smali_path,
                act_name,
                helper_targets,
                layout_id_to_name,
                view_id_to_name,
            )

        # 解析 layout + widgets（包含递归 include）
        layout_entries: List[Dict] = []

        for ln in sorted(layouts_used):
            xml_path = layout_name_to_xml.get(ln)
            widgets: List[Dict] = []
            if xml_path and xml_path.exists():
                widgets = extract_widgets_from_layout(xml_path, layout_name_to_xml)
            layout_entries.append({
                "layout_name": ln,
                "file": str(xml_path) if xml_path else None,
                "widgets": widgets,
            })

        # 用 method_trigger_map_code 来给 transitions 填 trigger / view_ids
        for t in transitions_for_act:
            method = t.get("method")
            ids = method_trigger_map_code.get(method, [])
            t["trigger"] = ids
            t["view_ids"] = ids

        activities_output.append({
            "name": act_name,
            "is_launcher": is_launcher,
            "layouts": layout_entries,
        })

        transitions_output.extend(transitions_for_act)

    return {
        "meta": {
            "pkg": pkg,
        },
        "activities": activities_output,
        "transitions": transitions_output,
    }


# -----------------------
# CLI
# -----------------------

def main():
    parser = argparse.ArgumentParser(description="Mini Android ATG static analyzer (v6)")
    parser.add_argument("--apk-root", required=True, help="apktool 解包后的根目录")
    parser.add_argument("--output", required=True, help="输出 JSON 路径")
    args = parser.parse_args()

    apk_root = Path(args.apk_root).resolve()
    out_path = Path(args.output).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    atg = build_atg(apk_root)
    out_path.write_text(json.dumps(atg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[mini_atg_analyzer_v6] ATG written to: {out_path}")


if __name__ == "__main__":
    main()