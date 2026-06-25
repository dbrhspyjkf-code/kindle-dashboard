package com.kindledash.app;

import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.net.nsd.NsdManager;
import android.net.nsd.NsdServiceInfo;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.TextUtils;
import android.widget.Button;
import android.widget.EditText;
import android.widget.Toast;

import androidx.activity.result.ActivityResultLauncher;
import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;

import com.journeyapps.barcodescanner.ScanContract;
import com.journeyapps.barcodescanner.ScanOptions;

import org.json.JSONObject;

import java.net.Inet4Address;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;

/**
 * 首次配置页(唯一原生界面):
 *  - 「搜索局域网服务器」:mDNS(NsdManager)发现广播 `_kindledash._tcp` 的看板服务器,自动填地址;
 *  - 「扫码配置」:扫设置页生成的二维码(JSON {url,token} 或 /app 链接),竖屏扫;
 *  - 手填服务器地址 + 访问令牌。
 * 令牌**不经 mDNS 广播**(密钥不上网),发现到的服务器只填地址,令牌仍需扫码/手填。
 */
public class SetupActivity extends AppCompatActivity {

    private static final String SERVICE_TYPE = "_kindledash._tcp.";
    private static final long DISCOVER_TIMEOUT_MS = 5000;

    private EditText urlEt, tokenEt;
    private Button discoverBtn;
    private final Handler ui = new Handler(Looper.getMainLooper());

    private NsdManager nsd;
    private NsdManager.DiscoveryListener discoveryListener;
    private boolean discovering = false;
    private boolean resolving = false;
    private final ArrayDeque<NsdServiceInfo> resolveQueue = new ArrayDeque<>();
    private final List<Server> found = new ArrayList<>();

    /** 一台发现到的服务器。 */
    private static class Server {
        final String label;   // 给用户看的名字
        final String url;     // http://ip:port
        Server(String label, String url) { this.label = label; this.url = url; }
    }

    private final ActivityResultLauncher<ScanOptions> scanLauncher =
            registerForActivityResult(new ScanContract(), result -> {
                if (result.getContents() != null) {
                    applyScanned(result.getContents());
                }
            });

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        setContentView(R.layout.activity_setup);

        urlEt = findViewById(R.id.et_url);
        tokenEt = findViewById(R.id.et_token);
        discoverBtn = findViewById(R.id.btn_discover);
        Button scan = findViewById(R.id.btn_scan);
        Button save = findViewById(R.id.btn_save);

        Prefs prefs = new Prefs(this);
        if (prefs.isConfigured()) {           // 「重新配置」进来时回填现有值
            urlEt.setText(prefs.baseUrl());
            tokenEt.setText(prefs.token());
        }

        discoverBtn.setOnClickListener(v -> startDiscovery());

        scan.setOnClickListener(v -> {
            ScanOptions opts = new ScanOptions();
            opts.setCaptureActivity(PortraitCaptureActivity.class);   // 锁竖屏
            opts.setOrientationLocked(false);                         // 让 Manifest 的 portrait 生效
            opts.setBeepEnabled(false);
            opts.setPrompt(getString(R.string.scan_prompt));
            scanLauncher.launch(opts);
        });

        save.setOnClickListener(v -> doSave());
    }

    // ---------- mDNS 局域网发现 ----------
    private void startDiscovery() {
        if (discovering) return;
        if (nsd == null) nsd = (NsdManager) getSystemService(Context.NSD_SERVICE);
        if (nsd == null) {
            Toast.makeText(this, R.string.discover_unavailable, Toast.LENGTH_LONG).show();
            return;
        }
        found.clear();
        resolveQueue.clear();
        resolving = false;
        discovering = true;
        discoverBtn.setEnabled(false);
        discoverBtn.setText(R.string.discovering);

        discoveryListener = new NsdManager.DiscoveryListener() {
            @Override public void onDiscoveryStarted(String t) {}
            @Override public void onServiceFound(NsdServiceInfo info) {
                resolveQueue.add(info);
                ui.post(SetupActivity.this::resolveNext);
            }
            @Override public void onServiceLost(NsdServiceInfo info) {}
            @Override public void onDiscoveryStopped(String t) {}
            @Override public void onStartDiscoveryFailed(String t, int code) {
                ui.post(() -> finishDiscovery(true));
            }
            @Override public void onStopDiscoveryFailed(String t, int code) {}
        };
        try {
            nsd.discoverServices(SERVICE_TYPE, NsdManager.PROTOCOL_DNS_SD, discoveryListener);
        } catch (Exception e) {
            finishDiscovery(true);
            return;
        }
        ui.postDelayed(() -> finishDiscovery(false), DISCOVER_TIMEOUT_MS);
    }

    /** NsdManager 在旧系统上一次只能 resolve 一个,这里串行排队。 */
    private void resolveNext() {
        if (resolving || resolveQueue.isEmpty() || !discovering) return;
        resolving = true;
        NsdServiceInfo info = resolveQueue.poll();
        nsd.resolveService(info, new NsdManager.ResolveListener() {
            @Override public void onResolveFailed(NsdServiceInfo i, int code) {
                resolving = false;
                ui.post(SetupActivity.this::resolveNext);
            }
            @Override public void onServiceResolved(NsdServiceInfo i) {
                resolving = false;
                ui.post(() -> { addResolved(i); resolveNext(); });
            }
        });
    }

    private void addResolved(NsdServiceInfo i) {
        if (i.getHost() == null || !(i.getHost() instanceof Inet4Address)) return;   // 只要 IPv4
        String ip = i.getHost().getHostAddress();
        int port = i.getPort();
        if (ip == null || port <= 0) return;
        String url = "http://" + ip + ":" + port;
        for (Server s : found) if (s.url.equals(url)) return;   // 去重
        String name = txt(i, "name");
        String label = (name != null && !name.isEmpty() ? name : i.getServiceName()) + "  (" + ip + ":" + port + ")";
        found.add(new Server(label, url));
    }

    private static String txt(NsdServiceInfo i, String key) {
        try {
            byte[] v = i.getAttributes().get(key);
            return v == null ? null : new String(v, "UTF-8");
        } catch (Exception e) {
            return null;
        }
    }

    private void finishDiscovery(boolean failed) {
        if (!discovering) return;
        discovering = false;
        try { if (nsd != null && discoveryListener != null) nsd.stopServiceDiscovery(discoveryListener); }
        catch (Exception ignored) {}
        discoveryListener = null;
        discoverBtn.setEnabled(true);
        discoverBtn.setText(R.string.discover_server);

        if (failed) {
            Toast.makeText(this, R.string.discover_unavailable, Toast.LENGTH_LONG).show();
            return;
        }
        if (found.isEmpty()) {
            Toast.makeText(this, R.string.discover_none, Toast.LENGTH_LONG).show();
        } else if (found.size() == 1) {
            pick(found.get(0));
        } else {
            String[] items = new String[found.size()];
            for (int k = 0; k < found.size(); k++) items[k] = found.get(k).label;
            new AlertDialog.Builder(this)
                    .setTitle(R.string.discover_pick_title)
                    .setItems(items, (d, which) -> pick(found.get(which)))
                    .show();
        }
    }

    private void pick(Server s) {
        urlEt.setText(s.url);
        Toast.makeText(this, getString(R.string.discover_filled), Toast.LENGTH_LONG).show();
    }

    private void applyScanned(String content) {
        content = content.trim();
        try {
            if (content.startsWith("{")) {                 // JSON {url, token}
                JSONObject o = new JSONObject(content);
                urlEt.setText(o.optString("url", ""));
                tokenEt.setText(o.optString("token", ""));
            } else if (content.startsWith("http")) {       // 直接是 /app 链接
                Uri u = Uri.parse(content);
                String base = u.getScheme() + "://" + u.getHost() + (u.getPort() > 0 ? ":" + u.getPort() : "");
                urlEt.setText(base);
                String t = u.getQueryParameter("token");
                tokenEt.setText(t == null ? "" : t);
            } else {
                Toast.makeText(this, R.string.scan_unrecognized, Toast.LENGTH_LONG).show();
                return;
            }
            Toast.makeText(this, R.string.scan_ok, Toast.LENGTH_SHORT).show();
        } catch (Exception e) {
            Toast.makeText(this, getString(R.string.scan_unrecognized), Toast.LENGTH_LONG).show();
        }
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
    protected void onDestroy() {
        if (discovering) finishDiscovery(false);
        ui.removeCallbacksAndMessages(null);
        super.onDestroy();
    }
}
