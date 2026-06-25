package com.kindledash.app;

import com.journeyapps.barcodescanner.CaptureActivity;

/**
 * 锁竖屏的扫码界面。ZXing 默认的 CaptureActivity 是横屏,手持手机扫二维码很别扭;
 * 这里子类化它,靠 Manifest 里 android:screenOrientation="portrait" 把朝向锁成竖屏,
 * 配合 ScanOptions.setOrientationLocked(false)(不让 CaptureManager 改回横屏)即生效。
 */
public class PortraitCaptureActivity extends CaptureActivity {
}
