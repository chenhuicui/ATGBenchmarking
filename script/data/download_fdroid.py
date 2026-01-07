# read urls from "result/fdroid.txt/urls_version1.txt"
# download apks from fdroid.txt
# save apks to downloaded/fdroid.txt/apks_version1
import argparse
import os
import time
import urllib.error
import urllib.parse
import urllib.request


def download_apk(url, apk_path):
    try:
        urllib.request.urlretrieve(url, apk_path)
    except urllib.error.HTTPError as e:
        print(e.reason)
        print(url)
        print(apk_path)
        return False
    except urllib.error.URLError as e:
        print(e.reason)
        print(url)
        print(apk_path)
        return False
    except Exception as e:
        print(e)
        print(url)
        print(apk_path)
        return False
    return True


if __name__ == '__main__':

    # Create the parser
    parser = argparse.ArgumentParser(description='Process to download fdroid.txt.')

    # Define the arguments
    parser.add_argument('--urls_path', type=str, help='Path to the file containing URLs')
    parser.add_argument('--apk_dir', type=str, help='Directory to save downloaded APKs')

    # Parse the arguments
    args = parser.parse_args()

    # Access the arguments
    urls_path = "/Users/cuichenhui/Documents/local-repositories/transition-graph-workspace/ATGBenchmarking/atgbuilder/androzoo.txt"
    apk_dir = '/Volumes/Extreme Pro/atg_apks'

    print(f'URLs Path: {urls_path}')
    print(f'APK Directory: {apk_dir}')

    if not os.path.exists(apk_dir):
        os.makedirs(apk_dir)

    urls = []
    with open(urls_path, "r") as f:
        urls = f.readlines()

    for url in urls:
        url = url.strip()
        apk_name = url.split("/")[-1]
        apk_path = os.path.join(apk_dir, apk_name)
        if os.path.exists(apk_path):
            continue
        print("downloading " + apk_name)
        download_apk(url, apk_path)
        time.sleep(1)
