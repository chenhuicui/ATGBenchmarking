from run_tool_base import ToolExecutor


# sdkmanager "system-images;android-28;google_apis;x86"
# avdmanager create avd --force --name api_28 --package 'system-images;android-28;google_apis;x86' --sdcard 1024M --device 'Nexus 7'

# docker run --rm -v /mnt/hdd3/jkliu/Projects/ATGEmpiricalWhole/ATGEmpirical/:/Data --device=/dev/kvm --name temp -it atg/ape bash

class Ape(ToolExecutor):

    def __init__(self, apk_path: str, test_time: str):
        super().__init__(apk_path, "ape", test_time)


if __name__ == '__main__':
    ape = Ape("/media/DATA/jkliu-data/Projects/ATGEmpirical/apks/downloaded/fdroid.txt/apks_version1/android.jonas.fakestandby_11.apk", "360")
    # ape = Ape("apks/fdroid.txt/net.kourlas.voipms_sms_146.apk", "360")
    ape.run()
