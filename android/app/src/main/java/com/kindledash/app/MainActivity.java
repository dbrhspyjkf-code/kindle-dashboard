package com.kindledash.app;

import android.annotation.SuppressLint;
import android.annotation.TargetApi;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.ActivityInfo;
import android.graphics.Color;
import android.os.BatteryManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewConfiguration;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.ImageButton;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * 看板主界面:一个全屏系统 WebView(android.webkit.WebView)加载服务器的活 HTML 外壳(/app?token=...)。
 * 职责全是「非 UI」能力:全屏沉浸 + 屏幕常亮 + 初始加载失败重连。业务 UI 全在 WebView 里的 HTML。
 * 用系统自带 WebView(安卓 5.0+ 均有、可经应用商店更新),不打包引擎 —— APK 仅几 MB。
 */
public class MainActivity extends Activity {

    private WebView webView;
    private View errorOverlay;
    private TextView errorText;
    private Prefs prefs;
    private FrameLayout rootLayout;
    private FrameLayout gearWrap;      // 齿轮 + 红点的容器(拖动/定位的是它,红点天然跟随)
    private ImageButton gearBtn;
    private View redDot;               // "有新版"小红点(默认隐藏)
    private String url;

    private static final long UPDATE_CHECK_INTERVAL_MS = 6L * 60 * 60 * 1000;   // 每 6 小时静默查一次
    private static final long LEGACY_UPDATE_CHECK_INTERVAL_MS = 24L * 60 * 60 * 1000;   // 老安卓挂墙:每天静默查一次
    private final Runnable updateCheck = new Runnable() {
        @Override public void run() {
            doUpdateCheck();
            handler.postDelayed(this, UPDATE_CHECK_INTERVAL_MS);
        }
    };
    private final Runnable legacyUpdateCheck = new Runnable() {
        @Override public void run() {
            LegacyUpdate.checkAndPrompt(MainActivity.this, false);
            handler.postDelayed(this, LEGACY_UPDATE_CHECK_INTERVAL_MS);
        }
    };
    private final Handler handler = new Handler(Looper.getMainLooper());
    private boolean firstLoadOk = false;
    private boolean pageError = false;     // 本次加载是否出错(主框架),由 onReceivedError 置位
    private Runnable retry;
    // 安卓 4.2/4.3(无 IMMERSIVE_STICKY):导航栏被触摸唤出后系统不会自动回藏 → 定时手动回藏
    private final Runnable reHideNav = new Runnable() {
        @Override public void run() { if (hasWindowFocus()) hideSystemUI(); }
    };

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);

        prefs = new Prefs(this);

        // ── 老系统兼容分流(施工图 §1/§3):一个 minSdk17 包,按 Build.VERSION.SDK_INT 分两条路 ──
        // 安卓 4.x(<21):极简路径,绝不碰任何现代库(SetupActivity/zxing、悬浮齿轮→SettingsActivity、
        // 在线更新都依赖现代库/交互),否则老系统类加载即崩。下面 5.0+ 全部逻辑整体包在 >=21 分支内,
        // 行为与改动前一字不变。
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.LOLLIPOP) {
            startLegacy();
            return;
        }

        // ========================= 以下为安卓 5.0+(SDK_INT>=21)现状,一字不变 =========================
        if (!prefs.isConfigured()) {                 // 没配过 → 先去配置页
            startActivity(new Intent(this, SetupActivity.class));
            finish();
            return;
        }
        url = prefs.appUrl();

        // 锁横屏:看板是 800×600 横屏设计,横屏铺满整屏(壁挂看板本就横放)
        setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE);

        // 壁挂常亮:屏幕不息屏
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        FrameLayout root = new FrameLayout(this);
        rootLayout = root;
        root.setBackgroundColor(Color.WHITE);
        webView = new WebView(this);
        webView.setBackgroundColor(Color.WHITE);
        configureWebView(webView);
        root.addView(webView, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));
        root.addView(buildGearButton());     // 悬浮齿轮:每页可见、可拖动的设置入口
        root.addView(buildErrorOverlay());   // 错误层在最上,出错时盖住齿轮
        setContentView(root);

        // 首帧 layout 后再摆齿轮初始位置(此时 root 才有尺寸):读上次拖到的位置,没有则默认右下角
        root.post(this::placeGearInitial);

        loadDashboard();
        startUpdateWatch();   // 后台静默查新版,有则齿轮亮红点
    }

    @SuppressLint("SetJavaScriptEnabled")
    private void configureWebView(WebView wv) {
        WebSettings s = wv.getSettings();
        s.setJavaScriptEnabled(true);            // 轮询 / 动作接口靠页面内 JS
        s.setDomStorageEnabled(true);            // sessionStorage 存令牌、页面状态
        // 让 WebView 按控件真实 CSS 宽度布局(=设备宽),交给 /app 页自己的
        // viewport meta(width=device-width)+ 自适应缩放 JS 处理。
        // 这两项设 true 会让系统 WebView 按更宽的布局视口 + overview 缩放,
        // 与页面 JS 的 scale 叠加 → 内容缩成屏幕中间一小块、四周全黑(踩过)。
        s.setLoadWithOverviewMode(false);
        s.setUseWideViewPort(false);
        // 暴露本机电量给页面(页脚显示手机自己的电量,而非 Kindle 上报的)。
        // minSdk 21:只有 @JavascriptInterface 注解的方法可被 JS 调,安全。
        wv.addJavascriptInterface(new BatteryBridge(this), "KDAndroid");
        wv.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView view, String u) {
                if (!pageError) { firstLoadOk = true; hideError(); }
            }
            // API 21~22:主框架加载错误走这个已废弃重载
            @SuppressWarnings("deprecation")
            @Override
            public void onReceivedError(WebView view, int errorCode, String description, String failingUrl) {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) return;   // 23+ 由下面的新重载处理
                onMainFrameError();
            }
            // API 23+:带 WebResourceRequest,可判断是否主框架(子资源失败不算断线)
            @TargetApi(Build.VERSION_CODES.M)
            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) onMainFrameError();
            }
        });
    }

    private void onMainFrameError() {
        // 初始/网络错误:显示重连提示并退避重试(诚实降级,不白屏)。
        // 注:连上后服务器再掉线由页面内 JS 自己处理(显示「重连中」继续轮询)。
        pageError = true;
        showError(getString(R.string.reconnecting));
        scheduleRetry();
    }

    private void loadDashboard() {
        pageError = false;
        webView.loadUrl(url);
    }

    /**
     * 安卓 4.x(SDK_INT<21)极简启动路径:纯 Activity + 全屏常亮 WebView,kiosk 主路径**不碰现代库**
     * (不挂悬浮齿轮、不进 SettingsActivity/AppCompat)。在线更新走 GitHub(4.x 经 UpdateChecker 强开
     * TLS1.2,安装用 file:// 不引 FileProvider);扫码用 ZXing —— 两者都只在 LegacySetupActivity 里**按需**
     * 触发(用户点按时才加载相应类),不在 kiosk 渲染路径上,故对 4.2 稳定性无影响。
     * 未配置 → 极简手填配置页 LegacySetupActivity。已配置 → 加载老系统降级页:
     * **第一步「地基」先用已有的 /web-simple 静态降级图占位,第二步换成 /app-legacy 活页**。
     * 施工图 §3.3 / §5 第一步。
     */
    @SuppressLint("SetJavaScriptEnabled")
    private void startLegacy() {
        if (!prefs.isConfigured()) {
            startActivity(new Intent(this, LegacySetupActivity.class));
            finish();
            return;
        }
        // 4.x 加载老系统降级活页(float-CSS+ES5,服务端 styles/legacy/ 渲染)。
        // 服务端连不上/旧版无此路由时,WebView onReceivedError 会显示「重试/重新配置」(诚实降级)。
        url = prefs.urlWithToken("/app-legacy");

        setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        // 全屏隐藏状态栏+导航栏统一走 setSystemUiVisibility(enableImmersive/hideSystemUI),
        // 不用 FLAG_FULLSCREEN(那只藏状态栏、还会与 systemUiVisibility 打架致导航栏残留阴影)。

        FrameLayout root = new FrameLayout(this);
        rootLayout = root;
        root.setBackgroundColor(Color.parseColor("#ffffff"));   // 浅色 editorial 底,首帧不闪黑
        webView = new WebView(this);
        webView.setBackgroundColor(Color.parseColor("#ffffff"));   // 浅色,与新 legacy 看板底色一致
        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setLoadWithOverviewMode(false);
        s.setUseWideViewPort(false);
        // 不缓存:外壳 HTML(含 <style>)与页面片段都实时取。否则 WebView 缓存住旧外壳 CSS,
        // 服务端改了 legacy 样式后设备仍显示旧版(踩过:暗色重设计上线后真机仍是旧浅色版)。
        s.setCacheMode(WebSettings.LOAD_NO_CACHE);
        webView.setWebViewClient(new WebViewClient() {
            @Override public void onPageFinished(WebView v, String u) {
                if (!pageError) hideError();
            }
            // 4.x 只有这个已废弃重载(无 WebResourceRequest)
            @SuppressWarnings("deprecation")
            @Override public void onReceivedError(WebView v, int code, String desc, String failingUrl) {
                onMainFrameError();
            }
        });
        root.addView(webView, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));
        root.addView(buildLegacyErrorOverlay());   // 连不上时给「重试 / 重新配置」(进 LegacySetupActivity)
        setContentView(root);
        enableImmersive();   // 隐藏导航栏:4.4+ 真沉浸 sticky;4.2/4.3 触摸唤出后定时回藏
        loadDashboard();
        // 看板起来后自动查一次 GitHub 在线更新(4.x 由 UpdateChecker 强开 TLS1.2),之后每天静默查一次;
        // 有新版弹对话框(用户确认才下载安装),无/失败静默不打扰。手动检查在 LegacySetupActivity。
        handler.postDelayed(legacyUpdateCheck, 12000);
    }

    /** 老系统降级路径的错误层:重试 + 重新配置(进 LegacySetupActivity,纯 Activity)。复用 errorOverlay/errorText 字段。 */
    private FrameLayout buildLegacyErrorOverlay() {
        FrameLayout wrap = new FrameLayout(this);
        wrap.setBackgroundColor(Color.parseColor("#111111"));
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setGravity(Gravity.CENTER);
        wrap.addView(col, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));

        errorText = new TextView(this);
        errorText.setTextColor(Color.WHITE);
        errorText.setTextSize(18);
        errorText.setGravity(Gravity.CENTER);
        errorText.setPadding(40, 20, 40, 24);
        col.addView(errorText);

        Button retryBtn = new Button(this);
        retryBtn.setText(R.string.retry_now);
        retryBtn.setOnClickListener(v -> { cancelRetry(); loadDashboard(); });
        col.addView(retryBtn);

        Button reconfig = new Button(this);
        reconfig.setText(R.string.reconfigure);
        reconfig.setOnClickListener(v -> {
            startActivity(new Intent(this, LegacySetupActivity.class));
            finish();
        });
        col.addView(reconfig);

        errorOverlay = wrap;
        errorOverlay.setVisibility(View.GONE);
        return wrap;
    }

    /**
     * 悬浮齿轮设置入口:单色圆形磨砂小按钮、半透明,**可拖动**——用户长按拖到屏幕任意位置,松手记住
     * (按比例存 Prefs,下次打开还在那)。轻点=进设置,拖动=挪位置(靠 touchSlop 区分)。所有页面都在
     * (原生悬浮层,不碰 WebView 页面模板、不影响 Kindle 出图)。单色磨砂跟墨水屏单色调一致、不突兀;
     * 用绝对定位(gravity TOP|START + leftMargin/topMargin),初始位置见 placeGearInitial()。
     */
    private FrameLayout buildGearButton() {
        float density = getResources().getDisplayMetrics().density;
        int sz = Math.round(36 * density);
        int pad = Math.round(7 * density);

        gearWrap = new FrameLayout(this);
        FrameLayout.LayoutParams wlp = new FrameLayout.LayoutParams(sz, sz);
        wlp.gravity = Gravity.TOP | Gravity.START;               // 绝对定位,靠 margin 摆位
        gearWrap.setLayoutParams(wlp);

        final ImageButton gear = new ImageButton(this);
        gearBtn = gear;
        gear.setImageResource(R.drawable.ic_gear);
        gear.setColorFilter(Color.parseColor("#4D4D4D"));        // 深灰齿轮(浅色看板上不刺眼)
        gear.setBackgroundResource(R.drawable.gear_bg);          // 圆形磨砂底
        gear.setScaleType(android.widget.ImageView.ScaleType.CENTER_INSIDE);
        gear.setAlpha(0.5f);                                     // 平时很安静
        gear.setContentDescription(getString(R.string.open_settings));
        gear.setPadding(pad, pad, pad, pad);
        gearWrap.addView(gear, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));

        // 右上角"有新版"红点(默认隐藏)
        redDot = new View(this);
        redDot.setBackgroundResource(R.drawable.red_dot);
        int dot = Math.round(9 * density);
        FrameLayout.LayoutParams dlp = new FrameLayout.LayoutParams(dot, dot);
        dlp.gravity = Gravity.TOP | Gravity.END;
        redDot.setLayoutParams(dlp);
        redDot.setVisibility(View.GONE);
        gearWrap.addView(redDot);

        final int slop = ViewConfiguration.get(this).getScaledTouchSlop();
        final float[] downXY = new float[2];    // 按下时的屏幕坐标
        final int[] start = new int[2];         // 按下时 gearWrap 的 margin
        final boolean[] moved = {false};
        gear.setOnTouchListener((v, e) -> {
            FrameLayout.LayoutParams p = (FrameLayout.LayoutParams) gearWrap.getLayoutParams();
            switch (e.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
                    downXY[0] = e.getRawX(); downXY[1] = e.getRawY();
                    start[0] = p.leftMargin; start[1] = p.topMargin;
                    moved[0] = false;
                    gear.setAlpha(0.92f);
                    return true;
                case MotionEvent.ACTION_MOVE: {
                    int dx = (int) (e.getRawX() - downXY[0]);
                    int dy = (int) (e.getRawY() - downXY[1]);
                    if (Math.abs(dx) > slop || Math.abs(dy) > slop) moved[0] = true;
                    int maxX = Math.max(0, rootLayout.getWidth() - gearWrap.getWidth());
                    int maxY = Math.max(0, rootLayout.getHeight() - gearWrap.getHeight());
                    p.leftMargin = clamp(start[0] + dx, 0, maxX);
                    p.topMargin = clamp(start[1] + dy, 0, maxY);
                    gearWrap.setLayoutParams(p);
                    return true;
                }
                case MotionEvent.ACTION_UP:
                case MotionEvent.ACTION_CANCEL:
                    gear.setAlpha(0.5f);
                    if (!moved[0]) {
                        gear.performClick();               // 没怎么动=点击,进设置
                    } else {
                        int maxX = Math.max(1, rootLayout.getWidth() - gearWrap.getWidth());
                        int maxY = Math.max(1, rootLayout.getHeight() - gearWrap.getHeight());
                        prefs.saveGearPos(p.leftMargin / (float) maxX, p.topMargin / (float) maxY);
                    }
                    return true;
            }
            return false;
        });
        gear.setOnClickListener(v -> startActivity(new Intent(this, SettingsActivity.class)));
        return gearWrap;
    }

    /** 首帧 layout 后摆齿轮初始位置:读上次拖到的比例位置,没有则默认右下角(页脚区,最不抢眼)。 */
    private void placeGearInitial() {
        if (gearWrap == null || rootLayout == null || rootLayout.getWidth() == 0) return;
        float density = getResources().getDisplayMetrics().density;
        int w = gearWrap.getWidth() > 0 ? gearWrap.getWidth() : Math.round(36 * density);
        int margin = Math.round(12 * density);
        int maxX = Math.max(0, rootLayout.getWidth() - w);
        int maxY = Math.max(0, rootLayout.getHeight() - w);
        float fx = prefs.gearFx(), fy = prefs.gearFy();
        int x, y;
        if (fx < 0 || fy < 0) { x = maxX - margin; y = maxY - margin; }   // 默认右下角
        else { x = Math.round(fx * maxX); y = Math.round(fy * maxY); }
        FrameLayout.LayoutParams lp = (FrameLayout.LayoutParams) gearWrap.getLayoutParams();
        lp.leftMargin = clamp(x, 0, maxX);
        lp.topMargin = clamp(y, 0, maxY);
        gearWrap.setLayoutParams(lp);
    }

    /** 后台静默查新版:启动 8 秒后查一次 + 之后每 6 小时;发现新版亮红点。 */
    private void startUpdateWatch() {
        handler.postDelayed(updateCheck, 8000);
    }

    private void doUpdateCheck() {
        new Thread(() -> {
            try {
                int cur = getPackageManager().getPackageInfo(getPackageName(), 0).versionCode;
                UpdateChecker.UpdateInfo u = UpdateChecker.check(cur);
                runOnUiThread(() -> {
                    if (redDot != null) redDot.setVisibility(u.hasUpdate ? View.VISIBLE : View.GONE);
                });
            } catch (Exception ignored) {
                // 网络/接口异常:静默忽略,不打扰看板;下一轮再试
            }
        }).start();
    }

    private static int clamp(int v, int lo, int hi) {
        return v < lo ? lo : (v > hi ? hi : v);
    }

    private FrameLayout buildErrorOverlay() {
        FrameLayout wrap = new FrameLayout(this);
        wrap.setBackgroundColor(Color.parseColor("#111111"));
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setGravity(Gravity.CENTER);
        FrameLayout.LayoutParams clp = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT);
        wrap.addView(col, clp);

        errorText = new TextView(this);
        errorText.setTextColor(Color.WHITE);
        errorText.setTextSize(18);
        errorText.setGravity(Gravity.CENTER);
        errorText.setPadding(40, 20, 40, 24);
        col.addView(errorText);

        Button retryBtn = new Button(this);
        retryBtn.setText(R.string.retry_now);
        retryBtn.setOnClickListener(v -> { cancelRetry(); loadDashboard(); });
        col.addView(retryBtn);

        Button reconfig = new Button(this);
        reconfig.setText(R.string.reconfigure);
        reconfig.setOnClickListener(v -> {
            startActivity(new Intent(this, SetupActivity.class));
            finish();
        });
        col.addView(reconfig);

        errorOverlay = wrap;
        errorOverlay.setVisibility(View.GONE);
        return wrap;
    }

    private void showError(String msg) {
        if (errorText != null) errorText.setText(msg + "\n" + url);
        if (errorOverlay != null) errorOverlay.setVisibility(View.VISIBLE);
    }

    private void hideError() {
        if (errorOverlay != null) errorOverlay.setVisibility(View.GONE);
    }

    private void scheduleRetry() {
        cancelRetry();
        retry = this::loadDashboard;
        handler.postDelayed(retry, 4000);     // 4s 退避重试
    }

    private void cancelRetry() {
        if (retry != null) handler.removeCallbacks(retry);
        retry = null;
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) hideSystemUI();
    }

    /** 全屏沉浸:隐藏状态栏 + 导航栏(API 19+ 标志,兼容 21)。 */
    private void hideSystemUI() {
        getWindow().getDecorView().setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                        | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                        | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_FULLSCREEN
                        | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);   // 4.4+ 生效:滑出临时显示后自动回藏
    }

    /**
     * 启用沉浸式导航栏隐藏(legacy 4.x 路径用)。
     * - 安卓 4.4+(API19):`hideSystemUI()` 的 IMMERSIVE_STICKY 直接搞定——平时藏、从边缘滑出临时显示、自动回藏。
     * - 安卓 4.2/4.3(API17/18):无 IMMERSIVE_STICKY,导航栏被触摸唤出后不会自动回藏 → 监听系统 UI 可见性变化,
     *   一旦导航栏重新出现就延时约 3 秒再 `hideSystemUI()` 藏回去(系统能力上限的「碰一下出来、自动回藏」近似)。
     */
    private void enableImmersive() {
        final View decor = getWindow().getDecorView();
        decor.setOnSystemUiVisibilityChangeListener(new View.OnSystemUiVisibilityChangeListener() {
            @Override public void onSystemUiVisibilityChange(int visibility) {
                // 仅 pre-4.4 需要手动回藏(4.4+ 交给 IMMERSIVE_STICKY,避免与之打架)
                if (Build.VERSION.SDK_INT < Build.VERSION_CODES.KITKAT
                        && (visibility & View.SYSTEM_UI_FLAG_HIDE_NAVIGATION) == 0) {
                    handler.removeCallbacks(reHideNav);
                    handler.postDelayed(reHideNav, 3000);
                }
            }
        });
        hideSystemUI();
    }

    @Override
    protected void onDestroy() {
        cancelRetry();
        handler.removeCallbacks(reHideNav);
        handler.removeCallbacks(updateCheck);
        handler.removeCallbacks(legacyUpdateCheck);
        if (webView != null) {
            webView.destroy();
            webView = null;
        }
        super.onDestroy();
    }

    /** 暴露给页面 JS 的本机电量桥(window.KDAndroid)。只读,无副作用。 */
    public static class BatteryBridge {
        private final Context ctx;
        BatteryBridge(Context c) { ctx = c.getApplicationContext(); }

        /** 当前电量百分比(0~100);取不到返回 -1。 */
        @JavascriptInterface
        public int level() {
            try {
                BatteryManager bm = (BatteryManager) ctx.getSystemService(Context.BATTERY_SERVICE);
                if (bm != null) {
                    int l = bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY);
                    if (l >= 0 && l <= 100) return l;
                }
            } catch (Exception ignored) {}
            return -1;
        }

        /** 是否正在充电。 */
        @JavascriptInterface
        public boolean charging() {
            try {
                Intent b = ctx.registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
                if (b != null) {
                    int st = b.getIntExtra(BatteryManager.EXTRA_STATUS, -1);
                    return st == BatteryManager.BATTERY_STATUS_CHARGING || st == BatteryManager.BATTERY_STATUS_FULL;
                }
            } catch (Exception ignored) {}
            return false;
        }
    }
}
