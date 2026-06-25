package com.kindledash.app;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.text.InputType;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

/**
 * 老系统(安卓 4.x,SDK_INT&lt;21)极简手填配置页。
 * <p>
 * 命根子:**纯 android.app.Activity + android.widget.*,零现代库依赖**(不用 AppCompat/zxing/
 * security-crypto),UI 全程序化构建(不 inflate XML,避免主题/资源牵连现代库)。主题在 Manifest
 * 指 DeviceDefault(4.x 也有;Material 是 21+)。配置经 {@link Prefs} 落普通 SharedPreferences
 * (4.x 无 Keystore,Prefs 自动明文回退)。施工图 §3.3。
 * <p>
 * 现代设备(5.0+)永远走 SetupActivity,不会进这里——本页只为 4.x 兜底。
 */
public class LegacySetupActivity extends Activity {

    private static final int REQ_SCAN = 1001;

    private EditText urlEt, tokenEt;

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);

        int pad = dp(20), gap = dp(12);

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);

        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setPadding(pad, pad, pad, pad);
        scroll.addView(col, new ScrollView.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        TextView title = new TextView(this);
        title.setText(R.string.app_name);
        title.setTextSize(22);
        title.setPadding(0, 0, 0, gap);
        col.addView(title);

        TextView hint = new TextView(this);
        hint.setText(R.string.legacy_setup_hint);
        hint.setPadding(0, 0, 0, gap);
        col.addView(hint);

        TextView urlLabel = new TextView(this);
        urlLabel.setText(R.string.label_url);
        col.addView(urlLabel);

        urlEt = new EditText(this);
        urlEt.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        urlEt.setSingleLine(true);
        urlEt.setHint("http://192.168.x.x:8585");
        col.addView(urlEt);

        TextView tokenLabel = new TextView(this);
        tokenLabel.setText(R.string.label_token);
        tokenLabel.setPadding(0, gap, 0, 0);
        col.addView(tokenLabel);

        tokenEt = new EditText(this);
        tokenEt.setInputType(InputType.TYPE_CLASS_TEXT);
        tokenEt.setSingleLine(true);
        tokenEt.setHint(R.string.token_hint);
        col.addView(tokenEt);

        Prefs prefs = new Prefs(this);
        if (prefs.isConfigured()) {                 // 「重新配置」进来时回填现有值
            urlEt.setText(prefs.baseUrl());
            tokenEt.setText(prefs.token());
        }

        Button save = new Button(this);
        save.setText(R.string.save_start);
        LinearLayout.LayoutParams slp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        slp.topMargin = gap;
        save.setLayoutParams(slp);
        save.setOnClickListener(v -> doSave());
        col.addView(save);

        // 扫码配置:复用锁竖屏的 PortraitCaptureActivity(ZXing)。纯 Activity 没有 AndroidX
        // ActivityResult,走经典 startActivityForResult;结果在 onActivityResult 解析。
        // 注意:ZXing 类只在点按时才加载,看板 kiosk 路径(MainActivity)不受牵连。
        Button scan = new Button(this);
        scan.setText(R.string.scan_qr);
        LinearLayout.LayoutParams scanLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        scanLp.topMargin = gap;
        scan.setLayoutParams(scanLp);
        scan.setOnClickListener(v -> {
            try {
                startActivityForResult(new Intent(this, PortraitCaptureActivity.class), REQ_SCAN);
            } catch (Throwable e) {   // 老机相机/库异常不崩,降级手填
                Toast.makeText(this, R.string.scan_unrecognized, Toast.LENGTH_LONG).show();
            }
        });
        col.addView(scan);

        // 在线更新(走 GitHub;4.x 由 UpdateChecker 强开 TLS1.2)。
        Button upd = new Button(this);
        upd.setText(R.string.cfg_check_update);
        LinearLayout.LayoutParams updLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        updLp.topMargin = gap;
        upd.setLayoutParams(updLp);
        upd.setOnClickListener(v -> LegacyUpdate.checkAndPrompt(this, true));
        col.addView(upd);

        TextView note = new TextView(this);
        note.setText(R.string.legacy_setup_note);
        note.setTextSize(12);
        note.setGravity(Gravity.START);
        note.setPadding(0, gap, 0, 0);
        col.addView(note);

        setContentView(scroll);
    }

    private void doSave() {
        String url = urlEt.getText().toString().trim();
        if (TextUtils.isEmpty(url)) {
            urlEt.setError(getString(R.string.err_need_url));
            return;
        }
        new Prefs(this).save(url, tokenEt.getText().toString());
        startActivity(new Intent(this, MainActivity.class));
        finish();
    }

    @Override
    protected void onActivityResult(int req, int res, Intent data) {
        super.onActivityResult(req, res, data);
        if (req == REQ_SCAN && res == RESULT_OK && data != null) {
            String content = data.getStringExtra(com.google.zxing.client.android.Intents.Scan.RESULT);
            if (content != null && !content.isEmpty()) applyScanned(content);
        }
    }

    /** 解析二维码内容:JSON {url,token} 或直接 /app 链接(与 SetupActivity 同款)。 */
    private void applyScanned(String content) {
        content = content.trim();
        try {
            if (content.startsWith("{")) {
                JSONObject o = new JSONObject(content);
                urlEt.setText(o.optString("url", ""));
                tokenEt.setText(o.optString("token", ""));
            } else if (content.startsWith("http")) {
                Uri u = Uri.parse(content);
                String base = u.getScheme() + "://" + u.getHost()
                        + (u.getPort() > 0 ? ":" + u.getPort() : "");
                urlEt.setText(base);
                String t = u.getQueryParameter("token");
                tokenEt.setText(t == null ? "" : t);
            } else {
                Toast.makeText(this, R.string.scan_unrecognized, Toast.LENGTH_LONG).show();
                return;
            }
            Toast.makeText(this, R.string.scan_ok, Toast.LENGTH_SHORT).show();
        } catch (Exception e) {
            Toast.makeText(this, R.string.scan_unrecognized, Toast.LENGTH_LONG).show();
        }
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
