# Eternity Warriors 3 Bridge (Windows 11 x64)

Нативный порт-прослойка и локальный сервер для запуска **Eternity Warriors 3 v4.1.0** (`com.glu.ewarriors3`, Android `armeabi-v7a`, Unity 4.6.1p5 + Mono) на Windows 11 x64 без Android-эмулятора, с восстановлением удалённых с CDN уровней, врагов и боссов из архивной сборки **v0.1.0 (iOS IPA)**.

---

## Быстрый старт

1. Убедитесь, что в рабочей папке находятся игровые архивы:
   - `ew3data/Android/obb/com.glu.ewarriors3/main.4100.com.glu.ewarriors3.obb` (кэш Android v4.1.0)
   - `31263-Eternity-Warriors-3-v0-1-0.ipa` в корне проекта (необязательно, но открывает все 25 уровней кампании в 3 королевствах, всех врагов и боссов)
2. Запустите игру через:
   ```bat
   play_win.cmd
   ```
   Скрипт (`play_win.py`) автоматически поднимает локальный сервер (`server/ew3server.py` на портах `:18080` HTTP и `:18024` Gluon TCP) и запускает `host/build-win/ew3host.exe`.

---

## Архитектура проекта

```
ew3host.exe (Windows x64, MSVC + dynarmic + ANGLE/SDL2)
  │
  ├─► Гостевой ARM32 процесс (port/build/ew3)
  │     ├── Bionic ELF loader: libunity.so, libmono.so, libmain.so
  │     ├── JNI-мост и заглушки SDK (Glu, Tapjoy, AJavaTools, UnityWWW)
  │     ├── Перехват сети (symtab_net.cpp / unity_www.cpp) -> 127.0.0.1:18080 / :18024
  │     └── GLES2 wire-протокол -> рендеринг через ANGLE (D3D11) на хосте
  │
  └─► Локальный бэкенд (server/ew3server.py)
        ├── HTTP CDN & Config (:18080): serverpost, DynamicContentInfo, index.version, AssetBundles
        ├── Gluon Edge (:18024, TCP + BSON): авторизация, синхронизация атрибутов профиля
        ├── Custom Game Server (server/cgs.py, server/cgs_state.py):
        │     бои, лут, инвентарь, экипировка, ковка (Fuse/Evolve), скиллы, гача, квесты и дейлики
        └── Конвертер ассетов (server/bundle_patcher.py):
              динамический патч OBB-бандлов и конвертация 33 недостающих бандлов из iOS IPA v0.1.0
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

- **Файл сохранений**: `ew3data/server/players.json`
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
- **Windows-хост (`host/build-win/ew3host.exe`)** — собирается через MSVC + CMake + Ninja:
  ```powershell
  cmake --build host/build-win --config Release
  ```
- **Кэш сконвертированных бандлов**: `ew3data/server/bundle_cache/` (пересоздаётся автоматически при изменении хэшей в `server/ew3server.py`).
