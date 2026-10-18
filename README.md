# Eternity Warriors 3 Bridge

Прослойка и локальный сервер для запуска **Eternity Warriors 3 v4.1.0** (`com.glu.ewarriors3`, Android `armeabi-v7a`, Unity 4.6.1p5 + Mono) без серверов Glu, которые давно закрыты: на **Android-телефоне** (готовый релиз) и на **Windows 11** (через qemu в WSL, нативный хост в работе). Удалённые с CDN уровни, враги и боссы восстанавливаются из архивной сборки **v0.1.0 (iOS IPA)**.

Файлы игры в репозиторий и релизы не входят: нужны ваши собственные (APK 4.1.0 и её данные).

---

## Android (релиз v0.2)

Скачайте APK из релиза (последний `v0.2`) и следуйте `INSTALL.txt`:

1. Установить `Eternity-Warriors-3-Bridge-0.2.apk`, открыть приложение, разрешить доступ ко всем файлам и уведомления.
2. Положить в `/sdcard/BridgeGames/com.jamescrumble.ew3/` оригинальный `E-Warriors-3-v4-1-0.apk` и cache-zip (или `main.4100.com.glu.ewarriors3.obb`). Для всех уровней кампании добавьте **расширенный пакет** `E-Warriors-3-v4-1-0-cache-extended.ew3x` (отдельный файл релиза, ~106 МБ) или IPA `31263-Eternity-Warriors-3-v0-1-0.ipa` (пакет проще и быстрее: IPA на телефоне конвертируется сервером).
3. Нажать «Играть». Первый запуск дольше: распаковка и старт сервера занимают до минуты.

Проверено на OnePlus CPH2723 (Android 16): частота кадров разблокирована до лимита из настроек (до 120; фактически 70-108 в зависимости от сцены, упор в процессор). Управление сенсорное; PvP, рейды, покупки и реклама отключены. Сохранения лежат в личной папке приложения (пропадают при удалении).

В настройках приложения:
- **Доступ из локальной сети**: сервер слушает `0.0.0.0`, и с компьютера в домашней сети открывается `http://<адрес телефона>:18080/docs` (Swagger: смотреть и менять сохранения). Логин `admin`, пароль показан в настройках и в уведомлении. На самом телефоне `/docs` открывается по `127.0.0.1:18080` без пароля, в том числе пока игра свёрнута: сервер держит уведомление (приложение просит разрешение на уведомления само).
- **Подключаться к другому серверу**: переключатель и поле с IPv4-адресом; игра идёт на указанный сервер (например, `python server/ew3server.py --host 0.0.0.0` на компьютере), встроенный не запускается.
- **Расширенный пакет** `E-Warriors-3-v4-1-0-cache-extended.ew3x` (zip на ~106 МБ, 36 готовых бандлов из IPA v0.1.0; собирается `tools/make_extended.py`): положите его рядом с APK игры, приложение распакует его один раз, и все уровни открыты без IPA и без конвертации на телефоне.

Приложение: игра исполняется в qemu-user (`libqemu.so`), OpenGL ES идёт на GPU телефона, а сервер на Python 3.8 работает внутри приложения в том же qemu. Подробности: [docs/PORTING_GUIDE.md](docs/PORTING_GUIDE.md#часть-7-android-bridge-apk).

---

## Windows (qemu в WSL)

Сейчас рабочий запуск — `tools/play_win.sh` из WSL: гость `port/build/ew3` под `qemu-arm`, графика через `host/build-win/ew3gl.exe` (ANGLE -> Direct3D 11), сервер `server/ew3server.py` на `:18080` (HTTP) и `:18024` (Gluon TCP). Нужны `ew3data/Android/obb/com.glu.ewarriors3/main.4100.com.glu.ewarriors3.obb` и, по желанию, `31263-Eternity-Warriors-3-v0-1-0.ipa` в корне проекта (открывает все 25 уровней кампании).

На ПК вместо IPA можно взять расширенный пакет: распакуйте `E-Warriors-3-v4-1-0-cache-extended.ew3x` (это zip) в `ew3data/server/bundle_cache/`, сервер поймёт, что набор полный.

`play_win.py` / `play_win.cmd` и нативный `ew3host.exe` (dynarmic, без WSL) не закончены, см. [PROJECT_STATE.md](PROJECT_STATE.md).

---

## Архитектура

```
Игра (port/build/ew3, ARM32 гость под qemu-user)
  ├── Bionic ELF loader: libunity.so, libmono.so, libmain.so
  ├── JNI-мост и заглушки SDK (Glu, Tapjoy, AJavaTools, UnityWWW)
  ├── Перехват сети (symtab_net.cpp / unity_www.cpp) -> 127.0.0.1:18080 / :18024
  └── GLES wire-протокол ──► GL на видеокарте:
        Android: apk/ GlBridge.java (GPU телефона)
        Windows: host/glbridge/ew3gl.exe (ANGLE -> D3D11)

Локальный бэкенд (server/ew3server.py; на Android внутри приложения)
  ├── HTTP CDN & Config (:18080): serverpost, DynamicContentInfo, index.version, AssetBundles
  ├── Gluon Edge (:18024, TCP + BSON): авторизация, синхронизация атрибутов профиля
  ├── Custom Game Server (server/cgs*.py): бои, лут, инвентарь, экипировка, ковка (Fuse/Evolve), скиллы, гача, квесты и дейлики
  └── Конвертер ассетов (server/bundle_patcher.py): патч OBB-бандлов и конвертация 33 недостающих бандлов из iOS IPA v0.1.0
      (Unity 4.2.1f4 iOS -> Unity 4.6.1p5 Android)
```

---

## Восстановленный контент и возможности

- **Полная эмуляция серверной логики (CGS)**:
  - Боевая система (`battle_start`, `battle_end`, подсчёт наград, опыта, монет, дропа предметов и босс-лута по таблицам `server/generated/game_data.json`).
  - Экипировка, инвентарь, продажа предметов, прокачка скиллов, слияние (`Fusion`), эволюция (`Evolution`), вставка камней и гача-сундуки.
  - Сюжетные, побочные и ежедневные задания (7 разнообразных дейликов на неделю в `base_uniform_global_manager`).
- **Восстановление утерянных с CDN бандлов из v0.1.0 IPA (`server/bundle_patcher.py`)** (готовый результат — расширенный пакет `.ew3x`, см. выше):
  - В OBB v4.1.0 присутствовали только стартовая деревня и 3 сцены Греции (`greece_1_scene`), а также базовый набор мобов (`base_char_enemy_base`: скелеты, летучие мыши, волки, зомби).
  - Из `31263-Eternity-Warriors-3-v0-1-0.ipa` автоматически конвертируются из формата Unity 4.2.1f4 (iOS) в формат Unity 4.6.1p5 (Android) **33 бандла**:
    - `base_char_enemy0` и `base_weapon_monster` (Циклоп, гарпии, минотавры, гоблины, элементали, ящеры, огненный демон, боссы Китая и Готики и их оружие).
    - 9 ресурсных бандлов окружения (`greece_raw_2..3`, `china_raw..3`, `china_bridge_raw`, `gothic_raw_1..3`).
    - 22 сцены уровней в 3 королевствах (**Moria / Greece**, **Binhai / China**, **Gothia / Gothic**), что открывает **все 25 уровней** на карте кампании.

---

## Сохранения и админ-панель

- **Файл сохранений**: `ew3data/server/players.json` (на Android — `files/serverdata/players.json` в личной папке приложения)
  - **`hc_current`** — донатная валюта (кристаллы / Gems, общая на аккаунт; хранится строкой, например `"99999"`).
  - **`warrior_sc_current` / `mage_sc_current` / `monk_sc_current`** — золото (монеты) каждого класса.
- **Swagger UI (при запущенном сервере)**: `http://127.0.0.1:18080/docs`
  - Позволяет просматривать и менять атрибуты профиля (`GET/PUT /admin/players/{player_id}/attributes/{name}`), а также смотреть логи пакетов CGS и Gluon.

---

## Сборка из исходников

- **Гостевой ARM32-лоадер (`port/build/ew3`)** — собирается в WSL:
  ```bash
  ./build.sh
  ```
- **Android-APK и релиз** (подробности в [docs/PORTING_GUIDE.md](docs/PORTING_GUIDE.md#71-сборка)):
  ```bash
  bash apk/make_sysroot.sh   # sysroot armhf + файлы сервера
  bash apk/build_apk.sh      # debug-APK
  server/.venv-android/bin/python tools/make_extended.py   # gamebin/E-Warriors-3-v4-1-0-cache-extended.ew3x из IPA
  tools/make_release.sh      # release/v<версия>/: подписанный APK, расширенный пакет, INSTALL.txt, RELEASE_NOTES.md, src, SHA256SUMS
  ```
  Всё нужное для сборки (Android SDK с `adb` — `tools/adb`, JDK, SDL для ARM, qemu в `third_party/qemu/`) лежит в проекте, вне git.
- **GL-мост для Windows (`host/build-win/ew3gl.exe`)** — MSVC + CMake + Ninja из WSL: `host/build.sh ew3gl`. Цель `ew3host` пока не линкуется (хост не закончен).
- **Кэш сконвертированных бандлов**: `ew3data/server/bundle_cache/` (пересоздаётся автоматически при изменении хэшей в `server/ew3server.py`; каталог задаёт `EW3_BUNDLE_CACHE`).

---

## Документация

- [PROJECT_STATE.md](PROJECT_STATE.md) — состояние и планы.
- [docs/PORTING_GUIDE.md](docs/PORTING_GUIDE.md) — как делался порт, по шагам (части 1–7, Android — часть 7).
- [docs/NETWORK.md](docs/NETWORK.md) — сетевые маршруты игры и их локальная подмена.

## Лицензии

Код проекта: GPL-3.0 (`port/LICENSE`). `libqemu.so` в APK — QEMU (GPL-2.0) с патчами, они приложены к релизу. Eternity Warriors 3 и его материалы принадлежат Glu; проект с Glu не связан и файлы игры не распространяет.
