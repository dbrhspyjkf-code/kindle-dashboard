package com.kindledash.app;

import android.content.Context;
import android.os.Build;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.InetAddress;
import java.net.Socket;
import java.net.URL;

import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSocket;
import javax.net.ssl.SSLSocketFactory;

/**
 * 在线更新:查 GitHub Release 最新版 → 比 versionCode → 下载 APK。
 * 安装动作在 {@link SettingsActivity}(要 FileProvider + 用户授权,侧载不能静默)。
 *
 * 版本约定:APK 附件命名 `MoshuiDesktop-<versionName>-<versionCode>.apk`,从文件名尾部解析 versionCode
 *  整数比对(单调、最可靠;不依赖 tag 格式)。更新说明取 Release 的 body。
 * 全程**工作线程**调用(同步阻塞)。GitHub API 匿名 60 次/小时/IP,手动检查足够。
 */
final class UpdateChecker {

    // 仓库(改这两行即可换 owner/repo)
    static final String OWNER = "yizhixiaoheigou";
    static final String REPO = "kindle-dashboard";
    private static final String LATEST_API =
            "https://api.github.com/repos/" + OWNER + "/" + REPO + "/releases/latest";

    private static final String UA = "MoshuiDesktop-Updater";  // GitHub API 无 UA 会 403
    private static final int CONNECT_TIMEOUT = 10000;
    private static final int READ_TIMEOUT = 20000;

    private UpdateChecker() {}

    static class UpdateInfo {
        int versionCode = -1;       // 远端最新版 versionCode(从 asset 文件名解析)
        String versionName = "";    // Release 的 tag_name(展示用)
        String notes = "";          // Release body(更新说明)
        String apkUrl = "";         // APK 附件下载地址
        String apkName = "";        // APK 附件文件名
        boolean hasUpdate = false;  // 远端 > 本机
    }

    /** 查最新版。currentVersionCode=本机当前版本。返回 UpdateInfo(apkUrl 空=没找到 APK 附件)。 */
    static UpdateInfo check(int currentVersionCode) throws Exception {
        String json = httpGetString(LATEST_API);
        JSONObject o = new JSONObject(json);
        UpdateInfo u = new UpdateInfo();
        u.versionName = o.optString("tag_name", "");
        u.notes = o.optString("body", "");
        JSONArray assets = o.optJSONArray("assets");
        for (int i = 0; assets != null && i < assets.length(); i++) {
            JSONObject a = assets.optJSONObject(i);
            if (a == null) continue;
            String name = a.optString("name", "");
            if (name.toLowerCase().endsWith(".apk")) {
                u.apkName = name;
                u.apkUrl = a.optString("browser_download_url", "");
                u.versionCode = parseVersionCode(name);
                break;
            }
        }
        u.hasUpdate = !u.apkUrl.isEmpty() && u.versionCode > currentVersionCode;
        return u;
    }

    /** 从 `名字-<versionName>-<versionCode>.apk` 尾部解析 versionCode;解析不出返回 -1。 */
    static int parseVersionCode(String apkName) {
        try {
            int dot = apkName.toLowerCase().lastIndexOf(".apk");
            String base = apkName.substring(0, dot);
            String tail = base.substring(base.lastIndexOf('-') + 1);
            return Integer.parseInt(tail.trim());
        } catch (Exception e) {
            return -1;
        }
    }

    interface Progress { void on(int pct); }

    /** 下载 APK 到 app 外部缓存的 update/ 目录(FileProvider 可共享),返回文件。 */
    static File download(Context ctx, String url, String fileName, Progress p) throws Exception {
        File dir = new File(ctx.getExternalFilesDir(null), "update");
        if (!dir.exists()) dir.mkdirs();
        File out = new File(dir, safeName(fileName));
        HttpURLConnection c = openFollow(url);
        try {
            int len = c.getContentLength();
            try (InputStream in = c.getInputStream();
                 FileOutputStream fo = new FileOutputStream(out)) {
                byte[] buf = new byte[8192];
                int n; long total = 0; int last = -1;
                while ((n = in.read(buf)) != -1) {
                    fo.write(buf, 0, n);
                    total += n;
                    if (len > 0 && p != null) {
                        int pct = (int) (total * 100 / len);
                        if (pct != last) { last = pct; p.on(pct); }
                    }
                }
            }
        } finally {
            c.disconnect();
        }
        return out;
    }

    private static String safeName(String n) {
        if (n == null || n.isEmpty()) return "update.apk";
        return n.replaceAll("[^A-Za-z0-9._-]", "_");
    }

    private static String httpGetString(String url) throws Exception {
        HttpURLConnection c = openFollow(url);
        c.setRequestProperty("Accept", "application/vnd.github+json");
        try (InputStream in = c.getInputStream()) {
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            byte[] buf = new byte[4096]; int n;
            while ((n = in.read(buf)) != -1) bos.write(buf, 0, n);
            return new String(bos.toByteArray(), "UTF-8");
        } finally {
            c.disconnect();
        }
    }

    /** 打开连接并手动跟随重定向(含 http↔https 跨协议,HttpURLConnection 默认不跨协议跟随)。
     *  GitHub 下载地址会 302 到对象存储,必须跟随。 */
    private static HttpURLConnection openFollow(String url) throws Exception {
        HttpURLConnection c = null;
        for (int hop = 0; hop < 5; hop++) {
            c = (HttpURLConnection) new URL(url).openConnection();
            c.setConnectTimeout(CONNECT_TIMEOUT);
            c.setReadTimeout(READ_TIMEOUT);
            c.setInstanceFollowRedirects(true);
            c.setRequestProperty("User-Agent", UA);   // GitHub 必需
            applyTls12(c);                             // 安卓 4.x 默认禁 TLS1.2,GitHub 要 TLS1.2 → 强开
            int code = c.getResponseCode();
            if (code == HttpURLConnection.HTTP_MOVED_PERM
                    || code == HttpURLConnection.HTTP_MOVED_TEMP
                    || code == HttpURLConnection.HTTP_SEE_OTHER
                    || code == 307 || code == 308) {
                String loc = c.getHeaderField("Location");
                c.disconnect();
                if (loc == null) throw new java.io.IOException("重定向缺 Location");
                url = loc;
                continue;
            }
            if (code >= 400) {
                c.disconnect();
                throw new java.io.IOException("HTTP " + code);
            }
            return c;
        }
        throw new java.io.IOException("重定向次数过多");
    }

    /**
     * 安卓 4.x(API&lt;22)默认禁用 TLS 1.2,而 GitHub 强制 TLS 1.2 → HTTPS 握手直接失败。
     * 给 HTTPS 连接套一层 socket factory 强制开启 TLS 1.2,老安卓才能连上 GitHub 在线更新。
     * 22+ 默认已开 TLS 1.2,不动(也不影响 5.0+ 现状)。装不上就静默回退系统默认(真机以结果为准)。
     */
    private static void applyTls12(HttpURLConnection c) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP_MR1) return;   // API22+ 无需
        if (!(c instanceof HttpsURLConnection)) return;
        try {
            SSLContext ctx = SSLContext.getInstance("TLSv1.2");
            ctx.init(null, null, null);
            ((HttpsURLConnection) c).setSSLSocketFactory(new Tls12SocketFactory(ctx.getSocketFactory()));
        } catch (Exception ignore) {
            // 设备根本不支持 TLS1.2 → 用系统默认(基本会失败,属老机硬限制,降级到「手动侧载」)
        }
    }

    /** 包装 SSLSocketFactory:每个创建出的 SSLSocket 强制启用 TLS 1.2/1.1。 */
    private static final class Tls12SocketFactory extends SSLSocketFactory {
        private static final String[] PROTOS = {"TLSv1.2", "TLSv1.1", "TLSv1"};
        private final SSLSocketFactory d;

        Tls12SocketFactory(SSLSocketFactory delegate) { this.d = delegate; }

        @Override public String[] getDefaultCipherSuites() { return d.getDefaultCipherSuites(); }
        @Override public String[] getSupportedCipherSuites() { return d.getSupportedCipherSuites(); }

        private Socket patch(Socket s) {
            if (s instanceof SSLSocket) ((SSLSocket) s).setEnabledProtocols(PROTOS);
            return s;
        }
        @Override public Socket createSocket(Socket s, String h, int p, boolean a) throws java.io.IOException { return patch(d.createSocket(s, h, p, a)); }
        @Override public Socket createSocket(String h, int p) throws java.io.IOException { return patch(d.createSocket(h, p)); }
        @Override public Socket createSocket(String h, int p, InetAddress lh, int lp) throws java.io.IOException { return patch(d.createSocket(h, p, lh, lp)); }
        @Override public Socket createSocket(InetAddress h, int p) throws java.io.IOException { return patch(d.createSocket(h, p)); }
        @Override public Socket createSocket(InetAddress h, int p, InetAddress lh, int lp) throws java.io.IOException { return patch(d.createSocket(h, p, lh, lp)); }
    }
}
