package com.jamescrumble.ew3;

import android.content.Context;
import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioTrack;
import android.os.SystemClock;
import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructPollfd;

import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileDescriptor;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InterruptedIOException;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedList;
import java.util.List;
import java.util.ListIterator;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import java.util.zip.ZipInputStream;

/**
 * Owns everything outside the UI: unpacking the sysroot, linking the player's
 * game files, running qemu-arm and talking to the port through the control
 * directory (commands in, frame.bin and status.json out, audio over a FIFO).
 */
final class GameProcess {
    interface Listener {
        void onStatus(String text);
        void onExit(int code);
    }

    private static final String NATIVE_DIR = "lib/armeabi-v7a";
    private static final String[] NATIVE_LIBS = {"libmain.so", "libmono.so", "libunity.so"};
    private static final String OBB_DIR = "Android/obb/com.glu.ewarriors3";
    // The game's FMOD mixer runs at 24 kHz (its project audio setting); see the "[audio] fmod:" log line.
    private static final int SAMPLE_RATE = 24000;

    private static final class Cmd {
        String line;
        final String key;
        Cmd(String line, String key) { this.line = line; this.key = key; }
    }

    private final Context ctx;
    private volatile Listener listener;
    private final boolean touchMode;
    private final File root;
    private final File control;
    private final File commandsFile;
    private final File statusFile;
    private final File fifo;
    private volatile File logFile;
    private final LinkedList<Cmd> queue = new LinkedList<>();
    private volatile boolean running;
    private volatile boolean muted = true;
    private Process process;
    private final GlBridge gl;
    private final PerfHint perf;
    private int renderW = 1280, renderH = 590;

    GameProcess(Context ctx, Listener listener) {
        this.ctx = ctx;
        this.listener = listener;
        root = ctx.getFilesDir();
        control = new File(root, "ctl");
        commandsFile = new File(control, "commands");
        statusFile = new File(control, "status.json");
        fifo = new File(root, "audio.pcm");
        logFile = new File(Storage.mainDir(ctx), "ew3.log");
        // pad_overlay.flag next to the log brings back the wrapper's own gamepad-style overlay.
        touchMode = !new File(logFile.getParentFile(), "pad_overlay.flag").exists();
        perf = new PerfHint(ctx, msg -> appendLog("[perf] " + msg));
        gl = new GlBridge(new File(root, "gl_cmd.pipe").getPath(), new File(root, "gl_reply.pipe").getPath(),
                msg -> appendLog("[gl] " + msg), perf::frame, perf::cpuLine);
        chooseRenderSize();
    }

    /**
     * The engine renders at whatever size it is told, so use the phone's own aspect ratio and let the
     * compositor scale the surface to the panel. resolution.txt ("1280x590") next to the log overrides it.
     */
    private void chooseRenderSize() {
        android.util.DisplayMetrics m = ctx.getResources().getDisplayMetrics();
        int longSide = Math.max(m.widthPixels, m.heightPixels), shortSide = Math.min(m.widthPixels, m.heightPixels);
        int h = 720;
        try { h = Integer.parseInt(SettingsActivity.load(ctx).getOrDefault("RENDER_HEIGHT", "720")); } catch (NumberFormatException ignored) { }
        h = Math.max(240, Math.min(h, 2160)) & ~1;
        int w = Math.round(h * (float) longSide / shortSide) & ~1;
        String over = readText(Storage.find(ctx, "resolution.txt")).trim();
        java.util.regex.Matcher mt = java.util.regex.Pattern.compile("(\\d+)x(\\d+)").matcher(over);
        if (mt.matches()) {
            w = Integer.parseInt(mt.group(1));
            h = Integer.parseInt(mt.group(2));
        }
        renderW = Math.max(320, Math.min(w, 4096));
        renderH = Math.max(240, Math.min(h, 4096));
    }

    int renderWidth() { return renderW; }
    int renderHeight() { return renderH; }
    GlBridge gl() { return gl; }
    File logFile() { return logFile; }
    boolean isRunning() { return running; }
    boolean touchMode() { return touchMode; }
    void setListener(Listener l) { listener = l; }
    void setMuted(boolean m) { muted = m; }

    void start() throws Exception {
        stopStale();
        // With all-files access everything of Android/data/<package>/files moves to BridgeGames/<package>, which
        // then becomes the main folder; the log and the settings are looked up there from here on.
        int moved = Storage.migrate(ctx, listener::onStatus);
        logFile = new File(Storage.mainDir(ctx), logFile.getName());
        if (moved > 0) appendLog("[wrapper] moved " + moved + " files to " + Storage.mainDir(ctx));
        prepare();
        launch();
    }

    /** Returns {frame, menu}, or null before the port has written a status. */
    int[] readStatus() {
        String s = readText(statusFile);
        if (s.isEmpty()) return null;
        return new int[] { intField(s, "\"frame\":"), intField(s, "\"menu\":") };
    }

    /**
     * Queues one command line. Commands with a key (cursor, stick) replace an
     * older queued command of the same key, because the port consumes only one
     * line per frame and stale positions would only add lag.
     */
    void command(String line, String key) {
        synchronized (queue) {
            if (!running) return;
            if (key != null) {
                ListIterator<Cmd> it = queue.listIterator(queue.size());
                while (it.hasPrevious()) {
                    Cmd c = it.previous();
                    if (c.key == null) break;
                    if (c.key.equals(key)) { c.line = line; return; }
                }
            }
            queue.add(new Cmd(line, key));
            queue.notifyAll();
        }
    }

    void stop() {
        boolean wasRunning = running;
        running = false;
        gl.stop();
        stopServer();
        synchronized (queue) { queue.notifyAll(); }
        if (!wasRunning) return;
        appendLine("quit");
        final Process p = process;
        if (p != null) {
            new Thread(() -> {
                try {
                    if (!p.waitFor(2, TimeUnit.SECONDS)) p.destroy();
                } catch (InterruptedException ignored) {
                    p.destroy();
                }
            }, "me-stop").start();
        }
    }

    // A qemu left behind by a killed app would keep running on its own;
    // ask it to quit before the control files are recreated.
    private void stopStale() throws InterruptedException {
        if (!statusFile.exists() || System.currentTimeMillis() - statusFile.lastModified() > 5000) return;
        appendLine("quit");
        long end = System.currentTimeMillis() + 5000;
        while (System.currentTimeMillis() < end && !readText(statusFile).contains("\"stopped\"")) {
            Thread.sleep(100);
        }
    }

    private void prepare() throws Exception {
        listener.onStatus("Подготовка файлов…");
        File bin = new File(root, "bin");
        File sysroot = new File(root, "sysroot");

        String stamp = String.valueOf(ctx.getPackageManager().getPackageInfo(ctx.getPackageName(), 0).lastUpdateTime);
        File stampFile = new File(root, "install.stamp");
        if (!stamp.equals(readText(stampFile).trim())) {
            deleteTree(bin);
            deleteTree(sysroot);
            deleteTree(new File(root, "serverroot"));
            stampFile.delete();
        }

        File binary = new File(bin, "ew3");
        if (!binary.exists()) {
            bin.mkdirs();
            try (InputStream in = new BufferedInputStream(ctx.getAssets().open("ew3"))) {
                copy(in, new FileOutputStream(binary));
            }
        }

        File done = new File(sysroot, ".done");
        if (!done.exists()) {
            listener.onStatus("Распаковка системных библиотек…\nЭто делается один раз.");
            unzipAsset("sysroot.zip");
            done.createNewFile();
        }
        File serverRoot = new File(root, "serverroot");
        File serverDone = new File(serverRoot, ".done");
        if (!serverDone.exists()) {
            listener.onStatus("Распаковка сервера…");
            deleteTree(serverRoot);
            unzipAsset("serverroot.zip");
            serverDone.createNewFile();
        }
        writeText(stampFile, stamp);
        // qemu-user refuses to load a guest program whose file lacks the execute bit.
        binary.setExecutable(true, true);
        new File(sysroot, "lib/ld-linux-armhf.so.3").setExecutable(true, true);
        new File(sysroot, "usr/bin/python3.8").setExecutable(true, true);

        File game = new File(root, "game");
        File libDir = new File(game, NATIVE_DIR);
        libDir.mkdirs();

        File external = Storage.mainDir(ctx);
        String where = Storage.describe(ctx);
        File ready = new File(game, ".data-ready");
        if (!ready.exists()) {
            File apk = external == null ? null : Storage.firstWithSuffix(ctx, ".apk");
            if (apk == null) {
                throw new IOException("Не найден оригинальный APK игры (Eternity Warriors 3 4.1.0).\nПоложите его и данные игры (cache-zip или main.*.obb) в папку:\n" + where);
            }
            listener.onStatus("Извлечение файлов игры из APK…");
            extractApk(apk, game);
            // The engine reads assets/bin/Data straight out of the APK, so it needs the file itself.
            try (InputStream in = new BufferedInputStream(new FileInputStream(apk))) {
                copy(in, new FileOutputStream(new File(game, "base.apk")));
            }
                        File obbDir = new File(game, OBB_DIR);
            obbDir.mkdirs();
            File obb = Storage.firstWithSuffix(ctx, ".obb");
            File cache = Storage.firstWithSuffix(ctx, ".zip");
            if (obb != null) {
                listener.onStatus("Копирование данных игры (~300 МБ)…\nЭто делается один раз.");
                linkOrCopy(obb, new File(obbDir, obb.getName()));
            } else if (cache != null) {
                listener.onStatus("Распаковка данных игры (~300 МБ)…\nЭто делается один раз.");
                extractObb(cache, obbDir);
            } else if (!extractObbFromApk(apk, obbDir)) {
                throw new IOException("Не найдены данные игры (cache-zip или main.*.obb).\nПоложите их в папку:\n" + where);
            }
            ready.createNewFile();
        }
        File props = new File(game, "glu_properties.txt");
        if (!props.exists()) {
            File apk = new File(game, "base.apk");
            try {
                writeGluProperties(apk, props);
            } catch (Exception e) {
                props.delete();
                throw new IOException("Не удалось прочитать настройки Glu из APK: " + e);
            }
        }
    }

    private static int intSetting(java.util.Map<String, String> m, String key, int def) {
        try { return Integer.parseInt(m.getOrDefault(key, String.valueOf(def))); } catch (NumberFormatException e) { return def; }
    }

    /**
     * res/raw/properties.dat of the APK (AES-128-CBC; key and IV are two 16-byte arrays inside classes.dex of 4.1.0)
     * into glu_properties.txt, which the port's AJTUtil.GetProperty reads (see tools/extract_properties.sh).
     */
    private static void writeGluProperties(File apk, File out) throws Exception {
        byte[] dex, dat;
        try (ZipFile z = new ZipFile(apk)) {
            dex = readAll(z, "classes.dex");
            dat = readAll(z, "res/raw/properties.dat");
        }
        byte[] key = Arrays.copyOfRange(dex, 0x301c68, 0x301c68 + 16), iv = Arrays.copyOfRange(dex, 0x301c80, 0x301c80 + 16);
        javax.crypto.Cipher c = javax.crypto.Cipher.getInstance("AES/CBC/PKCS5Padding");
        c.init(javax.crypto.Cipher.DECRYPT_MODE, new javax.crypto.spec.SecretKeySpec(key, "AES"), new javax.crypto.spec.IvParameterSpec(iv));
        byte[] text = c.doFinal(dat);
        if (new String(text, "UTF-8").indexOf('=') < 0) throw new IOException("properties.dat: неожиданное содержимое");
        try (FileOutputStream o = new FileOutputStream(out)) { o.write(text); }
    }

    private static byte[] readAll(ZipFile z, String name) throws IOException {
        ZipEntry e = z.getEntry(name);
        if (e == null) throw new IOException("В APK нет " + name);
        ByteArrayOutputStream bo = new ByteArrayOutputStream();
        pump(z.getInputStream(e), bo);
        return bo.toByteArray();
    }

    private volatile Process serverProcess;

    /**
     * The stand-in Glu server (server/ew3server.py) runs next to the game, in the same libqemu.so: Python 3.8 for
     * armhf from the sysroot. The game talks to it over 127.0.0.1 (EW3_SERVER). Returns when :18080 answers.
     */
    private void startServer(File qemu) throws Exception {
        listener.onStatus("Запуск сервера…\nПервый раз это занимает до минуты.");
        File sysroot = new File(root, "sysroot");
        File serverRoot = new File(root, "serverroot");
        File data = new File(root, "serverdata");
        data.mkdirs();
        File obb = new File(root, "game/" + OBB_DIR);
        File[] obbs = obb.listFiles((d, n) -> n.startsWith("main.") && n.endsWith(".obb"));
        ProcessBuilder b = new ProcessBuilder(qemu.getPath(), "-cpu", "cortex-a15", "-B", "0x100000000",
                "-L", sysroot.getPath(), new File(sysroot, "usr/bin/python3.8").getPath(),
                "-u", new File(serverRoot, "server/ew3server.py").getPath(),
                "--data", data.getPath());
        if (obbs != null && obbs.length > 0) { b.command().add("--obb"); b.command().add(obbs[0].getPath()); }
        Map<String, String> env = b.environment();
        // Patched/recovered AssetBundles: the server writes them here, the game reads them from here (or over HTTP).
        File bundleCache = new File(data, "bundle_cache");
        bundleCache.mkdirs();
        env.put("EW3_BUNDLE_CACHE", bundleCache.getPath());
        env.put("PYTHONHOME", "/usr");
        env.put("PYTHONDONTWRITEBYTECODE", "1");
        env.put("PYTHONIOENCODING", "utf-8");
        env.put("GLIBC_TUNABLES", "glibc.pthread.rseq=0");
        env.put("HOME", new File(root, "home").getPath());
        // The IPA of v0.1.0 (optional) unlocks the campaign levels; the server converts its bundles on first use.
        File ipa = Storage.firstWithSuffix(ctx, ".ipa");
        if (ipa != null) env.put("EW3_IPA", ipa.getPath());
        b.redirectErrorStream(true);
        b.redirectOutput(ProcessBuilder.Redirect.appendTo(new File(logFile.getParentFile(), "server.log")));
        appendLog("[wrapper] server: " + b.command());
        Process p = b.start();
        serverProcess = p;
        long end = SystemClock.elapsedRealtime() + 180000;
        while (SystemClock.elapsedRealtime() < end) {
            if (!p.isAlive()) throw new IOException("Сервер игры завершился (код " + p.exitValue() + "). Смотрите server.log рядом с логом.");
            try (java.net.Socket s = new java.net.Socket()) {
                s.connect(new java.net.InetSocketAddress("127.0.0.1", 18080), 300);
                appendLog("[wrapper] server is up");
                return;
            } catch (IOException notYet) {
                Thread.sleep(500);
            }
        }
        throw new IOException("Сервер игры не запустился за 3 минуты. Смотрите server.log.");
    }

    private void stopServer() {
        Process p = serverProcess;
        serverProcess = null;
        if (p != null) p.destroy();
    }

    /** lib/armeabi-v7a/{libmain,libmono,libunity}.so of the APK into game/. */
    private void extractApk(File apk, File game) throws IOException {
        String base = game.getCanonicalPath() + File.separator;
        int libs = 0;
        try (ZipFile z = new ZipFile(apk)) {
            for (String lib : NATIVE_LIBS) {
                ZipEntry e = z.getEntry(NATIVE_DIR + "/" + lib);
                if (e == null) throw new IOException("В APK нет " + NATIVE_DIR + "/" + lib + ".\nНужна версия 4.1.0 (armeabi-v7a).");
                File out = new File(game, e.getName());
                if (!out.getCanonicalPath().startsWith(base)) throw new IOException("bad zip entry " + e.getName());
                out.getParentFile().mkdirs();
                copy(z.getInputStream(e), new FileOutputStream(out));
                libs++;
            }
        }
    }

    /** The main.*.obb inside a cache zip into obbDir. */
    private void extractObb(File zip, File obbDir) throws IOException {
        int count = 0;
        try (ZipFile z = new ZipFile(zip)) {
            java.util.Enumeration<? extends ZipEntry> en = z.entries();
            while (en.hasMoreElements()) {
                ZipEntry e = en.nextElement();
                String n = e.getName();
                if (e.isDirectory() || !n.endsWith(".obb")) continue;
                String name = n.substring(n.lastIndexOf('/') + 1);
                copy(z.getInputStream(e), new FileOutputStream(new File(obbDir, name)));
                count++;
            }
        }
        if (count == 0) throw new IOException("В zip нет файла .obb\nНужен cache игры 4.1.0.");
    }

    /** Some repacks carry the expansion file inside the APK (assets/sdcard/Android/obb/...). */
    private boolean extractObbFromApk(File apk, File obbDir) throws IOException {
        try (ZipFile z = new ZipFile(apk)) {
            java.util.Enumeration<? extends ZipEntry> en = z.entries();
            while (en.hasMoreElements()) {
                ZipEntry e = en.nextElement();
                String n = e.getName();
                if (e.isDirectory() || !n.endsWith(".obb")) continue;
                listener.onStatus("Распаковка данных игры (~300 МБ)…\nЭто делается один раз.");
                copy(z.getInputStream(e), new FileOutputStream(new File(obbDir, n.substring(n.lastIndexOf('/') + 1))));
                return true;
            }
        }
        return false;
    }

    private void launch() throws Exception {
        listener.onStatus("Запуск игры…");
        File qemu = new File(ctx.getApplicationInfo().nativeLibraryDir, "libqemu.so");
        if (!qemu.exists()) throw new IOException("Нет libqemu.so в " + qemu.getParent());

        control.mkdirs();
        statusFile.delete();
        commandsFile.delete();
        commandsFile.createNewFile();
        fifo.delete();
        Os.mkfifo(fifo.getPath(), 0600);
        File glCmd = new File(root, "gl_cmd.pipe"), glReply = new File(root, "gl_reply.pipe");
        glCmd.delete();
        glReply.delete();
        Os.mkfifo(glCmd.getPath(), 0600);
        Os.mkfifo(glReply.getPath(), 0600);
        logFile.delete();
        gl.start();

        startServer(qemu);
        ProcessBuilder b = new ProcessBuilder(qemu.getPath());
        // Diagnostics: extra qemu arguments, one per line, from qemu_args.txt next to the log.
        for (String arg : readText(new File(logFile.getParentFile(), "qemu_args.txt")).split("\n")) {
            if (!arg.trim().isEmpty()) b.command().add(arg.trim());
        }
        // Android hides /proc/sys/vm/mmap_min_addr, so qemu would try to reserve guest memory at
        // 0x1000 and be refused; a non-zero guest base sidesteps that.
        // The default "any" CPU makes qemu emulate NEON/VFP through slow helpers; a real Cortex-A15
        // profile is several times faster on the game's own code.
        b.command().add("-cpu");
        b.command().add("cortex-a15");
        b.command().add("-B");
        b.command().add("0x100000000");
        b.command().add("-L");
        b.command().add(new File(root, "sysroot").getPath());
        b.command().add(new File(root, "bin/ew3").getPath());
        b.command().add(new File(root, "game").getPath());
        Map<String, String> env = b.environment();
        env.put("HOME", new File(root, "home").getPath());
        env.put("SDL_VIDEODRIVER", "offscreen");
        env.put("SDL_AUDIODRIVER", "disk");
        env.put("SDL_DISKAUDIOFILE", fifo.getPath());
        // Shorter than one 1024-frame period (23.2 ms): the device thread is then paced by the FIFO, see audioLoop().
        env.put("SDL_DISKAUDIODELAY", "15");
        env.put("EW3_SERVER", "127.0.0.1");
        env.put("EW3_BUNDLE_CACHE", new File(root, "serverdata/bundle_cache").getPath());
        env.put("EW3_ALLOW_UNRESOLVED", "1");
        env.put("EW3_CONTROL_DIR", control.getPath());
        // OpenGL ES calls are executed by the app on the GPU (GlBridge); nothing renders inside qemu.
        env.put("EW3_GL_BRIDGE", "1");
        env.put("EW3_GL_CMD", glCmd.getPath());
        env.put("EW3_GL_REPLY", glReply.getPath());
        env.put("EW3_WIDTH", String.valueOf(renderW));
        env.put("EW3_HEIGHT", String.valueOf(renderH));
        env.put("EW3_FB_PROBE_INTERVAL", "0");
        env.put("EW3_NO_CURSOR", "1");
        env.put("EW3_TOUCH", "1");
        env.put("EW3_SYSTEM_FONT", "/system/fonts/RobotoStatic-Regular.ttf");
        // Saves go to BridgeGames/<package>/save when there is access (mirrored to the private folder), else private.
        File saveDir = Storage.saveDir(ctx, new File(root, "save"));
        appendLog("[wrapper] saves: " + saveDir);
        env.put("EW3_SAVEDIR", saveDir.getPath());
        // An ordinary touch phone to the engine: its own on-screen controls, no PowerA pad until one is used.
        File dir = logFile.getParentFile();
        // engine_env.txt: KEY=VALUE per line, added to the port environment.
        for (String line : readText(new File(dir, "engine_env.txt")).split("\n")) {
            int eq = line.indexOf('=');
            if (eq > 0 && !line.trim().startsWith("#")) env.put(line.substring(0, eq).trim(), line.substring(eq + 1).trim());
        }
        java.util.Map<String, String> settings = SettingsActivity.load(ctx);
        applySettings(settings, env);
        // glibc looks at /etc/localtime again on every localtime() while TZ is unset (the game asks ~150 times
        // a second: openat + fstat + read + close each); with TZ given it reads nothing.
        env.put("TZ", posixTz());
        // glibc 2.35+ registers rseq at startup; Android's seccomp filter may kill the process for it.
        env.put("GLIBC_TUNABLES", "glibc.pthread.rseq=0");
        File home = new File(root, "home");
        home.mkdirs();
        // Loader trace stays on while the Android build is being brought up; add notrace.flag next to the log to mute it.
        if (!new File(logFile.getParentFile(), "notrace.flag").exists() && !"0".equals(settings.get("TRACE"))) env.put("LOADER_TRACE", "1");
        // Diagnostics: run diag_cmd.txt with sh instead of the game, same uid and environment.
        File diag = new File(logFile.getParentFile(), "diag_cmd.txt");
        if (diag.exists()) {
            env.put("QEMU", qemu.getPath());
            env.put("STRACE", new File(ctx.getApplicationInfo().nativeLibraryDir, "libmstrace.so").getPath());
            env.put("ROOT", root.getPath());
            b.command("/system/bin/sh", "-c", readText(diag));
        }
        // cpu_mask.txt next to the log (a hex mask, e.g. "c0" = cores 6-7): qemu and all its threads stay on those
        // cores. The frequency limiter caps clusters differently from moment to moment, and the scheduler keeps
        // moving the game's one busy thread onto whichever is free - often a capped one.
        String mask = readText(new File(logFile.getParentFile(), "cpu_mask.txt")).trim();
        if (mask.isEmpty() && "1".equals(settings.get("CPU_PRIME"))) mask = "c0";
        if (diag.exists()) mask = "";
        if (mask.matches("[0-9a-fA-F]{1,4}")) {
            b.command().add(0, "/system/bin/taskset");
            b.command().add(1, mask);
            appendLog("[wrapper] qemu pinned to cpu mask 0x" + mask);
        }
        b.redirectErrorStream(true);
        b.redirectOutput(ProcessBuilder.Redirect.appendTo(logFile));

        running = true;
        final long startedAt = SystemClock.elapsedRealtime();
        appendLog("[wrapper] " + b.command());
        process = b.start();
        final Process p = process;
        perf.spread = "1".equals(settings.get("CPU_SPREAD"));
        perf.start(p, !"0".equals(settings.get("PERF_HINT")), intSetting(settings, "FPS_LIMIT", 120));
        new Thread(this::writerLoop, "me-commands").start();
        new Thread(this::injectLoop, "me-inject").start();
        new Thread(this::audioLoop, "me-audio").start();
        new Thread(() -> {
            int code = -1;
            try { code = p.waitFor(); } catch (InterruptedException ignored) { }
            appendLog("[wrapper] qemu exited with code " + code
                    + (code > 128 ? " (signal " + (code - 128) + ")" : "")
                    + " after " + (SystemClock.elapsedRealtime() - startedAt) + " ms");
            stopServer();
            if (running) {
                running = false;
                listener.onExit(code);
            }
        }, "me-watch").start();
    }

    /**
     * settings.txt (SettingsActivity) into the game's environment. EW3_* keys go to the port as they are,
     * except the two "leave it alone" values of the menu (DPI 0, NEON -1); the rest are the wrapper's own switches.
     */
    private void applySettings(java.util.Map<String, String> settings, Map<String, String> env) {
        for (java.util.Map.Entry<String, String> e : settings.entrySet()) {
            String k = e.getKey(), v = e.getValue();
            if (!k.startsWith("EW3_")) continue;
            if (k.equals("EW3_SCREEN_DPI") && v.equals("0")) continue;
            if (k.equals("EW3_NEON_MATH") && v.equals("-1")) continue;
            env.put(k, v);
        }
        // The menu's frame-rate limit is what the engine is told to run at (src/fps_unlock.cpp).
        if (settings.containsKey("FPS_LIMIT")) env.put("EW3_TARGET_FPS", settings.get("FPS_LIMIT"));
        // Our qemu: guest syscall counts and a sampled guest-PC profile every 10 s in the log.
        // Off by default: the sampling profiler signals the engine thread 250 times a second, and that can leave Boehm's
        // stop-the-world waiting forever for two freshly started Mono threads (game frozen on a black screen).
        if ("1".equals(settings.get("PROFILING"))) {
            env.put("QEMU_SYSCALL_STATS", "1");
            env.put("QEMU_GUEST_PROF", "1");
            env.put("EW3_GL_PROFILE", "1");
            env.put("EW3_PC_PROF", "1");
        }
        appendLog("[app] settings: " + settings);
    }

    /** The phone's current UTC offset as a POSIX TZ string ("<+0300>-3:00": POSIX counts west of Greenwich). */
    private static String posixTz() {
        int min = java.util.TimeZone.getDefault().getOffset(System.currentTimeMillis()) / 60000;
        int a = Math.abs(min);
        return String.format(java.util.Locale.US, "<%s%02d%02d>%s%d:%02d", min < 0 ? "-" : "+", a / 60, a % 60,
                min < 0 ? "" : "-", a / 60, a % 60);
    }

    /**
     * Writes whatever is queued in one go. The port paces the lines itself (touch lines several per
     * frame, everything else one per frame), so the pause here only lets moves coalesce.
     */
    private void writerLoop() {
        StringBuilder batch = new StringBuilder();
        try (FileOutputStream out = new FileOutputStream(commandsFile, true)) {
            while (running) {
                batch.setLength(0);
                synchronized (queue) {
                    while (queue.isEmpty() && running) queue.wait();
                    if (!running) break;
                    for (Cmd c : queue) batch.append(c.line).append('\n');
                    queue.clear();
                }
                out.write(batch.toString().getBytes("US-ASCII"));
                Thread.sleep(4);
            }
        } catch (Exception ignored) {
        }
    }


    /**
     * Diagnostics: lines of inject.txt next to the log are queued as port commands once, then the file is
     * removed (adb push inject.txt ...). Lets a test tap or press buttons without touching the screen.
     */
    private void injectLoop() {
        File f = new File(logFile.getParentFile(), "inject.txt");
        while (running) {
            try {
                if (f.isFile()) {
                    String text = readText(f);
                    f.delete();
                    for (String line : text.split("\n")) {
                        line = line.trim();
                        if (line.isEmpty()) continue;
                        if (line.startsWith("sleep ")) { Thread.sleep(Long.parseLong(line.substring(6).trim())); continue; }
                        appendLog("[inject] " + line);
                        command(line, null);
                    }
                }
                Thread.sleep(300);
            } catch (Exception ignored) {
            }
        }
    }

    /**
     * Plays what the port's SDL "disk" audio device writes into the FIFO.
     *
     * The AudioTrack is the clock. SDL's disk device paces itself with a sleep (SDL_DISKAUDIODELAY) that is not
     * exactly one period, so left alone it runs slightly ahead of real time and everything between it and the
     * speaker fills up: with a 64 KB pipe and a 64 KB track buffer the sound ended up ~0.75 s late after a couple
     * of minutes. So the sleep is set shorter than a period (launch()), the pipe is shrunk to one period and the
     * track buffer to the menu's AUDIO_LATENCY_MS: the SDL thread then blocks on the pipe and advances only as fast as the
     * speaker consumes, and there is nowhere for a backlog to build.
     */
    private void audioLoop() {
        int min = AudioTrack.getMinBufferSize(SAMPLE_RATE, AudioFormat.CHANNEL_OUT_STEREO, AudioFormat.ENCODING_PCM_16BIT);
        // 0 (the default) is the smallest buffer the device allows.
        int latencyMs = 0;
        try { latencyMs = Integer.parseInt(SettingsActivity.load(ctx).getOrDefault("AUDIO_LATENCY_MS", "0")); } catch (NumberFormatException ignored) { }
        int bufBytes = Math.max(min, (SAMPLE_RATE * 4 * Math.max(0, Math.min(latencyMs, 1000)) / 1000) & ~3);
        AudioTrack track = new AudioTrack.Builder()
                .setAudioAttributes(new AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_GAME)
                        .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
                .setAudioFormat(new AudioFormat.Builder()
                        .setSampleRate(SAMPLE_RATE)
                        .setChannelMask(AudioFormat.CHANNEL_OUT_STEREO)
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
                .setBufferSizeInBytes(bufBytes)
                .setPerformanceMode(AudioTrack.PERFORMANCE_MODE_LOW_LATENCY)
                .setTransferMode(AudioTrack.MODE_STREAM)
                .build();
        FileDescriptor fd = null;
        try {
            // O_RDWR keeps the FIFO open without a writer yet and never reports EOF,
            // so the loop can poll with a timeout and notice when the game stops.
            fd = Os.open(fifo.getPath(), OsConstants.O_RDWR | OsConstants.O_NONBLOCK, 0);
            int pipe = -1;
            if (android.os.Build.VERSION.SDK_INT >= 30) {
                try { pipe = Os.fcntlInt(fd, 1031 /* F_SETPIPE_SZ */, 4096); } catch (ErrnoException ignored) { }
            }
            appendLog("[audio] track buffer " + bufBytes + " bytes (" + bufBytes * 1000L / (SAMPLE_RATE * 4) + " ms, min " + min
                    + "), pipe " + pipe + " bytes");
            StructPollfd[] polls = { new StructPollfd() };
            polls[0].fd = fd;
            polls[0].events = (short) OsConstants.POLLIN;
            byte[] buf = new byte[16384];
            boolean playing = false;
            while (running) {
                polls[0].revents = 0;
                if (Os.poll(polls, 100) <= 0) continue;
                int n;
                try {
                    n = Os.read(fd, buf, 0, buf.length);
                } catch (ErrnoException e) {
                    if (e.errno == OsConstants.EAGAIN) continue;
                    break;
                } catch (InterruptedIOException e) {
                    break;
                }
                if (n <= 0) continue;
                // While the game is loading its audio is read and dropped; the CPU
                // is saturated then and playing it back would only crackle.
                if (muted) continue;
                if (!playing) { track.play(); playing = true; }
                track.write(buf, 0, n);
            }
        } catch (ErrnoException ignored) {
        } finally {
            if (fd != null) try { Os.close(fd); } catch (ErrnoException ignored) { }
            track.release();
        }
    }

    private void unzipAsset(String name) throws IOException {
        String rootPath = root.getCanonicalPath() + File.separator;
        try (ZipInputStream z = new ZipInputStream(new BufferedInputStream(ctx.getAssets().open(name)))) {
            ZipEntry e;
            while ((e = z.getNextEntry()) != null) {
                File out = new File(root, e.getName());
                if (!out.getCanonicalPath().startsWith(rootPath)) throw new IOException("bad zip entry " + e.getName());
                if (e.isDirectory()) { out.mkdirs(); continue; }
                out.getParentFile().mkdirs();
                copy(z, new FileOutputStream(out), false);
            }
        }
    }

    // The OBB is ~300 MB; a symlink saves copying it into private storage.
    private void linkOrCopy(File src, File dst) throws IOException {
        if (dst.length() == src.length() && dst.length() > 0) return;
        dst.delete();
        try {
            Os.symlink(src.getPath(), dst.getPath());
        } catch (ErrnoException ignored) {
        }
        if (dst.length() != src.length()) {
            dst.delete();
            listener.onStatus("Копирование " + src.getName() + "…");
            copy(new FileInputStream(src), new FileOutputStream(dst));
        }
    }

    void log(String line) { appendLog("[app] " + line); }

    private void appendLog(String line) {
        try (FileOutputStream out = new FileOutputStream(logFile, true)) {
            out.write((line + "\n").getBytes("UTF-8"));
        } catch (IOException ignored) {
        }
    }

    private void appendLine(String line) {
        try (FileOutputStream out = new FileOutputStream(commandsFile, true)) {
            out.write((line + "\n").getBytes("US-ASCII"));
        } catch (IOException ignored) {
        }
    }

    private static int intField(String s, String key) {
        int i = s.indexOf(key);
        if (i < 0) return 0;
        i += key.length();
        int j = i;
        while (j < s.length() && Character.isDigit(s.charAt(j))) j++;
        try { return Integer.parseInt(s.substring(i, j)); } catch (NumberFormatException e) { return 0; }
    }

    private static String readText(File f) {
        if (!f.isFile()) return "";
        try (FileInputStream in = new FileInputStream(f)) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[4096];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            return out.toString("UTF-8");
        } catch (IOException e) {
            return "";
        }
    }

    private static void writeText(File f, String text) throws IOException {
        try (FileOutputStream out = new FileOutputStream(f)) { out.write(text.getBytes("UTF-8")); }
    }

    private static void copy(InputStream in, OutputStream out) throws IOException {
        try (InputStream i = in) { copy(i, out, true); }
    }

    private static void copy(InputStream in, OutputStream out, boolean unused) throws IOException {
        byte[] buf = new byte[65536];
        int n;
        try {
            while ((n = in.read(buf)) >= 0) if (n > 0) out.write(buf, 0, n);
        } finally {
            out.close();
        }
    }

    /** Like copy, but leaves both streams open (the output is a ZipOutputStream entry). */
    private static void pump(InputStream in, OutputStream out) throws IOException {
        try (InputStream i = in) {
            byte[] buf = new byte[65536];
            int n;
            while ((n = i.read(buf)) >= 0) if (n > 0) out.write(buf, 0, n);
        }
    }

    private static void deleteTree(File f) {
        File[] children = f.listFiles();
        if (children != null) for (File c : children) deleteTree(c);
        f.delete();
    }
}
