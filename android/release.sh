#!/bin/sh
# Build a new numbered APK for the phone: bump version.properties, build, run SelfTest on the phone's own runtime,
# and leave exactly one /sdcard/Download/furby-companion-<version>.apk for a tap in File Manager
# (MIUI blocks adb installs unless "Install via USB" is on; then it is installed too). Usage: android/release.sh [-PphoneDir=/path/to/phone]
set -e
cd "$(dirname "$0")"
code=$(sed -n 's/^code=//p' version.properties)
code=$((code + 1))
name="0.$code"
cp version.properties version.properties.bak
trap 'mv version.properties.bak version.properties' EXIT    # a failed build keeps the old number
printf 'code=%s\nname=%s\n' "$code" "$name" > version.properties
JAVA_HOME=${JAVA_HOME:-/opt/homebrew/opt/openjdk@21} ./gradlew assembleDebug --console=plain -q "$@"
apk=app/build/outputs/apk/debug/app-debug.apk
adb push "$apk" /data/local/tmp/furby.apk >/dev/null
adb shell CLASSPATH=/data/local/tmp/furby.apk app_process / fluffkit.companion.SelfTest | tee /dev/stderr | grep -q "ALL OK"
adb shell 'rm -f /sdcard/Download/furby-companion*.apk'
adb push "$apk" "/sdcard/Download/furby-companion-$name.apk" >/dev/null
trap - EXIT; rm -f version.properties.bak
# install right away where the phone allows it (MIUI: "Install via USB" on); otherwise tap the file in Download
if adb shell pm install -r /data/local/tmp/furby.apk 2>&1 | grep -q Success; then
  echo "installed $name"; adb shell am start -n fluffkit.companion/.MainActivity >/dev/null
fi
echo "ready: /sdcard/Download/furby-companion-$name.apk (version $name, code $code)"
