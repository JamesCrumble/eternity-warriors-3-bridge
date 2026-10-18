package com.jamescrumble.ew3;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.text.Editable;
import android.text.InputType;
import android.text.TextWatcher;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.SeekBar;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Game settings. They are kept in settings.txt (KEY=VALUE per line) next to the game log; GameProcess
 * applies them when it builds the game's command line and environment (see GameProcess.applySettings),
 * after engine_env.txt, so a menu value wins over a hand-edited one.
 * This is the app's launcher screen: "Играть" saves and starts the game (the game process is restarted
 * so that it always begins with the values shown here).
 */
public final class SettingsActivity extends Activity {
    private static final int BG = Color.rgb(18, 22, 26), FG = Color.rgb(230, 235, 238), DIM = Color.rgb(140, 150, 156),
            ACCENT = Color.rgb(128, 203, 196);

    private final Map<String, String> values = new LinkedHashMap<>();
    private float dp;
    private TextView folderInfo, serverInfo, notifyInfo;
    private EditText serverAddr;
    private boolean hadAccess, asked;

    /** The existing settings file (main folder first, then the other), or where it would be written. */
    static File file(Context c) {
        return Storage.find(c, "settings.txt");
    }

    static Map<String, String> load(Context c) {
        Map<String, String> m = new LinkedHashMap<>();
        File f = file(c);
        if (!f.isFile()) return m;
        try (FileInputStream in = new FileInputStream(f)) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] b = new byte[2048];
            int n;
            while ((n = in.read(b)) > 0) out.write(b, 0, n);
            for (String line : out.toString("UTF-8").split("\n")) {
                int eq = line.indexOf('=');
                if (eq > 0) m.put(line.substring(0, eq).trim(), line.substring(eq + 1).trim());
            }
        } catch (IOException ignored) { }
        return m;
    }

    /** A dotted IPv4 address (the port takes nothing else in EW3_SERVER). */
    static boolean validIpv4(String a) {
        if (a == null || !a.matches("\\d{1,3}(\\.\\d{1,3}){3}")) return false;
        for (String part : a.split("\\.")) if (Integer.parseInt(part) > 255) return false;
        return true;
    }

    /** The address field can be edited only while "connect to another server" is on. */
    private void applyCustomState() {
        if (serverAddr == null) return;
        boolean on = "1".equals(values.get("SERVER_CUSTOM"));
        serverAddr.setEnabled(on);
        serverAddr.setAlpha(on ? 1f : 0.4f);
    }

    private boolean save() {
        if ("1".equals(values.get("SERVER_CUSTOM")) && !validIpv4(values.get("SERVER_ADDR"))) {
            Toast.makeText(this, "Введите IPv4-адрес сервера, например 192.168.1.20", Toast.LENGTH_LONG).show();
            return false;
        }
        StringBuilder sb = new StringBuilder();
        for (Map.Entry<String, String> e : values.entrySet()) sb.append(e.getKey()).append('=').append(e.getValue()).append('\n');
        try (FileOutputStream out = new FileOutputStream(new File(Storage.mainDir(this), "settings.txt"))) {
            out.write(sb.toString().getBytes("UTF-8"));
            return true;
        } catch (IOException e) {
            Toast.makeText(this, "Не удалось сохранить: " + e.getMessage(), Toast.LENGTH_LONG).show();
            return false;
        }
    }

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        dp = getResources().getDisplayMetrics().density;
        values.putAll(load(this));

        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setPadding(px(20), px(16), px(20), px(24));

        col.addView(text("Eternity Warriors 3 — настройки", 22, FG, true));
        col.addView(text("Настрой и нажми «Играть» — игра стартует с этими значениями.", 13, DIM, false));
        folderInfo = text("", 12, DIM, false);
        folderInfo.setPadding(0, px(6), 0, 0);
        col.addView(folderInfo);

        col.addView(section("Картинка"));
        col.addView(choice("Разрешение рендера (высота)", "RENDER_HEIGHT", new int[] { 480, 540, 720 }, null, 720, "p",
                "Ширина считается по пропорциям экрана. Ниже — быстрее и крупнее интерфейс. Файл resolution.txt рядом с логом важнее этого значения."));

        col.addView(choice("Лимит кадров", "FPS_LIMIT", new int[] { 30, 60, 90, 120 }, null, 120, " fps",
                "Целевая частота игры и экрана. Игра упирается в процессор телефона (движок идёт в эмуляции): в лёгких сценах 90-110 fps, в тяжёлых и в меню инвентаря около 60-70. Если экран не успевает за лимитом, он пропускает кадры (например 90 -> 45), тогда выбери 60."));

        col.addView(toggle("Счётчик FPS", "FPS_COUNTER", true, "Маленькая зелёная цифра вверху по центру экрана."));

        col.addView(section("Звук"));
        col.addView(choice("Буфер звука", "AUDIO_LATENCY_MS", new int[] { 0, 200, 400 },
                new String[] { "минимум", "200 мс", "400 мс" }, 0, "",
                "Минимум (на OnePlus 13s это 120 мс) — звук ближе всего к картинке. Если потрескивает при просадках FPS — увеличь."));

        col.addView(section("Сервер"));
        col.addView(toggle("Доступ из локальной сети", "SERVER_LAN", false,
                "Выкл: сервер слушает только этот телефон (127.0.0.1): /docs (Swagger) открывается в браузере на телефоне, "
                        + "пока игра свёрнута. Вкл: сервер слушает 0.0.0.0 и виден в домашней сети, с компьютера можно открыть /docs "
                        + "и менять сохранения; вход по логину admin и паролю ниже. Работа в фоне держится уведомлением; "
                        + "в этом режиме телефон не засыпает, пока игра запущена. Применяется при следующем запуске игры."));
        notifyInfo = text("Уведомления выключены: Android может остановить сервер, когда игра свёрнута, и не покажет, что он "
                + "работает. Нажмите здесь, чтобы разрешить уведомления.", 13, Color.rgb(255, 183, 77), false);
        notifyInfo.setPadding(0, px(8), 0, px(2));
        notifyInfo.setOnClickListener(v -> {
            Intent i = new Intent(android.provider.Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                    .putExtra(android.provider.Settings.EXTRA_APP_PACKAGE, getPackageName());
            startActivity(i);
        });
        col.addView(notifyInfo);
        serverInfo = text("", 13, FG, false);
        serverInfo.setTextIsSelectable(true);
        serverInfo.setPadding(0, px(6), 0, 0);
        col.addView(serverInfo);
        col.addView(toggle("Подключаться к другому серверу", "SERVER_CUSTOM", false,
                "Выкл: игра работает со встроенным сервером. Вкл: игра подключается к серверу по адресу ниже (например, "
                        + "ew3server.py на компьютере: python server/ew3server.py --host 0.0.0.0), встроенный сервер тогда не запускается. "
                        + "Нужен IPv4-адрес; порты те же: 18080 (HTTP) и 18024 (Gluon)."));
        serverAddr = new EditText(this);
        serverAddr.setHint("192.168.1.20");
        serverAddr.setText(values.containsKey("SERVER_ADDR") ? values.get("SERVER_ADDR") : "");
        serverAddr.setTextColor(FG);
        serverAddr.setHintTextColor(DIM);
        serverAddr.setSingleLine();
        serverAddr.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL);
        serverAddr.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence c, int a, int b, int d) { }
            @Override public void onTextChanged(CharSequence c, int a, int b, int d) { }
            @Override public void afterTextChanged(Editable e) {
                values.put("SERVER_ADDR", e.toString().trim());
                showServer();
            }
        });
        col.addView(serverAddr, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        applyCustomState();

        col.addView(section("Производительность"));
        col.addView(toggle("Только быстрые ядра (6-7)", "CPU_PRIME", false,
                "Держит игру на двух самых быстрых ядрах: главный поток и поток воркера оба работают на них, система не переносит их на медленные. Давало заметный прирост FPS. Файл cpu_mask.txt рядом с логом важнее."));
        col.addView(toggle("Подсказки производительности системе (ADPF)", "PERF_HINT", true,
                "Сообщает Android время кадра, чтобы он держал частоту ядер выше. На некоторых телефонах давало обратный эффект — если FPS хуже, выключи."));
        col.addView(choice("Кадров «в полёте»", "EW3_GL_INFLIGHT", new int[] { 1, 2, 3 }, null, 2, "",
                "Сколько кадров игра готовит вперёд, пока телефон рисует предыдущий. 2 — плавнее, 1 — меньше задержка."));

        col.addView(section("Отладка"));
        col.addView(toggle("Профилирование в логе", "PROFILING", false,
                "Раз в 10 секунд пишет в лог, где игра тратит время. Только для отладки: может подвесить игру (чёрный экран, 0 FPS)."));
        col.addView(toggle("Подробный лог порта (TRACE)", "TRACE", true,
                "Строки TRACE: ввод, загрузка файлов, вызовы движка. Отчёт о падении пишется в лог в любом случае."));

        ScrollView sv = new ScrollView(this);
        sv.addView(col, new ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        // The buttons stay at the bottom whatever the scroll position.
        Button reset = button("Вернуть как было");
        reset.setOnClickListener(v -> {
            values.clear();
            Storage.deleteEverywhere(this, "settings.txt");
            recreate();
        });
        Button saveOnly = button("Сохранить");
        saveOnly.setOnClickListener(v -> {
            if (save()) Toast.makeText(this, "Сохранено", Toast.LENGTH_SHORT).show();
        });
        Button play = button("Играть");
        play.setOnClickListener(v -> { if (save()) restartGame(); });
        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setPadding(px(16), px(4), px(16), px(8));
        for (Button bt : new Button[] { reset, saveOnly, play }) {
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
            lp.setMargins(px(4), 0, px(4), 0);
            bar.addView(bt, lp);
        }
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(BG);
        root.addView(sv, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        root.addView(bar, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        setContentView(root);
        hadAccess = Storage.hasAccess(this);
        showFolder();
        showServer();
        askNotifications();
        if (!hadAccess) askAccess();
        else moveFiles();
    }

    @Override protected void onResume() {
        super.onResume();
        // Back from the system page: if the access has just been given, take the files over.
        boolean now = Storage.hasAccess(this);
        if (now && !hadAccess) moveFiles();
        hadAccess = now;
        showFolder();
        showServer();
    }

    /** Where /docs can be opened and with which login; the password is made by the server on its first LAN start. */
    private void showServer() {
        if (serverInfo == null) return;
        if (notifyInfo != null) notifyInfo.setVisibility(ServerService.notificationsAllowed(this) ? View.GONE : View.VISIBLE);
        StringBuilder sb = new StringBuilder();
        if ("1".equals(values.get("SERVER_CUSTOM"))) {
            String a = values.get("SERVER_ADDR");
            sb.append(validIpv4(a) ? "Игра подключится к серверу http://" + a + ":" + ServerService.PORT + "/docs (встроенный не запускается)"
                    : "Введите IPv4-адрес сервера");
            serverInfo.setText(sb.toString());
            return;
        }
        sb.append("На этом телефоне: http://127.0.0.1:" + ServerService.PORT + "/docs");
        if ("1".equals(values.get("SERVER_LAN"))) {
            java.util.List<String> ips = ServerService.addresses();
            if (ips.isEmpty()) sb.append("\nЛокальная сеть: подключитесь к Wi-Fi (адрес появится здесь)");
            for (String ip : ips) sb.append("\nС компьютера: http://").append(ip).append(':').append(ServerService.PORT).append("/docs");
            String pw = "";
            try (FileInputStream in = new FileInputStream(new File(getFilesDir(), "serverdata/admin_password.txt"))) {
                ByteArrayOutputStream out = new ByteArrayOutputStream();
                byte[] b = new byte[256];
                int n;
                while ((n = in.read(b)) > 0) out.write(b, 0, n);
                pw = out.toString("UTF-8").trim();
            } catch (IOException ignored) { }
            sb.append("\nЛогин: admin   Пароль: ").append(pw.isEmpty() ? "появится после первого запуска игры с этой настройкой" : pw);
        }
        serverInfo.setText(sb.toString());
    }

    /** Android 13+: the notification that says the server is running needs this permission. */
    private void askNotifications() {
        ServerService.askNotifications(this);
    }

    @Override public void onRequestPermissionsResult(int code, String[] perms, int[] results) {
        if (Storage.hasAccess(this)) { hadAccess = true; moveFiles(); }
        showFolder();
        showServer();
    }

    private void showFolder() {
        if (folderInfo == null) return;
        File main = Storage.mainDir(this);
        folderInfo.setText("Папка игры: " + main.getPath() + (Storage.hasAccess(this) ? ""
                : "\n(нет доступа ко всем файлам — используется папка приложения в Android/data)"));
    }

    /** Asks once per launch of this screen for access to all files; the game works without it. */
    private void askAccess() {
        if (asked) return;
        asked = true;
        new AlertDialog.Builder(this)
                .setTitle("Доступ ко всем файлам")
                .setMessage("Чтобы хранить APK игры, кэш и сохранения в удобной папке\n"
                        + Storage.shared(this).getPath() + "\nприложению нужен доступ ко всем файлам. Файлы из Android/data "
                        + "будут перенесены туда сами. Без доступа игра работает с папкой в Android/data.")
                .setPositiveButton("Разрешить", (d, w) -> Storage.requestAccess(this, 2))
                .setNegativeButton("Позже", null)
                .show();
    }

    /** Creates BridgeGames/<package> and moves the files of Android/data into it (off the UI thread: it may copy). */
    private void moveFiles() {
        new Thread(() -> {
            int n = Storage.migrate(getApplicationContext(), t -> runOnUiThread(() -> folderInfo.setText(t)));
            runOnUiThread(() -> {
                showFolder();
                if (n > 0) Toast.makeText(this, "Файлов перенесено в BridgeGames: " + n, Toast.LENGTH_LONG).show();
            });
        }, "bridge-storage").start();
    }

    /**
     * Starts the game with the saved values. CLEAR_TASK destroys a MainActivity that is still alive, so its
     * GameProcess (which reads settings.txt when it is created) is rebuilt from scratch.
     */
    private void restartGame() {
        startActivity(new Intent(this, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK));
        finish();
    }

    // ------------------------------------------------------------ widgets

    private int px(int v) { return Math.round(v * dp); }

    private TextView text(String s, int sp, int color, boolean bold) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextColor(color);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        if (bold) t.setTypeface(t.getTypeface(), android.graphics.Typeface.BOLD);
        return t;
    }

    private View spacer(int h) {
        View v = new View(this);
        v.setLayoutParams(new LinearLayout.LayoutParams(1, px(h)));
        return v;
    }

    private View section(String title) {
        LinearLayout l = new LinearLayout(this);
        l.setOrientation(LinearLayout.VERTICAL);
        l.setPadding(0, px(22), 0, px(4));
        l.addView(text(title.toUpperCase(), 12, ACCENT, true));
        return l;
    }

    private Button button(String label) {
        Button b = new Button(this);
        b.setText(label);
        b.setAllCaps(false);
        return b;
    }

    private int intOf(String key, int def) {
        try { return Integer.parseInt(values.getOrDefault(key, String.valueOf(def))); } catch (NumberFormatException e) { return def; }
    }

    private View slider(String title, String key, int min, int max, int step, int def, String unit, String hint) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.VERTICAL);
        row.setPadding(0, px(10), 0, px(4));
        TextView head = text("", 16, FG, false);
        SeekBar bar = new SeekBar(this);
        bar.setMax((max - min) / step);
        int cur = Math.max(min, Math.min(max, intOf(key, def)));
        bar.setProgress((cur - min) / step);
        Runnable show = () -> head.setText(title + ": " + (min + bar.getProgress() * step) + unit);
        show.run();
        bar.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override public void onProgressChanged(SeekBar s, int p, boolean user) {
                show.run();
                values.put(key, String.valueOf(min + p * step));
            }
            @Override public void onStartTrackingTouch(SeekBar s) { }
            @Override public void onStopTrackingTouch(SeekBar s) { }
        });
        row.addView(head);
        row.addView(bar);
        row.addView(text(hint, 12, DIM, false));
        return row;
    }

    private View choice(String title, String key, int[] options, String[] labels, int def, String unit, String hint) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.VERTICAL);
        row.setPadding(0, px(10), 0, px(4));
        row.addView(text(title, 16, FG, false));
        LinearLayout line = new LinearLayout(this);
        line.setOrientation(LinearLayout.HORIZONTAL);
        line.setGravity(Gravity.START);
        int cur = intOf(key, def);
        Button[] bs = new Button[options.length];
        for (int i = 0; i < options.length; i++) {
            final int o = options[i];
            Button b = new Button(this);
            b.setAllCaps(false);
            b.setText(labels != null ? labels[i] : o + unit);
            b.setMinWidth(0);
            b.setMinimumWidth(0);
            bs[i] = b;
            b.setOnClickListener(v -> {
                values.put(key, String.valueOf(o));
                for (int j = 0; j < bs.length; j++) bs[j].setAlpha(options[j] == o ? 1f : 0.45f);
            });
            b.setAlpha(o == cur ? 1f : 0.45f);
            line.addView(b, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        }
        row.addView(line);
        row.addView(text(hint, 12, DIM, false));
        return row;
    }

    private View toggle(String title, String key, boolean def, String hint) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.VERTICAL);
        row.setPadding(0, px(10), 0, px(4));
        Switch sw = new Switch(this);
        sw.setText(title);
        sw.setTextColor(FG);
        sw.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        sw.setChecked(intOf(key, def ? 1 : 0) != 0);
        sw.setOnCheckedChangeListener((b, on) -> {
            values.put(key, on ? "1" : "0");
            if (key.equals("SERVER_LAN")) {
                showServer();
                if (on) askNotifications();
            }
            if (key.equals("SERVER_CUSTOM")) {
                applyCustomState();
                showServer();
            }
        });
        row.addView(sw);
        row.addView(text(hint, 12, DIM, false));
        return row;
    }
}
