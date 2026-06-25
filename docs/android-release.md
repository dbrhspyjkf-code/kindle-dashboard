# 安卓 App 签名 release 出包指南

> 适用 v2 起。debug 包(`assembleDebug`)用 Android 默认 debug.keystore 自动签名,**无需** keystore;
> 正式发布包(`assembleRelease`)需要你**自己生成一个 release keystore**。
> **铁律:keystore 文件与口令绝不进 git**(`.gitignore` 已排除 `*.jks`/`*.keystore`/`keystore.properties`),构建时本地提供。

## 1. 生成 release keystore(一次性)

用 JDK 自带的 `keytool`(本机自包含工具链在 `~/android-build/jdk/bin/keytool`):

```bash
~/android-build/jdk/bin/keytool -genkeypair -v \
  -keystore ~/kindledash-release.jks \
  -alias kindledash \
  -keyalg RSA -keysize 2048 -validity 10000 \
  -storepass '你的口令' -keypass '你的口令' \
  -dname "CN=Kindle Dashboard, OU=, O=yizhixiaoheigou, L=, ST=, C=CN"
```

- `-validity 10000` ≈ 27 年(应用商店要求签名有效期足够长)。
- 把 `~/kindledash-release.jks` 放到仓库**外**的安全位置,**别提交、别丢**——丢了就没法给同一个 App 发更新(签名不一致会被系统当成另一个应用)。
- 口令记到密码管理器,别写进任何会进 git 的文件。

## 2. 告诉 Gradle 去哪拿签名材料

两选一(`app/build.gradle` 已支持,优先文件、其次环境变量;都没有=release 不签名):

### 方式 A:本地 properties 文件(推荐)

在 `android/` 目录下建 `keystore.properties`(**已被 .gitignore 排除**):

```properties
storeFile=$HOME/kindledash-release.jks
storePassword=你的口令
keyAlias=kindledash
keyPassword=你的口令
```

### 方式 B:环境变量(CI / 不想落文件时)

```bash
export KINDLEDASH_KEYSTORE=$HOME/kindledash-release.jks
export KINDLEDASH_STORE_PASSWORD='你的口令'
export KINDLEDASH_KEY_ALIAS=kindledash
export KINDLEDASH_KEY_PASSWORD='你的口令'
```

## 3. 出签名 release APK

复用本机自包含工具链(和 debug 同一套 JDK17/SDK34/Gradle8.2):

```bash
cd ~/android-build/android-src    # 或直接在仓库的 android/ 目录(确保 keystore.properties 在 android/ 下)
export JAVA_HOME=~/android-build/jdk
export ANDROID_HOME=~/android-build/sdk
export PATH="$JAVA_HOME/bin:$HOME/android-build/gradle/bin:$PATH"
export GRADLE_USER_HOME=~/android-build/ghome
gradle --no-daemon assembleRelease
```

产物:`app/build/outputs/apk/release/app-release.apk`(已签名,可直接侧载/上架)。

验证签名:

```bash
~/android-build/jdk/bin/keytool -printcert -jarfile app/build/outputs/apk/release/app-release.apk
# 或用 build-tools 的 apksigner
~/android-build/sdk/build-tools/34.0.0/apksigner verify --print-certs app/build/outputs/apk/release/app-release.apk
```

若 `keystore.properties` / 环境变量都没配,`assembleRelease` 会产出**未签名**包(`app-release-unsigned.apk`),装不上——配好签名再出。

## 4. 版本号规范

- `app/build.gradle` 的 `versionCode`(整数,每次发布**必须递增**,商店/在线升级靠它比新旧)+ `versionName`(给人看的，如 `2.0`)。
- 当前:`versionCode 2` / `versionName '2.0'`。下次发布改这两个。

## 红线回顾
- keystore、口令绝不进 git、不进日志、不进 commit。
- 同一个 App 的所有更新必须用**同一个 keystore** 签名(换了 = 用户得卸载重装)。
- debug 包仅供自测,别拿 debug 包发布。
