package com.kindledash.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.ProgressDialog;
import android.content.DialogInterface;
import android.content.Intent;
import android.net.Uri;
import android.widget.Toast;

import java.io.File;

/**
 * 老系统(安卓 4.x,SDK_INT&lt;21)在线更新 —— 仍走 GitHub(开源分发渠道,不走任何私有地址)。
 * <p>
 * 命根子(为何单独一份、不复用 SettingsActivity 的安装流程):
 *  - **TLS 1.2**:GitHub 强制 TLS1.2,4.2 默认禁用 → 由 {@link UpdateChecker#applyTls12} 对 4.x 连接强开;
 *  - **安装**:API&lt;24 用 `Uri.fromFile` 直接交系统安装器,**不引 FileProvider**(那是 androidx 现代类,
 *    legacy 路径尽量不碰);7.0+ 才需要 FileProvider,而 legacy 只可能跑在 &lt;21 上。
 *  - 纯 `android.app.*` + 纯 Java 的 {@link UpdateChecker},不碰 AppCompat。
 * <p>
 * manual=true(用户在配置页主动点「检查更新」):无更新/失败也给 Toast 反馈;
 * manual=false(看板启动后自动查一次):静默,只在发现新版时弹对话框。
 */
final class LegacyUpdate {

    private LegacyUpdate() {}

    static void checkAndPrompt(final Activity act, final boolean manual) {
        if (manual) Toast.makeText(act, R.string.cfg_update_checking, Toast.LENGTH_SHORT).show();
        int cur;
        try {
            cur = act.getPackageManager().getPackageInfo(act.getPackageName(), 0).versionCode;
        } catch (Exception e) {
            cur = -1;
        }
        final int curCode = cur;
        new Thread(new Runnable() {
            @Override public void run() {
                try {
                    final UpdateChecker.UpdateInfo u = UpdateChecker.check(curCode);
                    act.runOnUiThread(new Runnable() {
                        @Override public void run() {
                            if (act.isFinishing()) return;
                            if (u.hasUpdate) promptInstall(act, u);
                            else if (manual) Toast.makeText(act, R.string.cfg_update_latest, Toast.LENGTH_LONG).show();
                        }
                    });
                } catch (final Exception e) {
                    if (manual) act.runOnUiThread(new Runnable() {
                        @Override public void run() {
                            if (!act.isFinishing())
                                Toast.makeText(act, act.getString(R.string.cfg_update_check_fail)
                                        + ": " + e.getMessage(), Toast.LENGTH_LONG).show();
                        }
                    });
                }
            }
        }).start();
    }

    private static void promptInstall(final Activity act, final UpdateChecker.UpdateInfo u) {
        String notes = (u.notes == null || u.notes.trim().isEmpty())
                ? act.getString(R.string.cfg_update_no_notes) : u.notes;
        new AlertDialog.Builder(act)
                .setTitle(act.getString(R.string.cfg_update_found) + "  " + u.versionName)
                .setMessage(notes)
                .setPositiveButton(R.string.cfg_update_download, new DialogInterface.OnClickListener() {
                    @Override public void onClick(DialogInterface d, int w) { download(act, u); }
                })
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private static void download(final Activity act, final UpdateChecker.UpdateInfo u) {
        final ProgressDialog pd = new ProgressDialog(act);
        pd.setProgressStyle(ProgressDialog.STYLE_HORIZONTAL);
        pd.setMessage(act.getString(R.string.cfg_update_downloading));
        pd.setCancelable(false);
        pd.setMax(100);
        pd.show();
        new Thread(new Runnable() {
            @Override public void run() {
                try {
                    final File apk = UpdateChecker.download(act, u.apkUrl, u.apkName, new UpdateChecker.Progress() {
                        @Override public void on(final int pct) {
                            act.runOnUiThread(new Runnable() {
                                @Override public void run() { pd.setProgress(pct); }
                            });
                        }
                    });
                    act.runOnUiThread(new Runnable() {
                        @Override public void run() { dismiss(pd); install(act, apk); }
                    });
                } catch (final Exception e) {
                    act.runOnUiThread(new Runnable() {
                        @Override public void run() {
                            dismiss(pd);
                            if (!act.isFinishing())
                                Toast.makeText(act, act.getString(R.string.cfg_update_download_fail)
                                        + ": " + e.getMessage(), Toast.LENGTH_LONG).show();
                        }
                    });
                }
            }
        }).start();
    }

    private static void install(Activity act, File apk) {
        try {
            // API<24:file:// URI 直接交系统安装器(legacy 只可能在 <21,不需要 FileProvider)
            Intent i = new Intent(Intent.ACTION_VIEW);
            i.setDataAndType(Uri.fromFile(apk), "application/vnd.android.package-archive");
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            act.startActivity(i);
        } catch (Exception e) {
            Toast.makeText(act, act.getString(R.string.cfg_update_install_fail)
                    + ": " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    private static void dismiss(ProgressDialog pd) {
        try { if (pd != null && pd.isShowing()) pd.dismiss(); } catch (Exception ignore) {}
    }
}
