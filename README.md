# Eternity Warriors 3 Bridge

Прослойка и локальный сервер для запуска **Eternity Warriors 3 v4.1.0** (`com.glu.ewarriors3`, Android `armeabi-v7a`, Unity 4.6.1p5 + Mono) без серверов Glu, которые давно закрыты: на **Android-телефоне** (готовый релиз) и на **Windows 11** (через qemu в WSL, нативный хост в работе). Удалённые с CDN уровни, враги и боссы восстанавливаются из архивной сборки **v0.1.0 (iOS IPA)**.

Файлы игры в репозиторий и релизы не входят: нужны ваши собственные (APK 4.1.0 и её данные).

---

## Android (релиз v0.1)

Скачайте APK из релиза `v0.1` и следуйте `INSTALL.txt`:

1. Установить `Eternity-Warriors-3-Bridge-0.1.apk`, открыть приложение, разрешить доступ ко всем файлам.
2. Положить в `/sdcard/BridgeGames/com.jamescrumble.ew3/` оригинальный `E-Warriors-3-v4-1-0.apk` и cache-zip (или `main.4100.com.glu.ewarriors3.obb`). Необязательно: `31263-Eternity-Warriors-3-v0-1-0.ipa` для восстановленных уровней (на телефоне не проверялось).
3. Нажать «Играть». Первый запуск дольше: распаковка и старт сервера занимают до минуты.

Проверено на OnePlus CPH2723 (Android 16): ~60 кадров/с. Управление сенсорное; PvP, рейды, покупки и реклама отключены. Сохранения лежат в личной папке приложения (пропадают при удалении).

Приложение: игра исполняется в qemu-user (`libqemu.so`), OpenGL ES идёт на GPU телефона, а сервер на Python 3.8 работает внутри приложения в том же qemu. Подробности: [docs/PORTING_GUIDE.md](docs/PORTING_GUIDE.md#часть-7-android-bridge-apk).

---

## Windows (qemu в WSL)

Сейчас рабочий запуск — `tools/play_win.sh` из WSL: гость `port/build/ew3` под `qemu-arm`, графика через `host/build-win/ew3gl.exe` (ANGLE -> Direct3D 11), сервер `server/ew3server.py` на `:18080` (HTTP) и `:18024` (Gluon TCP). Нужны `ew3data/Android/obb/com.glu.ewarriors3/main.4100.com.glu.ewarriors3.obb` и, по желанию, `31263-Eternity-Warriors-3-v0-1-0.ipa` в корне проекта (открывает все 25 уровней кампании).

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
- **Восстановление утерянных с CDN бандлов из v0.1.0 IPA (`server/bundle_patcher.py`)**:
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
  tools/make_release.sh      # release/v<версия>/: подписанный APK, INSTALL.txt, RELEASE_NOTES.md, src, SHA256SUMS
  ```
- **GL-мост для Windows (`host/build-win/ew3gl.exe`)** — MSVC + CMake + Ninja из WSL: `host/build.sh ew3gl`. Цель `ew3host` пока не линкуется (хост не закончен).
- **Кэш сконвертированных бандлов**: `ew3data/server/bundle_cache/` (пересоздаётся автоматически при изменении хэшей в `server/ew3server.py`; каталог задаёт `EW3_BUNDLE_CACHE`).

---

## Документация

- [PROJECT_STATE.md](PROJECT_STATE.md) — состояние и планы.
- [docs/PORTING_GUIDE.md](docs/PORTING_GUIDE.md) — как делался порт, по шагам (части 1–7, Android — часть 7).
- [docs/NETWORK.md](docs/NETWORK.md) — сетевые маршруты игры и их локальная подмена.

## Лицензии

Код проекта: GPL-3.0 (`port/LICENSE`). `libqemu.so` в APK — QEMU (GPL-2.0) с патчами, они приложены к релизу. Eternity Warriors 3 и его материалы принадлежат Glu; проект с Glu не связан и файлы игры не распространяет.
