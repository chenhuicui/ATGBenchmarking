from androguard.core.bytecodes.apk import APK

apk = APK("/Volumes/Extreme Pro/atg_apks_hard/org.wordpress.android_1440.apk")
print(apk.get_androidversion_code())
print(apk.get_androidversion_name())