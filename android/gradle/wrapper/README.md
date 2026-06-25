# gradle-wrapper.jar 说明

本目录应有一个二进制 `gradle-wrapper.jar`(约 60KB),但**二进制不入 git**(避免仓库塞二进制)。
它会在以下任一情况下自动出现,无需手动下载:

- **用 Android Studio 打开 `android/` 目录**:IDE 自动补全 wrapper(jar + 必要文件)。
- **命令行**:在装了 Gradle 8.x 的机器上,于 `android/` 跑一次 `gradle wrapper`,即生成 jar。

生成后 `./gradlew assembleDebug` 就能用了。详见 `docs/android-app.md`。
