package com.jamescrumble.ew3;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;

import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * Keeps the stand-in server alive while the game is minimized: Android freezes the processes of a cached app, and
 * the server is one of them. A foreground service with an ongoing notification says that it is running and where
 * /docs (Swagger, the admin API) can be opened. With "access from the local network" on it also holds a partial
 * wake lock and a Wi-Fi lock, so the server still answers when the screen is off.
 */
public final class ServerService extends Service {
    static final String EXTRA_LAN = "lan";
    static final int PORT = 18080;
    private static final String CHANNEL = "ew3_server";
    private static final int ID = 1;

    /** The GameProcess that started the service: a restarted game must not have its notification stopped by the old one. */
    private static volatile Object owner;

    private PowerManager.WakeLock wake;
    private WifiManager.WifiLock wifi;

    static void start(Context c, boolean lan, Object by) {
        owner = by;
        try {
            c.startForegroundService(new Intent(c, ServerService.class).putExtra(EXTRA_LAN, lan));
        } catch (RuntimeException e) {
            // Not allowed from the background; the server still runs, only without the notification.
        }
    }

    static void stop(Context c, Object by) {
        if (owner != by) return;
        owner = null;
        c.stopService(new Intent(c, ServerService.class));
    }

    static boolean notificationsAllowed(Context c) {
        return c.getSystemService(NotificationManager.class).areNotificationsEnabled();
    }

    /**
     * Asks for what the app is missing and Android lets it ask for: notifications (13+, without them the "server is
     * running" notification is hidden) and local-network access (where this Android has that permission).
     * INTERNET and the rest are granted at install; storage has its own dialog.
     */
    static void askNotifications(android.app.Activity a) {
        java.util.List<String> need = new ArrayList<>();
        if (Build.VERSION.SDK_INT >= 33
                && a.checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            need.add(android.Manifest.permission.POST_NOTIFICATIONS);
        }
        final String local = "android.permission.ACCESS_LOCAL_NETWORK";
        if (Build.VERSION.SDK_INT >= 36 && a.checkSelfPermission(local) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            try {
                a.getPackageManager().getPermissionInfo(local, 0);
                need.add(local);
            } catch (android.content.pm.PackageManager.NameNotFoundException notOnThisAndroid) { }
        }
        if (!need.isEmpty()) a.requestPermissions(need.toArray(new String[0]), 3);
    }

    /** IPv4 addresses of this phone on Wi-Fi, Ethernet or its own hotspot (mobile data is left out). */
    static List<String> addresses() {
        List<String> out = new ArrayList<>();
        try {
            for (NetworkInterface ni : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                String n = ni.getName();
                if (!ni.isUp() || ni.isLoopback() || !(n.startsWith("wlan") || n.startsWith("swlan") || n.startsWith("eth")
                        || n.startsWith("ap") || n.startsWith("softap"))) continue;
                for (InetAddress a : Collections.list(ni.getInetAddresses())) {
                    if (a instanceof Inet4Address && !a.isLoopbackAddress() && a.isSiteLocalAddress()) out.add(a.getHostAddress());
                }
            }
        } catch (Exception ignored) { }
        return out;
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        boolean lan = intent != null && intent.getBooleanExtra(EXTRA_LAN, false);
        NotificationManager nm = getSystemService(NotificationManager.class);
        NotificationChannel ch = new NotificationChannel(CHANNEL, "Сервер игры", NotificationManager.IMPORTANCE_LOW);
        ch.setDescription("Показывает, что сервер Eternity Warriors 3 работает в фоне");
        nm.createNotificationChannel(ch);

        StringBuilder text = new StringBuilder("На этом телефоне: http://127.0.0.1:" + PORT + "/docs");
        if (lan) {
            List<String> ips = addresses();
            if (ips.isEmpty()) text.append("\nЛокальная сеть: нет подключения к Wi-Fi");
            for (String ip : ips) text.append("\nС компьютера: http://").append(ip).append(':').append(PORT).append("/docs");
            // The server makes the password file when it starts; GameProcess starts this service again once it is up.
            String pw = "";
            try (java.io.FileInputStream in = new java.io.FileInputStream(new java.io.File(getFilesDir(), "serverdata/admin_password.txt"))) {
                java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
                byte[] b = new byte[256];
                int n;
                while ((n = in.read(b)) > 0) out.write(b, 0, n);
                pw = out.toString("UTF-8").trim();
            } catch (java.io.IOException ignored) { }
            text.append("\nЛогин: admin   Пароль: ").append(pw.isEmpty() ? "создаётся при запуске сервера…" : pw);
        }
        PendingIntent open = PendingIntent.getActivity(this, 0,
                new Intent(Intent.ACTION_VIEW, Uri.parse("http://127.0.0.1:" + PORT + "/docs")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        PendingIntent game = PendingIntent.getActivity(this, 1,
                new Intent(this, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        Notification n = new Notification.Builder(this, CHANNEL)
                .setSmallIcon(android.R.drawable.stat_notify_sync_noanim)
                .setContentTitle("Eternity Warriors 3: сервер работает")
                .setContentText(text.toString().split("\n")[0])
                // The password stays off the lock screen of a secured phone.
                .setVisibility(Notification.VISIBILITY_PRIVATE)
                .setPublicVersion(new Notification.Builder(this, CHANNEL)
                        .setSmallIcon(android.R.drawable.stat_notify_sync_noanim)
                        .setContentTitle("Eternity Warriors 3: сервер работает")
                        .build())
                .setStyle(new Notification.BigTextStyle().bigText(text.toString()))
                .setContentIntent(open)
                .addAction(new Notification.Action.Builder(null, "Открыть игру", game).build())
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setCategory(Notification.CATEGORY_SERVICE)
                .build();
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(ID, n, android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        } else {
            startForeground(ID, n);
        }
        releaseLocks();
        if (lan) {
            try {
                wake = getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "ew3:server");
                wake.acquire();
                wifi = getSystemService(WifiManager.class).createWifiLock(
                        Build.VERSION.SDK_INT >= 29 ? WifiManager.WIFI_MODE_FULL_LOW_LATENCY : WifiManager.WIFI_MODE_FULL_HIGH_PERF,
                        "ew3:server");
                wifi.acquire();
            } catch (RuntimeException ignored) { }
        }
        return START_NOT_STICKY;
    }

    private void releaseLocks() {
        try { if (wake != null && wake.isHeld()) wake.release(); } catch (RuntimeException ignored) { }
        try { if (wifi != null && wifi.isHeld()) wifi.release(); } catch (RuntimeException ignored) { }
        wake = null;
        wifi = null;
    }

    @Override public void onDestroy() {
        releaseLocks();
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) {
        return null;
    }
}
