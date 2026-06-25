package com.kindledash.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.ProgressDialog;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.text.InputType;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import androidx.core.content.FileProvider;

import java.io.File;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * 原生分类设置页(v2 核心)。**完全 schema 驱动,不硬编码任何字段**:
 *   进入并发拉 GET /api/schema(分类+字段,服务端已按 language 本地化)+ GET /api/config(当前值);
 *   第一屏=分类列表(各 section),点一类进二级页只显示该类字段,改完 POST /api/config 存回。
 * 与网页 /setup 共用同一份 schema/config —— 配置永远同步、不分叉。
 *
 * 字段类型→控件:str/secret=EditText、int/float=数字 EditText、bool=Switch、enum=Spinner、
 *   str_list=多行、**module_list=原生增删改**(每项一张卡片渲染其 item_fields,可加/删/改;
 *   item 里的特殊类型 ha_entity/city/printer 退化成文本框,复杂选择器走底部「网页高级设置」)。
 * secret:不回显原值、留空=不改(留空时回传服务端给的掩码,_merge_for_save/_merge_list 据掩码保留原值)。
 *
 * 顶部额外一项「本机 / 服务器连接」=改这台设备连哪个服务器 + 令牌(存 Prefs,不进服务端 config),
 *   复用 v1 的 SetupActivity(扫码/mDNS/手填)。保存后**停留在当前二级页**,方便接着改。
 */
public class SettingsActivity extends Activity {

    private Prefs prefs;
    private String base, token;

    private JSONArray schemaArr;       // /api/schema 的各 section
    private JSONObject config;         // /api/config 的 config(脱敏,secret 为掩码)
    private JSONObject currentSection;  // 当前在看的二级页 section(返回/保存后判断)

    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private final Handler ui = new Handler(Looper.getMainLooper());

    private FrameLayout root;
    private boolean inDetail = false;  // 当前是否在二级页(决定返回键行为)
    private View cachedCategoryView;   // 缓存的分类列表(复用=返回时保留滚动位置)
    private boolean reloadOnResume = false;  // 仅去过子 Activity(本机连接/网页)回来才重拉,普通 resume 不动状态
    private TextView updateRowSub;     // 「检查更新」行的副标题(发现新版时标记)

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        prefs = new Prefs(this);
        base = prefs.baseUrl();
        token = prefs.token();

        root = new FrameLayout(this);
        root.setBackgroundColor(Color.WHITE);
        setContentView(root);

        if (base == null || base.isEmpty()) {     // 没配过(理论上进不来)→ 直接去配置页
            startActivity(new Intent(this, SetupActivity.class));
            finish();
            return;
        }
        showLoading();
        loadSchemaAndConfig(null);
    }

    // ---------- 数据加载 ----------
    /** 拉 schema + config;reopenSectionKey 非空=加载完重新打开该 section 二级页(否则回分类列表)。 */
    private void loadSchemaAndConfig(final String reopenSectionKey) {
        io.execute(() -> {
            try {
                String schemaResp = ApiClient.get(base, token, "/api/schema");
                String cfgResp = ApiClient.get(base, token, "/api/config");
                final JSONArray sa = new JSONArray(schemaResp);
                JSONObject c = new JSONObject(cfgResp).optJSONObject("config");
                final JSONObject cfg = (c == null) ? new JSONObject() : c;
                ui.post(() -> {
                    schemaArr = sa;
                    config = cfg;
                    cachedCategoryView = null;   // schema 重拉了,分类列表按新 schema 重建
                    JSONObject reopen = reopenSectionKey == null ? null : findSection(reopenSectionKey);
                    if (reopen != null) showSectionDetail(reopen);
                    else showCategoryList();
                });
            } catch (Exception e) {
                final String msg = errMsg(e);
                ui.post(() -> showError(msg));
            }
        });
    }

    private JSONObject findSection(String key) {
        for (int i = 0; schemaArr != null && i < schemaArr.length(); i++) {
            JSONObject s = schemaArr.optJSONObject(i);
            if (s != null && key.equals(s.optString("key"))) return s;
        }
        return null;
    }

    private String errMsg(Exception e) {
        if (e instanceof ApiClient.ApiException && ((ApiClient.ApiException) e).code == 403) {
            return getString(R.string.cfg_err_auth);
        }
        return getString(R.string.cfg_err_load) + "\n" + e.getMessage();
    }

    // ---------- 第一屏:分类列表 ----------
    /** 复用缓存的列表视图(同一个 ScrollView 实例)=从二级页返回时**滚动位置保留**,不弹回顶部。 */
    private void showCategoryList() {
        inDetail = false;
        currentSection = null;
        if (cachedCategoryView == null) cachedCategoryView = buildCategoryListView();
        root.removeAllViews();
        root.addView(cachedCategoryView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        silentUpdateCheck();   // 静默查一次,有新版标记「检查更新」行
    }

    private View buildCategoryListView() {
        LinearLayout col = screen(getString(R.string.cfg_title), false);

        // 本机连接(设备本地,不在服务端 schema)——改这台设备连哪个服务器 + 令牌
        col.addView(categoryRow(getString(R.string.cfg_local_conn),
                getString(R.string.cfg_local_conn_sub),
                v -> { reloadOnResume = true; startActivity(new Intent(this, SetupActivity.class)); }));

        // 检查更新(从 GitHub Release 拉最新版并安装);副标题在发现新版时标记
        View updateRow = categoryRow(getString(R.string.cfg_check_update),
                getString(R.string.cfg_check_update_sub),
                v -> checkForUpdate());
        updateRowSub = (TextView) ((LinearLayout) updateRow).getChildAt(1);   // 第2个子=副标题
        col.addView(updateRow);

        // 服务端各 section(全 schema 驱动)
        for (int i = 0; i < schemaArr.length(); i++) {
            JSONObject sec = schemaArr.optJSONObject(i);
            if (sec == null || !hasVisibleField(sec)) continue;   // 全隐藏字段的段不显示
            final JSONObject fsec = sec;
            col.addView(categoryRow(sec.optString("label", sec.optString("key")),
                    sec.optString("help", ""),
                    v -> showSectionDetail(fsec)));
        }
        return (View) col.getTag();
    }

    private boolean hasVisibleField(JSONObject sec) {
        JSONArray fields = sec.optJSONArray("fields");
        if (fields == null) return false;
        for (int i = 0; i < fields.length(); i++) {
            JSONObject f = fields.optJSONObject(i);
            if (f != null && !f.optBoolean("hidden", false)) return true;
        }
        return false;
    }

    // ---------- 二级页:某一类的字段 ----------
    private void showSectionDetail(JSONObject sec) {
        inDetail = true;
        currentSection = sec;
        String secKey = sec.optString("key");
        LinearLayout col = screen(sec.optString("label", secKey), true);

        String secHelp = sec.optString("help", "");
        if (!secHelp.isEmpty()) {
            TextView h = new TextView(this);
            h.setText(secHelp);
            h.setTextColor(Color.parseColor("#888888"));
            h.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
            h.setPadding(0, 0, 0, dp(6));
            col.addView(h);
        }

        JSONObject secCfg = config.optJSONObject(secKey);
        if (secCfg == null) { secCfg = new JSONObject(); try { config.put(secKey, secCfg); } catch (JSONException ignored) {} }
        final JSONObject fSecCfg = secCfg;

        boolean hasModuleList = false;
        final List<FieldEditor> editors = new ArrayList<>();
        JSONArray fields = sec.optJSONArray("fields");
        for (int i = 0; fields != null && i < fields.length(); i++) {
            JSONObject f = fields.optJSONObject(i);
            if (f == null || f.optBoolean("hidden", false)) continue;
            if ("module_list".equals(f.optString("type"))) {
                addLabel(col, f.optString("label", f.optString("key")), f.optString("help", ""));
                JSONArray items = fSecCfg.optJSONArray(f.optString("key"));
                editors.add(new ModuleListEditor(col, f, items == null ? new JSONArray() : items));
                hasModuleList = true;
            } else {
                editors.add(buildControl(col, f, fSecCfg));
            }
        }

        final Button save = new Button(this);
        save.setText(R.string.cfg_save);
        LinearLayout.LayoutParams slp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        slp.topMargin = dp(24);
        save.setLayoutParams(slp);
        save.setOnClickListener(v -> {
            for (FieldEditor ed : editors) ed.collectInto(fSecCfg);
            doSave(save);
        });
        col.addView(save);

        // 复杂列表/特殊选择器(城市搜索、浏览 HA 实体、发现设备、扫描打印机)仍走网页高级设置入口
        if (hasModuleList || hasSpecialField(sec)) {
            TextView web = new TextView(this);
            web.setText(getString(R.string.cfg_web_advanced));
            web.setTextColor(Color.parseColor("#2f6fed"));
            web.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
            LinearLayout.LayoutParams wlp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            wlp.topMargin = dp(20);
            web.setLayoutParams(wlp);
            web.setOnClickListener(v -> openWebSetup());
            col.addView(web);
        }
        render(col);
    }

    /** 段里是否含需要专用选择器的字段类型(本期原生退化成文本框,复杂选择走网页)。 */
    private boolean hasSpecialField(JSONObject sec) {
        JSONArray fields = sec.optJSONArray("fields");
        for (int i = 0; fields != null && i < fields.length(); i++) {
            JSONObject f = fields.optJSONObject(i);
            if (f != null && isSpecialType(f.optString("type"))) return true;
        }
        return false;
    }

    private static boolean isSpecialType(String t) {
        return "ha_entity".equals(t) || "city".equals(t) || "printer".equals(t);
    }

    // ---------- 通用控件构建(段字段 + module_list 子字段共用)----------
    /**
     * 把一个字段渲染成控件加进 container,返回值收集器(collectInto(target) 把当前值写进 target)。
     * @param src 当前值来源(段字段=secCfg;列表项子字段=该 item)——secret 留空时从这里取原值保留。
     */
    private FieldEditor buildControl(LinearLayout container, JSONObject f, JSONObject src) {
        String type = f.optString("type", "str");
        final String key = f.optString("key");
        boolean secretFlag = f.optBoolean("secret", false);

        addLabel(container, f.optString("label", key) + (f.optBoolean("required", false) ? " *" : ""),
                f.optString("help", ""));

        if ("bool".equals(type)) {
            Switch sw = new Switch(this);
            sw.setChecked(src.optBoolean(key, asBool(f.opt("default"))));
            container.addView(sw);
            return target -> { try { target.put(key, sw.isChecked()); } catch (JSONException ignored) {} };
        }

        if ("enum".equals(type)) {
            JSONArray opts = f.optJSONArray("options");
            final List<String> values = new ArrayList<>();
            List<String> labels = new ArrayList<>();
            String cur = src.optString(key, String.valueOf(f.opt("default")));
            int sel = 0;
            for (int i = 0; opts != null && i < opts.length(); i++) {
                JSONArray o = opts.optJSONArray(i);
                if (o == null || o.length() < 1) continue;
                String val = o.optString(0);
                values.add(val);
                labels.add(o.length() >= 2 ? o.optString(1) : val);
                if (val.equals(cur)) sel = values.size() - 1;
            }
            Spinner sp = new Spinner(this);
            ArrayAdapter<String> ad = new ArrayAdapter<>(this, android.R.layout.simple_spinner_item, labels);
            ad.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
            sp.setAdapter(ad);
            sp.setSelection(sel);
            container.addView(sp);
            return target -> {
                int p = sp.getSelectedItemPosition();
                if (p >= 0 && p < values.size()) {
                    try { target.put(key, values.get(p)); } catch (JSONException ignored) {}
                }
            };
        }

        if ("str_list".equals(type)) {
            EditText et = new EditText(this);
            et.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE);
            et.setMinLines(2);
            et.setGravity(Gravity.TOP | Gravity.START);
            StringBuilder sb = new StringBuilder();
            JSONArray arr = src.optJSONArray(key);
            for (int i = 0; arr != null && i < arr.length(); i++) {
                if (i > 0) sb.append("\n");
                sb.append(arr.optString(i));
            }
            et.setText(sb.toString());
            container.addView(et);
            return target -> {
                JSONArray out = new JSONArray();
                for (String line : et.getText().toString().split("\n")) {
                    String t = line.trim();
                    if (!t.isEmpty()) out.put(t);
                }
                try { target.put(key, out); } catch (JSONException ignored) {}
            };
        }

        // 默认:str / secret / int / float / 特殊类型(ha_entity/city/printer 退化为文本框)→ EditText
        final boolean secret = secretFlag;
        final String ftype = type;
        EditText et = new EditText(this);
        if (secret) {
            et.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
            et.setHint(R.string.cfg_secret_hint);     // 留空=不改;不回显原值
        } else if ("int".equals(type)) {
            et.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_SIGNED);
            et.setText(src.optString(key, String.valueOf(f.opt("default"))));
        } else if ("float".equals(type)) {
            et.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL | InputType.TYPE_NUMBER_FLAG_SIGNED);
            et.setText(src.optString(key, String.valueOf(f.opt("default"))));
        } else {
            et.setInputType(InputType.TYPE_CLASS_TEXT);
            et.setText(src.optString(key, f.optString("default", "")));
        }
        container.addView(et);
        return target -> {
            String v = et.getText().toString();
            if (secret) {
                if (v.trim().isEmpty()) {     // 留空=不改:保留原值(掩码/空),服务端据掩码保留原值
                    Object orig = src.opt(key);
                    if (orig != null) { try { target.put(key, orig); } catch (JSONException ignored) {} }
                    return;
                }
                try { target.put(key, v); } catch (JSONException ignored) {}
                return;
            }
            try {
                if ("int".equals(ftype)) {
                    if (v.trim().isEmpty()) return;
                    target.put(key, Long.parseLong(v.trim()));
                } else if ("float".equals(ftype)) {
                    if (v.trim().isEmpty()) return;
                    target.put(key, Double.parseDouble(v.trim()));
                } else {
                    target.put(key, v);
                }
            } catch (NumberFormatException nfe) {
                // 数字解析失败:保留原值不动(诚实降级,不写坏配置)
                Object orig = src.opt(key);
                if (orig != null) { try { target.put(key, orig); } catch (JSONException ignored) {} }
            } catch (JSONException ignored) {}
        };
    }

    /** module_list 原生编辑器:每项一张卡片渲染其 item_fields,可加/删/改。 */
    private class ModuleListEditor implements FieldEditor {
        private final JSONObject field;
        private final JSONArray itemFields;
        private final String key;
        private final LinearLayout rowsBox;
        private final TextView emptyHint;
        private final List<Row> rows = new ArrayList<>();

        ModuleListEditor(LinearLayout parent, JSONObject field, JSONArray currentItems) {
            this.field = field;
            this.key = field.optString("key");
            this.itemFields = field.optJSONArray("item_fields");

            rowsBox = new LinearLayout(SettingsActivity.this);
            rowsBox.setOrientation(LinearLayout.VERTICAL);
            parent.addView(rowsBox);

            emptyHint = new TextView(SettingsActivity.this);
            emptyHint.setText(R.string.cfg_list_empty);
            emptyHint.setTextColor(Color.parseColor("#aaaaaa"));
            emptyHint.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
            emptyHint.setPadding(0, dp(6), 0, dp(6));
            parent.addView(emptyHint);

            for (int i = 0; i < currentItems.length(); i++) addRow(currentItems.optJSONObject(i));

            Button add = new Button(SettingsActivity.this);
            add.setText(R.string.cfg_add_item);
            LinearLayout.LayoutParams alp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            alp.topMargin = dp(8);
            add.setLayoutParams(alp);
            add.setOnClickListener(v -> addRow(new JSONObject()));
            parent.addView(add);
            refreshEmptyHint();
        }

        private void addRow(JSONObject item) {
            Row r = new Row(item == null ? new JSONObject() : item);
            rows.add(r);
            rowsBox.addView(r.card);
            refreshEmptyHint();
        }

        private void refreshEmptyHint() {
            emptyHint.setVisibility(rows.isEmpty() ? View.VISIBLE : View.GONE);
        }

        @Override
        public void collectInto(JSONObject secCfg) {
            JSONArray arr = new JSONArray();
            for (Row r : rows) arr.put(r.collect());
            try { secCfg.put(key, arr); } catch (JSONException ignored) {}
        }

        /** 列表里的一项:卡片内联渲染所有 item_fields + 一个删除按钮。 */
        private class Row {
            final JSONObject orig;
            final LinearLayout card;
            final List<FieldEditor> subs = new ArrayList<>();

            Row(JSONObject item) {
                orig = item;
                card = new LinearLayout(SettingsActivity.this);
                card.setOrientation(LinearLayout.VERTICAL);
                card.setBackgroundColor(Color.parseColor("#F4F6F8"));
                card.setPadding(dp(12), dp(8), dp(12), dp(12));
                LinearLayout.LayoutParams clp = new LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
                clp.topMargin = dp(10);
                card.setLayoutParams(clp);

                for (int i = 0; itemFields != null && i < itemFields.length(); i++) {
                    JSONObject sf = itemFields.optJSONObject(i);
                    if (sf == null) continue;
                    final String sk = sf.optString("key");
                    if (sf.optBoolean("hidden", false)) {
                        // 隐藏子字段(如 HA 实体的 icon):不显示控件,但保留原值
                        final Object preserve = orig.has(sk) ? orig.opt(sk) : sf.opt("default");
                        subs.add(target -> { if (preserve != null) { try { target.put(sk, preserve); } catch (JSONException ignored) {} } });
                    } else {
                        subs.add(buildControl(card, sf, orig));
                    }
                }

                Button del = new Button(SettingsActivity.this);
                del.setText(R.string.cfg_del_item);
                del.setTextColor(Color.parseColor("#c0392b"));
                LinearLayout.LayoutParams dlp = new LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
                dlp.topMargin = dp(10);
                del.setLayoutParams(dlp);
                del.setOnClickListener(v -> { rows.remove(this); rowsBox.removeView(card); refreshEmptyHint(); });
                card.addView(del);
            }

            JSONObject collect() {
                JSONObject out = new JSONObject();
                for (FieldEditor e : subs) e.collectInto(out);
                return out;
            }
        }
    }

    // ---------- 保存(原地,不离开当前二级页)----------
    private void doSave(final Button saveBtn) {
        final String body;
        try {
            body = new JSONObject().put("config", config).toString();
        } catch (JSONException e) {
            Toast.makeText(this, R.string.cfg_save_fail, Toast.LENGTH_LONG).show();
            return;
        }
        saveBtn.setEnabled(false);
        saveBtn.setText(R.string.cfg_saving);
        io.execute(() -> {
            try {
                ApiClient.post(base, token, "/api/config", body);
                ui.post(() -> {
                    saveBtn.setEnabled(true);
                    saveBtn.setText(R.string.cfg_save);
                    Toast.makeText(this, R.string.cfg_saved, Toast.LENGTH_SHORT).show();
                    // 停留在当前二级页,滚动位置不变;用户可接着改下一项
                });
            } catch (Exception e) {
                final String m = e.getMessage();
                ui.post(() -> {
                    saveBtn.setEnabled(true);
                    saveBtn.setText(R.string.cfg_save);
                    Toast.makeText(this, getString(R.string.cfg_save_fail) + "\n" + m, Toast.LENGTH_LONG).show();
                });
            }
        });
    }

    private void openWebSetup() {
        String url = Prefs.normalize(base) + "/setup";
        if (token != null && !token.isEmpty()) url += "?token=" + Uri.encode(token);
        Intent it = new Intent(this, WebPageActivity.class);
        it.putExtra(WebPageActivity.EXTRA_URL, url);
        it.putExtra(WebPageActivity.EXTRA_TITLE, getString(R.string.cfg_edit_in_web));
        reloadOnResume = true;     // 网页里可能改了值,回来重拉同步
        startActivity(it);
    }

    // ---------- 在线更新(查 GitHub Release → 下载 → 拉起系统安装器)----------
    private boolean updateCheckedOnce = false;

    /** 进设置页时静默查一次:发现新版就把「检查更新」行标红提示(本次会话只查一次,省请求)。 */
    private void silentUpdateCheck() {
        if (updateCheckedOnce || updateRowSub == null) return;
        updateCheckedOnce = true;
        io.execute(() -> {
            try {
                int cur = getPackageManager().getPackageInfo(getPackageName(), 0).versionCode;
                UpdateChecker.UpdateInfo u = UpdateChecker.check(cur);
                if (u.hasUpdate) {
                    ui.post(() -> {
                        if (updateRowSub != null) {
                            updateRowSub.setText(getString(R.string.cfg_update_found) + " "
                                    + u.versionName + " · " + getString(R.string.cfg_update_tap));
                            updateRowSub.setTextColor(Color.parseColor("#E53935"));
                        }
                    });
                }
            } catch (Exception ignored) {
                // 静默忽略,不打扰
            }
        });
    }

    private void checkForUpdate() {
        Toast.makeText(this, R.string.cfg_update_checking, Toast.LENGTH_SHORT).show();
        io.execute(() -> {
            try {
                int cur = getPackageManager().getPackageInfo(getPackageName(), 0).versionCode;
                UpdateChecker.UpdateInfo u = UpdateChecker.check(cur);
                ui.post(() -> {
                    if (u.apkUrl.isEmpty()) {
                        Toast.makeText(this, R.string.cfg_update_no_apk, Toast.LENGTH_LONG).show();
                    } else if (!u.hasUpdate) {
                        Toast.makeText(this, R.string.cfg_update_latest, Toast.LENGTH_LONG).show();
                    } else {
                        showUpdateDialog(u);
                    }
                });
            } catch (Exception e) {
                final String m = e.getMessage();
                ui.post(() -> Toast.makeText(this,
                        getString(R.string.cfg_update_check_fail) + "\n" + m, Toast.LENGTH_LONG).show());
            }
        });
    }

    private void showUpdateDialog(UpdateChecker.UpdateInfo u) {
        String notes = (u.notes == null || u.notes.trim().isEmpty())
                ? getString(R.string.cfg_update_no_notes) : u.notes.trim();
        new AlertDialog.Builder(this)
                .setTitle(getString(R.string.cfg_update_found) + " " + u.versionName)
                .setMessage(notes)
                .setPositiveButton(R.string.cfg_update_download, (d, w) -> startDownload(u))
                .setNegativeButton(android.R.string.cancel, null)
                .show();
    }

    private void startDownload(UpdateChecker.UpdateInfo u) {
        if (!ensureInstallPermission()) return;     // API26+ 先确保有"未知来源"安装权限
        final ProgressDialog pd = new ProgressDialog(this);
        pd.setProgressStyle(ProgressDialog.STYLE_HORIZONTAL);
        pd.setMessage(getString(R.string.cfg_update_downloading));
        pd.setCancelable(false);
        pd.setMax(100);
        pd.show();
        io.execute(() -> {
            try {
                File apk = UpdateChecker.download(this, u.apkUrl, u.apkName,
                        pct -> ui.post(() -> pd.setProgress(pct)));
                ui.post(() -> { dismiss(pd); installApk(apk); });
            } catch (Exception e) {
                final String m = e.getMessage();
                ui.post(() -> {
                    dismiss(pd);
                    Toast.makeText(this, getString(R.string.cfg_update_download_fail) + "\n" + m,
                            Toast.LENGTH_LONG).show();
                });
            }
        });
    }

    /** API26+ 需用户先授权"允许安装未知应用";没授权就引导去设置,返回 false(本次不继续)。 */
    private boolean ensureInstallPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                && !getPackageManager().canRequestPackageInstalls()) {
            new AlertDialog.Builder(this)
                    .setTitle(R.string.cfg_update_perm_title)
                    .setMessage(R.string.cfg_update_perm_msg)
                    .setPositiveButton(R.string.cfg_update_perm_go, (d, w) -> {
                        try {
                            startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                                    Uri.parse("package:" + getPackageName())));
                        } catch (Exception ignored) {}
                    })
                    .setNegativeButton(android.R.string.cancel, null)
                    .show();
            return false;
        }
        return true;
    }

    private void installApk(File apk) {
        try {
            Uri uri;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                uri = FileProvider.getUriForFile(this, getPackageName() + ".fileprovider", apk);
            } else {
                uri = Uri.fromFile(apk);
            }
            Intent i = new Intent(Intent.ACTION_VIEW);
            i.setDataAndType(uri, "application/vnd.android.package-archive");
            i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(i);
        } catch (Exception e) {
            Toast.makeText(this, getString(R.string.cfg_update_install_fail) + "\n" + e.getMessage(),
                    Toast.LENGTH_LONG).show();
        }
    }

    private void dismiss(ProgressDialog pd) {
        try { if (pd != null && pd.isShowing()) pd.dismiss(); } catch (Exception ignored) {}
    }

    @Override
    protected void onResume() {
        super.onResume();
        // 只有去过子 Activity(本机连接 / 网页高级设置)回来才重拉同步;普通 resume(焦点变化)不动状态,
        // 这样纯「列表↔二级页」导航靠缓存视图保留滚动位置,不会因 resume 把页面重置回顶部。
        if (prefs != null) { base = prefs.baseUrl(); token = prefs.token(); }
        if (reloadOnResume && schemaArr != null) {
            reloadOnResume = false;
            String reopen = (inDetail && currentSection != null) ? currentSection.optString("key") : null;
            showLoading();
            loadSchemaAndConfig(reopen);
        }
    }

    @Override
    public void onBackPressed() {
        if (inDetail && schemaArr != null) {
            showCategoryList();    // 二级页 → 回分类列表
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onDestroy() {
        io.shutdownNow();
        super.onDestroy();
    }

    // ---------- UI 脚手架(全程序化,不依赖布局 XML)----------
    /** 建一个带顶栏(标题 + 可选返回)的滚动内容容器,调用方往返回的 LinearLayout 加控件。 */
    private LinearLayout screen(String title, boolean showBack) {
        LinearLayout outer = new LinearLayout(this);
        outer.setOrientation(LinearLayout.VERTICAL);
        outer.setBackgroundColor(Color.WHITE);

        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setBackgroundColor(Color.parseColor("#2f6fed"));
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setPadding(dp(12), dp(12), dp(16), dp(12));
        if (showBack) {
            TextView back = new TextView(this);
            back.setText("‹ " + getString(R.string.cfg_back));
            back.setTextColor(Color.WHITE);
            back.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
            back.setPadding(0, 0, dp(16), 0);
            back.setOnClickListener(v -> onBackPressed());
            bar.addView(back);
        }
        TextView tv = new TextView(this);
        tv.setText(title);
        tv.setTextColor(Color.WHITE);
        tv.setTextSize(TypedValue.COMPLEX_UNIT_SP, 18);
        bar.addView(tv);
        outer.addView(bar, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        ScrollView sv = new ScrollView(this);
        sv.setFillViewport(true);
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setPadding(dp(20), dp(16), dp(20), dp(32));
        sv.addView(col, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        outer.addView(sv, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        col.setTag(outer);   // render() 取出外层贴到 root
        return col;
    }

    private void render(LinearLayout col) {
        View outer = (View) col.getTag();
        root.removeAllViews();
        root.addView(outer != null ? outer : col, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
    }

    /** 分类列表的一行:大标题 + 小副标题,整行可点。 */
    private View categoryRow(String title, String sub, View.OnClickListener onClick) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.VERTICAL);
        row.setPadding(dp(8), dp(16), dp(8), dp(16));
        row.setClickable(true);
        row.setOnClickListener(onClick);
        row.setLayoutParams(new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        TextView t = new TextView(this);
        t.setText(title);
        t.setTextColor(Color.parseColor("#111111"));
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, 17);
        row.addView(t);
        if (sub != null && !sub.isEmpty()) {
            TextView s = new TextView(this);
            s.setText(sub);
            s.setTextColor(Color.parseColor("#888888"));
            s.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
            s.setPadding(0, dp(3), 0, 0);
            row.addView(s);
        }
        View div = new View(this);
        div.setBackgroundColor(Color.parseColor("#EEEEEE"));
        LinearLayout.LayoutParams dlp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(1));
        dlp.topMargin = dp(16);
        div.setLayoutParams(dlp);
        row.addView(div);
        return row;
    }

    private void addLabel(LinearLayout col, String label, String help) {
        TextView t = new TextView(this);
        t.setText(label);
        t.setTextColor(Color.parseColor("#333333"));
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = dp(16);
        t.setLayoutParams(lp);
        col.addView(t);
        if (help != null && !help.isEmpty()) {
            TextView h = new TextView(this);
            h.setText(help);
            h.setTextColor(Color.parseColor("#999999"));
            h.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
            h.setPadding(0, dp(2), 0, dp(4));
            col.addView(h);
        }
    }

    private void showLoading() {
        root.removeAllViews();
        ProgressBar pb = new ProgressBar(this);
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.gravity = Gravity.CENTER;
        root.addView(pb, lp);
    }

    private void showError(String msg) {
        root.removeAllViews();
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setGravity(Gravity.CENTER);
        col.setPadding(dp(32), dp(32), dp(32), dp(32));
        TextView t = new TextView(this);
        t.setText(msg);
        t.setGravity(Gravity.CENTER);
        t.setTextColor(Color.parseColor("#444444"));
        col.addView(t);
        Button retry = new Button(this);
        retry.setText(R.string.retry_now);
        retry.setOnClickListener(v -> { showLoading(); loadSchemaAndConfig(null); });
        col.addView(retry);
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT);
        root.addView(col, lp);
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    private static boolean asBool(Object o) {
        if (o instanceof Boolean) return (Boolean) o;
        return o != null && "true".equalsIgnoreCase(String.valueOf(o));
    }

    /** 一个字段的值收集器:把控件当前值写进给定 JSON(段=secCfg;列表项=新建 item)。 */
    private interface FieldEditor {
        void collectInto(JSONObject target);
    }
}
