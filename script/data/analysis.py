import pandas as pd

# 1. AndroZoo 总表，比如 andro_csv = "/path/to/androzoo.csv"
andro_csv = "/Volumes/Extreme Pro/latest.csv"
df_all = pd.read_csv(andro_csv)

# 2. 你的目标 apk 列表，存成一个 txt 或者直接在代码里写
target_names = [
    "com.yinzcam.facilities.verizon_1612214.0.apk",
]

rows = []
for name in target_names:
    # 去掉尾巴 .apk
    name_no_ext = name[:-4] if name.endswith(".apk") else name
    pkg, ver = name_no_ext.rsplit("_", 1)
    # 去掉你这边的 .0（如果存在）
    if ver.endswith(".0"):
        ver = ver[:-2]
    # vercode 在 AndroZoo 里通常是整数
    try:
        ver_int = int(ver)
    except ValueError:
        print("无法解析版本号：", name)
        continue

    # 在总表里匹配
    matched = df_all[(df_all["pkg_name"] == pkg) & (df_all["vercode"] == ver_int)]
    if matched.empty:
        print("找不到：", pkg, ver_int)
        continue

    rows.append(matched.iloc[0])  # 假设唯一匹配

df_to_download = pd.DataFrame(rows)

# 只保留需要的三列（如果你愿意也可以多保留）
df_to_download = df_to_download[["sha256", "pkg_name", "vercode"]]

df_to_download.to_csv("apks_to_download.csv", index=False)
print("生成 apks_to_download.csv 完成")