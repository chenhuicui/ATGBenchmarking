from run_tool_base import ToolExecutor


# sdkmanager "system-images;android-28;google_apis;x86"
# avdmanager create avd --force --name api_28 --package 'system-images;android-28;google_apis;x86' --sdcard 1024M --device 'Nexus 7'

# docker run -v /mnt/hdd3/jkliu/Projects/ATGEmpiricalWhole/ATGEmpirical/:/Data --device=/dev/kvm --name new_container -it atg/humanoid bash

class Humanoid(ToolExecutor):

    def __init__(self, apk_path: str, test_time: str):
        super().__init__(apk_path, "humanoid", test_time)
        self.docker_image = f"atg/{self.tool_name}"


if __name__ == '__main__':
    ape = Humanoid("/media/DATA/jkliu-data/Projects/ATGEmpirical/apks/downloaded/fdroid.txt/apks_version1/android.jonas.fakestandby_11.apk", "360")
    # ape = Humanoid("apks/fdroid.txt/net.kourlas.voipms_sms_146.apk", "360")
    ape.run()
