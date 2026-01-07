import os.path


def main():
    file_path = '/Users/cuichenhui/Documents/local-repositories/transition-graph-workspace/ATGBenchmarking/summary/data_analysis/final/gt_transitions_bigger1.txt'
    apk_list = []

    fdroid_file_path = '/Users/cuichenhui/Documents/local-repositories/transition-graph-workspace/ATGBenchmarking/atgbuilder/fdroid.txt'
    androzoo_file_path = '/Users/cuichenhui/Documents/local-repositories/transition-graph-workspace/ATGBenchmarking/atgbuilder/androzoo.txt'
    hackerone_apps_file_path = '/Users/cuichenhui/Documents/local-repositories/transition-graph-workspace/ATGBenchmarking/atgbuilder/hackerone_apps.txt'
    with open(file_path, "r") as f:
        lines = f.readlines()
        for line in lines:
            if not line.endswith('.apk\n') and not line.startswith('APK: apks/hackerone_apps/'):
                continue
            app_info = {'name': line.strip().split('/')[-1], 'source': line.strip().split('/')[-2]}

            apk_list.append(app_info)

    for apk in apk_list:
        if apk['source'] == "fdroid":
            url = os.path.join("https://f-droid.org/repo/", apk['name'])
            with open(fdroid_file_path, "a") as fd:
                fd.write(url + '\n')
        elif apk['source'] == "androzoo":
            url = apk['name']
            with open(androzoo_file_path, "a") as fds:
                fds.write(url + '\n')
        elif apk['source'] == "hackerone_apps":
            url = apk['name']
            with open(hackerone_apps_file_path, "a") as fdx:
                fdx.write(url + '\n')

    print(len(apk_list))


if __name__ == '__main__':
    main()
