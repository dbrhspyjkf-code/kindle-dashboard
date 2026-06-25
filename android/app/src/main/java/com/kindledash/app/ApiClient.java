package com.kindledash.app;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * 极简 HTTP 客户端:只为原生设置页拉/存配置用(GET /api/schema、GET /api/config、POST /api/config)。
 * 不引第三方库(用 java.net.HttpURLConnection,minSdk 21 自带)。**必须在工作线程调用**(同步阻塞)。
 *
 * 鉴权:令牌经 header `X-Access-Token` 传(服务端 _auth 接受 query/header/cookie 三处之一)。
 * 用 header 而非 URL query —— 令牌不进 URL、不落日志(红线:令牌不进日志)。
 */
final class ApiClient {

    private static final int CONNECT_TIMEOUT = 8000;
    private static final int READ_TIMEOUT = 12000;

    private ApiClient() {}

    /** 请求失败(HTTP >=400)时抛出,带状态码与响应体,供上层提示。 */
    static class ApiException extends IOException {
        final int code;
        ApiException(int code, String msg) {
            super("HTTP " + code + (msg != null && !msg.isEmpty() ? ": " + msg : ""));
            this.code = code;
        }
    }

    static String get(String base, String token, String path) throws IOException {
        return request(base, token, path, "GET", null);
    }

    static String post(String base, String token, String path, String jsonBody) throws IOException {
        return request(base, token, path, "POST", jsonBody);
    }

    private static String request(String base, String token, String path,
                                  String method, String jsonBody) throws IOException {
        HttpURLConnection c = null;
        try {
            URL u = new URL(Prefs.normalize(base) + path);
            c = (HttpURLConnection) u.openConnection();
            c.setConnectTimeout(CONNECT_TIMEOUT);
            c.setReadTimeout(READ_TIMEOUT);
            c.setRequestMethod(method);
            c.setRequestProperty("Accept", "application/json");
            if (token != null && !token.isEmpty()) {
                c.setRequestProperty("X-Access-Token", token);   // 令牌走 header,不进 URL
            }
            if (jsonBody != null) {
                c.setDoOutput(true);
                c.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                byte[] body = jsonBody.getBytes("UTF-8");
                try (OutputStream os = c.getOutputStream()) {
                    os.write(body);
                }
            }
            int code = c.getResponseCode();
            InputStream is = (code >= 400) ? c.getErrorStream() : c.getInputStream();
            String resp = readAll(is);
            if (code >= 400) {
                throw new ApiException(code, resp);
            }
            return resp;
        } finally {
            if (c != null) c.disconnect();
        }
    }

    private static String readAll(InputStream is) throws IOException {
        if (is == null) return "";
        try (InputStream in = is) {
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            byte[] buf = new byte[4096];
            int n;
            while ((n = in.read(buf)) != -1) bos.write(buf, 0, n);
            return new String(bos.toByteArray(), "UTF-8");
        }
    }
}
