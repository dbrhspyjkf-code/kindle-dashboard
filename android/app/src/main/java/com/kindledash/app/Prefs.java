package com.kindledash.app;

import android.annotation.TargetApi;
import android.content.Context;
import android.content.SharedPreferences;
import android.os.Build;

import androidx.security.crypto.EncryptedSharedPreferences;
import androidx.security.crypto.MasterKey;

/**
 * 配置存储:服务器地址 + 访问令牌。
 * API 23+ 用 EncryptedSharedPreferences(Android Keystore 加密);23 以下(含 4.x)用普通 SharedPreferences
 * (局域网令牌,非高敏感;诚实降级,不崩)。令牌不进日志。
 * <p>
 * 老系统兼容(minSdk17)关键:加密库(security-crypto/tink)声明 minSdk21,4.x 上连类校验都过不了。
 * 故 EncryptedSharedPreferences/MasterKey 的实例化**只在 SDK_INT>=23 时**走、且抽进单独的
 * {@link #createEncrypted} 方法(@TargetApi(23)),让 Dalvik/ART 校验器不会在 4.x 上碰到这些类
 * (类引用集中在那一个方法里,4.x 永不调用即永不加载)。施工图 §3.2。
 */
public class Prefs {
    private static final String FILE = "kindledash_cfg";
    private static final String K_BASE = "base_url";   // 如 http://192.168.1.100:8585
    private static final String K_TOKEN = "token";

    private final SharedPreferences sp;

    public Prefs(Context ctx) {
        SharedPreferences p = null;
        // 仅 API 23+ 才尝试加密;23 以下(含 4.x)直接普通存储,不实例化任何加密库类
        // (避免老系统类加载/校验崩)。加密库声明 minSdk21,4.x 上连引用都不能碰。
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            try {
                p = createEncrypted(ctx);
            } catch (Throwable t) {
                // Keystore 不可用等:回退明文(仍只存本地)
                p = null;
            }
        }
        if (p == null) {
            p = ctx.getSharedPreferences(FILE, Context.MODE_PRIVATE);
        }
        sp = p;
    }

    /** 加密存储的创建,所有 security-crypto 类引用集中于此;只在 SDK_INT>=23 调用(@TargetApi(23))。 */
    @TargetApi(Build.VERSION_CODES.M)
    private static SharedPreferences createEncrypted(Context ctx) throws Exception {
        MasterKey key = new MasterKey.Builder(ctx)
                .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                .build();
        return EncryptedSharedPreferences.create(
                ctx, FILE + "_enc", key,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM);
    }

    public boolean isConfigured() {
        return baseUrl() != null && !baseUrl().isEmpty();
    }

    public String baseUrl() {
        return sp.getString(K_BASE, "");
    }

    public String token() {
        return sp.getString(K_TOKEN, "");
    }

    public void save(String base, String token) {
        sp.edit().putString(K_BASE, normalize(base)).putString(K_TOKEN, token == null ? "" : token.trim()).apply();
    }

    public void clear() {
        sp.edit().clear().apply();
    }

    // ---- 悬浮齿轮位置(用户可拖动,按比例 0~1 存,换分辨率/旋转也稳;-1=未设,用默认右下角)----
    private static final String K_GEAR_FX = "gear_fx";
    private static final String K_GEAR_FY = "gear_fy";

    public void saveGearPos(float fx, float fy) {
        sp.edit().putFloat(K_GEAR_FX, fx).putFloat(K_GEAR_FY, fy).apply();
    }

    public float gearFx() { return sp.getFloat(K_GEAR_FX, -1f); }

    public float gearFy() { return sp.getFloat(K_GEAR_FY, -1f); }

    /** 拼接活 HTML 外壳地址:base + /app?force=app&token=...(现代 5.0+ 路径)。
     * 现代 App 已在 MainActivity 按 SDK_INT>=21 分流,这里显式 force=app,避免某些现代 WebView
     * UA 里带 `Version/4.0` 被服务端浏览器降级规则误判成 /app-legacy。 */
    public String appUrl() {
        return urlWithToken("/app?force=app");
    }

    /** 拼接 base + path(?token=...);path 以 / 开头。供现代 /app 与老系统降级页(/web-simple、后续 /app-legacy)复用。 */
    public String urlWithToken(String path) {
        String base = normalize(baseUrl());
        String t = token();
        String url = base + path;
        if (t != null && !t.isEmpty()) {
            // path 可能已带查询串(如 /app?force=app)→ 用 & 续接,否则用 ?;
            // 否则拼成 /app?force=app?token=... 第二个 ? 非法,token 参数丢失致 401。
            url += (path.indexOf('?') >= 0 ? "&" : "?") + "token=" + android.net.Uri.encode(t);
        }
        return url;
    }

    static String normalize(String u) {
        if (u == null) return "";
        u = u.trim();
        if (u.isEmpty()) return "";
        if (!u.startsWith("http://") && !u.startsWith("https://")) {
            u = "http://" + u;
        }
        while (u.endsWith("/")) {
            u = u.substring(0, u.length() - 1);
        }
        return u;
    }
}
