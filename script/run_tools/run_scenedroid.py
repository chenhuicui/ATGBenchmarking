from run_tool_base import ToolExecutor


# sdkmanager "system-images;android-28;google_apis;x86"
# avdmanager create avd --force --name api_28 --package 'system-images;android-28;google_apis;x86' --sdcard 1024M --device 'Nexus 7'

# docker run --rm -v /mnt/hdd3/jkliu/Projects/ATGEmpiricalWhole/ATGEmpirical/:/Data --device=/dev/kvm --name temp -it stoat  bash

# /root/Projects/Exhau-SceId-master/run_scenedroid.sh /root/Projects/Exhau-SceId-master/apks_old/org.connectbot.apk /root/Projects/Exhau-SceId-master/temp 600 > /root/Projects/Exhau-SceId-master/temp/log.txt 2>&1
# /root/Projects/Exhau-SceId-master/run_scenedroid.sh /root/Projects/Exhau-SceId-master/apks_old/v2rayNG_1.7.3.apk /root/Projects/Exhau-SceId-master/temp 900 > /root/Projects/Exhau-SceId-master/temp/log.txt 2>&1

class SceneDroid(ToolExecutor):

    def __init__(self, apk_path: str, test_time: str):
        super().__init__(apk_path, "scenedroid", test_time)
        self.docker_image = f"atg/{self.tool_name}"
        self.docker_test_time = str(int(self.test_time) * 1.1)


if __name__ == '__main__':
    ape = SceneDroid("/media/DATA/jkliu-data/Projects/ATGEmpirical/apks/downloaded/fdroid.txt/apks_version2/org.wikipedia_50458.apk", "3000")
    # ape = SceneDroid("apks/fdroid.txt/net.kourlas.voipms_sms_146.apk", "3000")
    ape.run()
