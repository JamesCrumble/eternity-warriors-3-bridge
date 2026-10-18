# Eternity Warriors 3 Bridge: состояние проекта

Цель: запустить Eternity Warriors 3 v4.1.0 (Glu, Android armeabi-v7a, Unity 4.6.1p5 + Mono) без серверов Glu: на **Android-телефоне** (Bridge-APK, выпущен) и на **Windows 11 x64** (qemu в WSL + GL на видеокарту через ANGLE; нативный хост в работе), с локальным сервером Gluon/CGS и восстановленным CDN-контентом (миры, мобы, боссы) из архивной iOS-сборки v0.1.0.

Обновлено: 2026-10-18.

## Статус

| Платформа | Состояние |
|---|---|
| **Android** | **релиз v0.2** (v0.1 выпущен раньше, тег `v0.1`): подписанный APK, сервер внутри приложения. Проверено на OnePlus CPH2723 (Android 16, Adreno 830): загрузка, уровень, бой, ~60 кадров/с. Уровни из `.ipa` на телефоне не проверялись |
| **Windows (WSL)** | работает: `tools/play_win.sh` (гость под `qemu-arm` в WSL, GL в `host/build-win/ew3gl.exe` через ANGLE -> D3D11, сервер Python). Релиз-пакета нет |
| **Windows (нативно)** | `ew3host.exe` **не закончен**: в `host/src/` только привязка dynarmic (`cpu.cpp`), память (`mem.c`) и заголовки. Нет `main`, ELF-загрузчика, сисколлов, потоков, сигналов, VFS и сокетов (план в `host/src/host.h`), exe не линкуется. `play_win.py` ссылается на каталоги, которых нет в дереве (`third_party/qemu-guest`, `wsl-distro`, `zig`) |

## Игра (`gamebin/` и корень, не в git)
- `E-Warriors-3-v4-1-0.apk`: `lib/armeabi-v7a/{libmain,libmono,libunity}.so`, `classes.dex` + `classes2.dex`
  (SDK Glu, Tapjoy, AWS). Движок в APK — **Unity 4.6.1p5** (`armeabi-v7a`, Mono).
- `E-Warriors-3-v4-1-0-cache.zip` -> `ew3data/Android/obb/com.glu.ewarriors3/main.4100.com.glu.ewarriors3.obb` (90 МБ).
- `E-Warriors-3-v4-1-0-cache-extended.ew3x`: расширенный пакет (zip, ~106 МБ): 33 бандла, конвертированные из IPA, и 3 пропатченных бандла OBB, готовые для сервера; делается `tools/make_extended.py`, заменяет IPA.
- `31263-Eternity-Warriors-3-v0-1-0.ipa`: архивная iOS-сборка v0.1.0 (Unity 4.2.1f4), содержащая все базовые сцены, окружение, мобов и боссов 3 королевств.
- Managed-DLL лежат в OBB (`assets/bin/Data/Managed/`): `Assembly-CSharp.dll`, `Assembly-CSharp-firstpass.dll`,
  `Photon3Unity3D.dll`, `UnityEngine*.dll`. Декомпилированы в `extracted/decompiled/`.
- Файлы игры в релиз не входят: игрок кладёт свои.

## Структура проекта
| Каталог / файл | Назначение | git |
|---|---|---|
| `port/` | Гостевой ARM32-лоадер (`port/build/ew3`): Bionic ELF loader, thunks, JNI-заглушки Glu/Tapjoy/WWW, перехват сети, GLES wire-протокол | да |
| `apk/` | Android-обёртка (Java: `GameProcess`, `GlBridge`, `MainActivity`, `SettingsActivity`, `Storage`), `build_apk.sh`, `make_sysroot.sh`, `make_icon.py`, `patch_syscalls.py` | да |
| `server/` | Бэкенд (`ew3server.py`, `edge.py`, `cgs*.py`, `bundle_patcher.py`, `generated/`), `requirements-android.txt`, `des_py.py` | да |
| `host/` | Windows: `ew3gl.exe` (GL-мост, работает) и заготовка нативного хоста `ew3host.exe` (не закончен) | да |
| `tools/` | `play_win.sh`, `make_release.sh`, `make_extended.py` (расширенный пакет), `adb`, `release_install.txt`, `release_notes.md`, `build_port.py`, дампы данных и прочее | да |
| `docs/` | `PORTING_GUIDE.md` (как делался порт, части 1–7), `NETWORK.md` (сетевые маршруты и локальная подмена) | да |
| `play_win.cmd` / `play_win.py` | запуск для Windows, не закончен (см. статус) | да |
| `ew3data/` | рабочие данные игры на ПК (OBB, `.so`, `server/players.json`, `server/bundle_cache/`) | нет |
| `release/` | `release/v<версия>/`: файлы для GitHub-релиза (`tools/make_release.sh`) | нет |
| `qemu/` | патчи и скрипт сборки qemu (GPL, прикладываются к релизу) | да |
| `android-sdk/`, `jdk/`, `sdl-arm/`, `third_party/qemu/`, `downloads/`, `apk/build/`, `third_party/`, `extracted/` | копии SDK/JDK/SDL и бинарник qemu (проект самодостаточен), загрузки, сборка APK и ключи подписи, зависимости, декомпиляция | нет |

## Что сделано и работает (2026-10-18)

### 1. Гость (`port/`)
- Загрузчик Bionic ELF, JNI-мост и заглушки SDK (Glu, Tapjoy, AJavaTools, UnityWWW), GLES wire-протокол.
- Проброс `SIGSEGV` из JIT-кода Mono в обработчик `libmono.so` (корректная генерация `NullReferenceException` в C#).
- Исправлен `__fpclassifyf` в `port/thunks/libc/legacy.cpp` (битовые флаги Bionic вместо констант glibc, иначе PhysX 2.8 отвергал матрицы с `0.0f`).
- Перехват сети (`symtab_net.cpp`, `unity_www.cpp`): HTTP на `127.0.0.1:18080`, Gluon TCP на `127.0.0.1:18024` (при `EW3_SERVER`).
- `GC_RETRY_SIGNALS=1` (`main.cpp`): сборщик Boehm повторяет потерянные сигналы остановки потоков под qemu-user.
- `unity_www.cpp`: бандлы, которых нет в OBB (пропатченные, с другим хэшем), берутся из `EW3_BUNDLE_CACHE` или у сервера.

### 1a. Android (`apk/`, релиз v0.2)
- APK: `libqemu.so` (aarch64 qemu-arm, QEMU 11.1.2 + патчи Shadowgun-проекта, приложены к релизу), sysroot armhf (glibc 2.31, SDL2, Python 3.8), гость `ew3`, файлы сервера, Java-обёртка; игра идёт в qemu-user, GLES выполняется на GPU телефона (`GlBridge`).
- Сервер работает на телефоне в том же `libqemu.so` (armhf Python 3.8); зависимости чистый Python: `server/requirements-android.txt` (FastAPI 0.95 + pydantic 1.10) и `server/des_py.py` вместо pycryptodome (сверен на 300 наборах). Данные сервера — в личной папке приложения.
- Файлы игры (APK, cache-zip/OBB, по желанию `.ipa`) игрок кладёт в `/sdcard/BridgeGames/com.jamescrumble.ew3/`; `glu_properties.txt` обёртка расшифровывает из APK сама.
- Профилирование (`PROFILING`) по умолчанию выключено: с ним игра зависала на чёрном экране (0 FPS), `SIGPWR` не доставлялся двум новым потокам Mono (подробно в `docs/PORTING_GUIDE.md`, 7.5). Причина потери сигналов не выяснена.
- Настройки сервера в приложении: доступ из локальной сети (`--host 0.0.0.0`, `/docs` и `/admin` по паролю для чужих клиентов, пароль в настройках и в уведомлении), свой сервер (переключатель и IPv4-адрес). Служба `ServerService` держит сервер в фоне и показывает несмахиваемое уведомление; приложение само запрашивает уведомления и доступ к файлам.
- Extended-пакет (`.ew3x`): готовые 36 бандлов из IPA, `tools/make_extended.py`; с ним IPA не нужен (проверено на телефоне: игра с пакетом работает; сами восстановленные уровни вручную не проверялись).
- Старт сервера на телефоне ~3 с (кэш `.pyc`, готовность по токену `/_ew3/ready`).
- Частота кадров разблокирована: движок больше не привязан к vsync (`vSyncCount` -> 0, `fps_unlock.cpp`), лимит из меню работает (30 даёт 30,0; при 120 в лёгких сценах 84-108, в тяжёлых ~70: упор в процессор, поток движка занят на ~90% ядра).
- Только сенсорное управление; онлайн-режимы, покупки и реклама отключены.
- Релиз: `tools/make_release.sh` -> `release/v0.2/` (APK, расширенный пакет `.ew3x`, `INSTALL.txt`, `RELEASE_NOTES.md`, исходники, патчи qemu, `SHA256SUMS`). Ключ подписи: `apk/build/release.keystore` (копию хранить вне репозитория).

### 1b. Windows
- Игра идёт через `tools/play_win.sh`: гость под `qemu-arm` в WSL, GL-поток по TCP в `ew3gl.exe` (ANGLE -> D3D11, SDL2), управление WASD/мышь переводится в касания (`ew3gl_input.inc`), сервер Python.
- Нативный `ew3host.exe` (dynarmic, свои сисколлы/потоки/сигналы) не написан, см. статус.

### 2. Локальный сервер Gluon + CGS (`server/`)
- **HTTP-сервер (`server/ew3server.py`, порт `:18080`)**:
  - Отдаёт `serverpost_<tag>.json`, `DynamicContentInfo.json`, пропатченный `index.version` и AssetBundle-файлы (из OBB и сконвертированного кэша IPA).
  - Предоставляет Swagger-админку (`/docs`, `/admin/players`) для редактирования сохранений и просмотра логов.
- **Gluon Edge (`server/edge.py`, порт `:18024`)**:
  - Бинарный протокол Gluon поверх TCP + BSON: авторизация клиента, чтение/запись серверных атрибутов профиля (`ew3data/server/players.json`), маршрутизация пакетов `CustomGameServerMessage`.
- **Игровая логика CGS (`server/cgs.py`, `server/cgs_state.py`)**:
  - Автоматическая инициализация стартового профиля для всех 3 классов (`warrior`, `mage`, `monk`) со стартовой экипировкой и предзавершёнными шагами боевого туториала (активные кнопки скиллов со старта).
  - Полный цикл боя (`battle_start`, `battle_end`): генерация сидов и дроп-листов по реальным таблицам `server/generated/game_data.json` (мобы, сундуки, боссы), начисление XP, золота (`<role>_sc_current`), кристаллов (`hc_current`) и предметов.
  - Инвентарь, смена экипировки, пересчёт `gearscore`, продажа предметов, прокачка скиллов (`skill_upgrade`), слияние (`fusion`), эволюция (`evolution`), гача-сундуки (`gacha`), квесты и ежедневные задания (`quest_claim`).

### 3. Патчер бандлов и восстановление контента из iOS IPA v0.1.0 (`server/bundle_patcher.py`)
- Результат сервер кэширует в `bundle_cache/`; тот же кэш, собранный заранее, поставляется отдельным файлом `.ew3x` (см. «Игра»). Кэш помнит, собран ли он с IPA (`.has_ipa`), и пересобирается при смене режима.
- **Патчи базовых бандлов OBB v4.1.0**:
  - `base_uniform_global_manager`: расширен список ежедневных заданий (`QuestListData._dailyQuests`) с одного туториального дейлика на полноценную ротацию из 7 разных ежедневных заданий по дням недели (`4101`–`4107`); удалены отсутствующие на CDN фоновые треки из `SoundTrackData`.
  - `base_uniform_data-levels`: при наличии `31263-Eternity-Warriors-3-v0-1-0.ipa` активируются все **25 уровней кампании** в 3 королевствах (**Moria / Greece**, **Binhai / China**, **Gothia / Gothic**).
- **Бинарный конвертер AssetBundle из Unity 4.2.1f4 (iOS) в Unity 4.6.1p5 (Android)**:
  - Автоматически конвертирует 33 бандла из IPA (`base_char_enemy0`, `base_weapon_monster`, 9 `*_raw` бандлов окружения и 22 сцены уровней):
    - Обновление заголовков `UnityRaw` и `SerializedFile`, перенос флага `m_IsStreamedSceneAssetBundle`.
    - Конвертация бинарных структур классов Unity 4.2 -> 4.6:
      - `Material` (`cid=21`): вставка `m_CustomRenderQueue`, перенаправление внешних ссылок шейдеров/текстур в `base_weapon_monster` на `CAB-base_uniform_shaders` (`fileID=2`).
      - `MeshRenderer` (`cid=23`), `SceneSettings` (`cid=29`), `Mesh` (`cid=43`), `Shader` (`cid=48`, подмена iOS-шейдеров на Android-шейдеры из OBB).
      - `AnimationClip` (`cid=74`): поддержка как `Legacy` (`m_AnimationType=1`), так и `Mecanim` (`m_AnimationType=2`, пересборка `MuscleClip`, `ClipBindingConstant` и полных CRC32-путей костей).
      - `Avatar` (`cid=90`), `AnimatorController` (`cid=91`), `Animator` (`cid=95`), `RenderSettings` (`cid=104`), `Animation` (`cid=111`), `SkinnedMeshRenderer` (`cid=137`), `ParticleSystemRenderer` (`cid=199`).
      - `MonoBehaviour` (`cid=114`): адаптация `EnemySpot`, `TriggerManager`, `UIPanel`, `UIHPController`, `UISprite`, `UILabel`, `AvatarController`.
      - `AssetBundle` (`cid=142`): генерация XML-индекса `TextAsset` (`pathID=999999`) для `Glu.AssetBundles.IndexInfo`, лексикографическая сортировка `m_Container` и сортировка таблицы объектов `SerializedFile::m_Objects` по знаковым 32-битным `pathID` (для корректной работы бинарного поиска `std::lower_bound` в движке Unity).

## Что осталось / дальнейшие планы
- **Android:** проверить прохождение восстановленных уровней из extended-пакета и `.ipa` на телефоне; ускорить эмуляцию, чтобы дойти до 120 кадров/с (конвертация бандлов под qemu на устройстве); выяснить, почему под профилировщиком теряется `SIGPWR`; другие устройства; геймпад.
- **Windows:** нативный `ew3host.exe` на dynarmic (ELF-загрузчик, сисколлы, потоки, сигналы, сокеты, встроенный мост), затем портативный Python с сервером и установщик; до этого можно упаковать схему qemu+WSL (лаунчер, `ew3gl.exe`, rootfs, Python).
- Проверить прохождение остальных восстановленных уровней и боссов (2-й регион Греции, Китай, Готика) по мере открытия кампании и при необходимости допатчить ассеты или скрипты сцен.
- Башня, рейд-боссы, PvP, гильдии — отвечают «недоступно».
