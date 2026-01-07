import argparse
import sys

from core.file_paths import *
from run_ape import Ape
from run_fastbot import Fastbot
from run_humanoid import Humanoid
from run_monkey import Monkey
from run_qtest import QTest
from run_scenedroid import SceneDroid
from run_stoat import Stoat


def run_tools(apk, test_time):
    ape = Ape(apk, test_time)
    fastbot = Fastbot(apk, test_time)
    humanoid = Humanoid(apk, test_time)
    monkey = Monkey(apk, test_time)
    qtest = QTest(apk, test_time)
    scenedroid = SceneDroid(apk, test_time)
    stoat = Stoat(apk, test_time)
    # current_tools = [scenedroid]
    current_tools = [ape, fastbot, humanoid, monkey, qtest, scenedroid, stoat]
    return current_tools


if __name__ == '__main__':

    # arg parsing

    parser = argparse.ArgumentParser(description='Process to download fdroid.txt.')

    # Define the arguments
    parser.add_argument('--result_dir', type=str, help='Result directory', required=True)
    parser.add_argument('--apk_dir', type=str, help='Directory of APKs to test', default="all")
    parser.add_argument('--test_time', type=str, help='Time to test the APKs', default="3600")
    parser.add_argument('--filter_internet', type=str, help='Whether exclude the apps with internet access', default="True")

    # Parse the arguments
    args = parser.parse_args()

    # Access the arguments
    result_dir = args.result_dir
    apk_dir = args.apk_dir
    test_time = args.test_time
    filter_internet = args.filter_internet

    print(f"Running tools for apks in {apk_dir}, results will be saved in {result_dir}")
    tools = []

    set_current_version(result_dir)

    print(f"Current version is {get_current_version()}")

    # apk = "/media/DATA/jkliu-data/Projects/ATGEmpirical/apks/downloaded/fdroid.txt/apks_version1/android.jonas.fakestandby_11.apk"
    #
    # current_tools = run_tools(apk, test_time)
    # tools.extend(current_tools)

    for apk in get_apks_list(apk_dir, filter_internet):
        current_tools = run_tools(apk, test_time)
        tools.extend(current_tools)

    with ThreadPoolExecutor(max_workers=15) as executor:
        for tool in tools:
            executor.submit(tool.run)
            # tool.run()
            # break
