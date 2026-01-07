import argparse
import os
import subprocess
import concurrent.futures

import pandas as pd

APIKEY = "35d7b41bd0d25bc910d8aaffe5375db2bae463451a5b8fdb548cf99e14dbfc58"  # 重新从网页复制一遍，确保没有多余空格/换行

def exclude_processed(df_sampled, df_processed):
    return df_sampled[~df_sampled["sha256"].isin(df_processed["sha256"])]


def downloading(sha256: str, file_path: str):
    # 按官方文档格式：先下载成 sha256.apk 再改名
    tmp_name = f"{sha256}.apk"
    if os.path.exists(tmp_name):
        os.remove(tmp_name)

    cmd = [
        "curl",
        "-O",
        "--remote-header-name",
        "-G",
        "-d", f"apikey={APIKEY}",
        "-d", f"sha256={sha256}",
        "https://androzoo.uni.lu/api/download",
    ]
    print(" ".join(cmd))

    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] 下载 {sha256} 失败: {e}")
        # 如果有下载出小垃圾文件，删掉
        if os.path.exists(tmp_name) and os.path.getsize(tmp_name) < 1024:
            os.remove(tmp_name)
        return

    # 检查文件是否真的存在&大小正常
    if not os.path.exists(tmp_name):
        print(f"[ERROR] {sha256}: curl 返回成功但没有生成 {tmp_name}")
        return

    size = os.path.getsize(tmp_name)
    if size < 1024:
        print(f"[WARN] {sha256}: 下载结果只有 {size} 字节，疑似错误提示，已删除")
        os.remove(tmp_name)
        return

    # 移动到目标目录
    os.rename(tmp_name, file_path)
    print(f"[OK] {sha256} -> {file_path} (size={size} bytes)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download APKs from AndroZoo.")
    parser.add_argument(
        "--apks_to_download",
        type=str,
        required=True,
        help="CSV with columns: sha256, pkg_name, vercode",
    )
    parser.add_argument(
        "--apk_dir",
        type=str,
        required=True,
        help="Directory to save downloaded APKs",
    )
    args = parser.parse_args()

    apks_to_download = args.apks_to_download
    apk_dir = args.apk_dir

    print(f"APKs Path: {apks_to_download}")
    print(f"APK Directory: {apk_dir}")

    os.makedirs(apk_dir, exist_ok=True)

    df = pd.read_csv(apks_to_download)

    MAX_WORKERS = 8  # 官方建议最多 ~20，这里保守一点
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS)

    futures = []
    for _, row in df.iterrows():
        apkname = row["pkg_name"]
        version = row["vercode"]
        sha256 = row["sha256"]

        version_str = str(version)
        file_path = os.path.join(apk_dir, f"{apkname}_{version_str}.apk")

        if os.path.exists(file_path):
            print(f"File {file_path} already exists, skip.")
            continue

        print(apkname, version_str, sha256)
        futures.append(executor.submit(downloading, sha256, file_path))

    for f in concurrent.futures.as_completed(futures):
        _ = f.result()

    executor.shutdown(wait=True)