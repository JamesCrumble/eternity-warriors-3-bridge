# Как делался Eternity Warriors 3 Bridge: разбор по шагам

ETERNITY WARRIORS 3 4.1.0 (Glu) — игра на Unity 4.5.2 с кодом на Mono. От остальных проектов семейства она
отличается двумя вещами. Во-первых, это онлайн-игра: экипировку, валюты и награды считал сервер Glu, а серверов
давно нет — без своего сервера игра не проходит дальше экрана загрузки. Во-вторых, целевых платформ две: Windows
(графика на видеокарту ПК через ANGLE, части 2–6) и Android-телефон (Bridge-APK, часть 7).

Каждый шаг описан одинаково: что было видно, как нашли причину, что и где исправили. Текущее состояние —
в [PROJECT_STATE.md](../PROJECT_STATE.md), сетевой протокол — в [NETWORK.md](NETWORK.md).

Состояние: меню, выбор героя, город, вход в сюжетные уровни, бой; звук; 60 кадров/с на RX 9070 XT при 720p
(процессор эмулирует qemu-arm в WSL). Android: релиз v0.1, около 60 кадров/с на OnePlus CPH2723 (Adreno 830).

## Почему не пересобрать под x86 или arm64

- **Unity 4.5.2f1, Mono.** Управляемые DLL лежат в OBB (`assets/bin/Data/Managed/`), но движок — только
  `libunity.so` под ARM32. Пересобрать его нельзя.
- Библиотеки только `armeabi-v7a`: `libmain.so`, `libmono.so`, `libunity.so`.

Поэтому схема та же, что в Shadowgun: ARM32-порт исполняет движок, а платформу (Android API, GL, звук, ввод)
подставляет порт.

## Часть 1. Каркас

Каркас — из Shadowgun Bridge ([port/](../port)): загрузчик bionic ELF, thunks libc, динамический JNI.

### 1.1. Порядок вызовов Unity 4.5

- **Видно:** движок рисовал в окно 128×128 и не реагировал на размер экрана.
- **Причина:** в Unity 4.5 другой `UnityPlayer`: `nativeRecreateGfxState(Surface)`, `nativeResize(IIII)`,
  `nativeSetDefaultDisplay(I)`, а размер поверхности движок спрашивает через `UnityPlayer.triggerResizeCall()`.
- **Исправлено:** [main.cpp](../port/src/main.cpp) вызывает их в порядке из `classes.dex` (`tools/dexclass.py`),
  `triggerResizeCall` — синхронный `nativeResize`.

### 1.2. `__fpclassifyf` и PhysX

- **Видно:** `NxActorDesc is not valid`, затем SIGSEGV на NULL-актёре.
- **Причина:** `__fpclassifyf` возвращал константы glibc (FP_ZERO = 2), а bionic — битовые флаги (FP_ZERO = 0x10).
  PhysX 2.8 проверяет `tst r0, #3` и считал каждый 0.0f в позе NaN.
- **Исправлено:** `thunks/libc/legacy.cpp`. **Та же ошибка есть в соседних проектах** (общая заготовка thunks).

### 1.3. Mono и SIGSEGV

- **Видно:** обращение по null в C# роняло процесс вместо `NullReferenceException`.
- **Причина:** мост `sigaction` глотал обработчики фатальных сигналов.
- **Исправлено:** обработчик из `libmono.so` запоминается, [crash.cpp](../port/src/crash.cpp) отдаёт ему падения
  вне загруженных модулей (JIT-код).

### 1.4. Плагины Glu

- `jni/glu_plugins.cpp`: неизвестные вызовы `com/glu/`, `com/tapjoy/`… с объектом в результате получают пустой
  объект нужного класса — C# бросает исключение на null. `AJTUtil.GetProperty` читает `glu_properties.txt`
  (`tools/extract_properties.sh` достаёт AES-ключ).

## Часть 2. Графика на видеокарте Windows

### 2.1. WSLg не даёт GPU

- **Видно:** в WSL рисует llvmpipe.
- **Как проверили:** `build/ew3gl` пишет `GL_RENDERER`. Видеокарта видна (`/dev/dxg`, `libd3d12.so`), но
  `GALLIUM_DRIVER=d3d12` даёт `failed to create dri screen`: Mesa 21.2.6 из Ubuntu 20.04 слишком стара.
- **Решение:** рисовать в Windows-процессе.

### 2.2. GL-мост на ANGLE

- Гостевой [gl_bridge.cpp](../port/src/gl_bridge.cpp) сериализует вызовы GLES в поток; хост
  [host/glbridge/ew3gl.c](../host/glbridge/ew3gl.c) — C-порт `GlBridge.java` из Shadowgun — проигрывает его на
  ANGLE (Direct3D 11). Модули по ~200 строк: транспорт, разбор, окно, объекты, отрисовка, запросы, статистика.
- **Транспорт:** гость слушает TCP (`EW3_GL_LISTEN`), `ew3gl.exe` подключается через localhost-форвардинг WSL —
  файрволу нечего блокировать.
- **ANGLE:** берётся из OBS ([tools/angle_setup.sh](../tools/angle_setup.sh)): сборка Chromium, только системные
  DLL. ANGLE из Firefox требует `mozglue.dll`. Библиотека импорта делается из `.def` (экспорты через `dumpbin`).
- **Тонкость SDL2 под Windows:** атрибуты GLES (профиль ES, версия) надо задать **до** `SDL_CreateWindow`.
  Иначе окно готовится под WGL, контекст EGL не становится текущим, `glGetString` возвращает NULL.

### 2.3. Качество графики по имени GPU

- **Видно:** низкое качество, `Level is 1`.
- **Причина:** `AndroidQualitySettings` выбирает уровень по `SystemInfo.graphicsDeviceName`. Строка ANGLE ему
  незнакома — Tier_1.
- **Решение:** `EW3_GPU=adreno|mali|powervr|tegra|real` в [play_win.sh](../tools/play_win.sh) подменяет
  `GL_RENDERER` для игры. По умолчанию `Adreno (TM) 420` — Tier_5 (`Level is 3`).

### 2.4. Счётчик кадров и снимки

- `ew3gl_hud.inc`: цифры прямоугольниками `glScissor` + `glClear` — без своих шейдеров, пять пунктов состояния
  GL сохраняются и восстанавливаются. F2 — вкл/выкл.
- `ew3gl_shot.inc`: F12 или `touch ctl/shot` — кадр в `ctl/ew3gl_shot.bmp`.

## Часть 3. Частота кадров

### 3.1. Разблокировка зависала на кадре 60

- **Видно:** с разблокировкой игра замерзала, все потоки в futex.
- **Как нашли:** `tools/thread_dump.sh` — в логе `[F/mono] Assertion at mini-arm.c:2644, condition
  'thumb_supported' not met`, затем `abort()`.
- **Причина:** замена `set_targetFrameRate` становится icall Mono. Порт собран в Thumb, а Mono решает, есть ли
  Thumb, по `/proc/cpuinfo` — под qemu-user это cpuinfo x86.
- **Исправлено:** [fps_unlock.cpp](../port/src/fps_unlock.cpp) — `__attribute__((target("arm")))`. Перехват
  `mono_add_internal_call` стоит в `so_resolve_link`: libunity 4.x берёт его из импортов, не через `dlsym`.

### 3.2. Потолок 60

Остаётся 60 кадров/с при `ew3gl` занятом на 5%: ограничение внутри движка/эмуляции. Отложено.

## Часть 4. Звук

- **Видно:** тишина; `libpulse` в процесс не загружена.
- **Как нашли:** `EW3_JNI_TRACE=1` показал поиск `UnityPlayer.restartFMODAudioDevice()` без обработчика.
- **Причина:** в Unity 4.x звук выводит Java-класс `org.fmod.FMODAudioDevice` (поток, который зовёт
  `fmodGetInfo`/`fmodProcess` из libunity). Запускает его Java-`UnityPlayer.resume()`; у Unity 5 это делала
  обёртка, здесь — некому.
- **Исправлено:** [fmod_audio.cpp](../port/jni/fmod_audio.cpp) — порт сам стартует устройство после
  `nativeResume`, обрабатывает `restartFMODAudioDevice`; поток ждёт, пока `fmodGetInfo` перестанет возвращать
  -1. Переключатель `EW3_FMOD_DEVICE=0`.
- **Музыка** скачивалась с CDN Glu (`…/ew3/music/*.mp3`) и утеряна; эффекты лежат в `resources.assets`.

## Часть 5. Сервер

Сервер — Python ([server/](../server)): HTTP-заглушки CDN и Gluon edge (BSON, `server/edge.py`), игровая логика —
CGS (`server/cgs*.py`). Правило для всех ответов: блокирующий запрос ставит обработчик в очередь, и если разбор
ответа бросит исключение, `SendACK` не придёт — экран «Accessing Network» навсегда. Поэтому каждый ответ
повторяет форму, которую читает обработчик клиента, а недоступное отвечает числовым `errorCode`
(путь `GluonCGSManager` приводит его `(int)(double)`).

### 5.1. Карта запросов

79 пар `messageType`/`op_type` найдены в трёх видах: `Hashtable.Add("messageType", …)`, JSON-строки
с экранированными кавычками и `CGSMessage.addParam` в `GluonCGSManager`. Обработчик ответа — по имени колбэка.

### 5.2. Сервер был авторитетным

`GameManager.ParseCommonReward` принимает от сервера `sc_current`, `hc_current`, `exp`, `items`… Клиент сам
сохраняет только свои атрибуты (`*_basic`, квесты, `account_shared`); валюты, опыт, инвентарь ведёт сервер
([cgs_state.py](../server/cgs_state.py)). Отчёт о бое (`battle_end`) клиент шифрует DES-CBC, ключ и IV
`ew3gluww` (`Utils._keyBytes`); заработанное считает сам — сервер записывает и возвращает итог.

### 5.3. Нет топора, чёрный герой, вазы не бьются

- **Причина:** стартовую экипировку создавал сервер Glu на `account_profile/CreateDefault`; клиентский
  `CreateDefaultProfiles` в 4.1.0 не вызывается. Пустой инвентарь — нет оружия (нет урона), нет брони (атлас
  `ModifiableMaterialBuilder` чёрный).
- **Исправлено:** `STARTER` в [cgs.py](../server/cgs.py) — списки `_defaultEquipment_*`/`_defaultItems_*`
  из ассета `InitInformation` (бандл `base_uniform_global_manager`; строки + int32 после строк).

### 5.4. Экран выбора героя падал каждый кадр

- **Видно:** `NullReferenceException` в `BackKeyManager.Pop` из `CharacterSelector.ShowSelection`.
- **Причина:** с героями без `_used` путь «выбор из трёх» — и там `Pop` с непустым стеком;
  `MethodBase.GetCurrentMethod()` под этим Mono, похоже, возвращает null.
- **Обход:** воин помечен использованным (`warrior_basic._used`). Сама ошибка не исправлена.

### 5.5. «Accessing Network» перед сюжетом

- `get_cgs_name`: `LiveOpsManager` без проверки читает `remain_maintain_time` и `closed_service`; пустой ответ
  убивал корутину с `IsUpdatingLiveOpsData = true`.
- `battle_enter`: со стоимостью в энергии `UIEnterLevel` ищет счётчик энергии и падает на null. Без
  `Normal`/`Hard` уровень бесплатный, кнопка обычная.

## Часть 6. Управление на ПК

Игра знает только касания: плавающий джойстик слева, кнопки справа. [ew3gl_input.inc](../host/glbridge/ew3gl_input.inc)
переводит WASD/мышь/клавиши в касания (мультитач). Это хост, игра и порт не меняются, Android-сборка
([часть 7](#часть-7-android-bridge-apk)) не затронута. `EW3_GL_KEYMAP=0` выключает, F1 — режим мыши, `ctl/keymap.txt` — координаты кнопок.
Джойстик ставится через пару кадров после касания, иначе центр окажется в смещённой точке.
Стик рисует сама игра, убрать его без изменения игры нельзя — точка касания в углу экрана.

## Часть 7. Android: Bridge-APK

Схема та же, что у Shadowgun: APK несёт свой qemu-user, 32-битная игра исполняется в нём, а OpenGL ES идёт
на GPU телефона. Обёртка взята из `../shadowgun-probe` и переделана под EW3 ([apk/](../apk)).

В APK: `lib/arm64-v8a/libqemu.so` (статический aarch64 `qemu-arm`, QEMU 11.1.2 + патчи Shadowgun-проекта; патчи
прикладываются к релизу), `assets/sysroot.zip` (armhf: glibc 2.31, SDL2, Python 3.8), `assets/ew3` (гость,
`port/build/ew3`), `assets/serverroot.zip` (файлы сервера) и Java-код `apk/src/com/jamescrumble/ew3/`:
`GameProcess` (подготовка файлов, запуск сервера и гостя, команды, звук), `GlBridge` (GLES-вызовы на GPU),
`MainActivity`, `SettingsActivity`, `Storage`. Протокол GL тот же, что у `ew3gl`: наборы опкодов гостя и Java
совпадают (38 штук), поэтому Java-мост от Shadowgun подошёл без изменений протокола.

### 7.1. Сборка

```bash
./build.sh                 # гость port/build/ew3
bash apk/make_sysroot.sh   # sysroot + serverroot (нужны downloads/armhf/debs и wheels-android)
bash apk/build_apk.sh      # Eternity-Warriors-3-Bridge-debug.apk
tools/make_release.sh      # release/v<версия>/: подписанный APK, INSTALL.txt, RELEASE_NOTES.md, src, SHA256SUMS
```

`libqemu.so` берётся из `../shadowgun-probe/qemu/out/qemu-arm-E.stripped` (`QEMU_BIN` меняет путь);
`patch_syscalls.py` переписывает в нём `set_robust_list`/`rseq`/`faccessat2` под seccomp-фильтр Android.
`jdk/` и `android-sdk/` — симлинки на соседний проект. Debian-пакеты Python (`downloads/armhf/debs`) и
чистые колёса (`downloads/armhf/wheels-android`, `pip download --no-deps --platform any -r server/requirements-android.txt`)
лежат вне git.

### 7.2. Раскладка данных на телефоне

- **Видно:** без файлов игры приложение пишет «Не найден оригинальный APK игры».
- **Решение:** игрок кладёт `.apk`, cache-`.zip` (или `main.*.obb`) и, по желанию, `.ipa` в
  `/sdcard/BridgeGames/com.jamescrumble.ew3/` (нужен доступ ко всем файлам) или в `Android/data/<пакет>/files/`.
  Приложение собирает из них `files/game/` в том виде, как ждёт порт: `lib/armeabi-v7a/{libmain,libmono,libunity}.so`,
  `base.apk`, `Android/obb/com.glu.ewarriors3/main.*.obb`.
- `glu_properties.txt` (его читает `AJTUtil.GetProperty`) обёртка делает сама: `res/raw/properties.dat` из APK
  расшифровывается AES-128-CBC, ключ и IV лежат в `classes.dex` по смещениям `0x301c68` и `0x301c80`
  (`GameProcess.writeGluProperties`, то же, что `tools/extract_properties.sh`; результат проверен побайтно).

### 7.3. Сервер на телефоне

- **Требование:** сервер остаётся Python, но у `pydantic-core` и `pycryptodome` нет колёс под armv7.
- **Решение:** в sysroot лежит armhf Python 3.8 из Ubuntu 20.04, и он запускается в том же `libqemu.so`
  (`-cpu cortex-a15 -B 0x100000000 -L sysroot`, `PYTHONHOME=/usr`). Зависимости — чистый Python:
  [requirements-android.txt](../server/requirements-android.txt) (FastAPI 0.95 + pydantic 1.10), а DES-CBC для отчёта
  боя даёт [des_py.py](../server/des_py.py), к которому [cgs_state.py](../server/cgs_state.py) переходит, если
  `Crypto` не импортируется (результат сверен с pycryptodome на 300 случайных наборах).
- Сервер стартует около 20 секунд на ПК. `GameProcess.startServer` ждёт ответа `:18080` до трёх минут и только
  потом запускает игру (`EW3_SERVER=127.0.0.1`). Для сокетов на loopback приложению нужно разрешение `INTERNET`.
- Данные сервера (`players.json`, `bundle_cache/`) — в личной папке приложения, `files/serverdata/`. Они пропадают
  вместе с приложением.
- **Ловушка:** первая сборка sysroot пропустила `libutil.so.1`, потому что тест на ПК прошёл: qemu на хосте
  подхватил библиотеку из системы. Теперь `make_sysroot.sh` обходит `NEEDED` у `python3.8` и всех модулей
  `lib-dynload` и падает, если чего-то нет.

### 7.4. Бандлы из кэша

- **Видно:** в логе `WWW jar:…obb!/assets/AssetBundles/base_uniform_global_manager_<хэш>… -> not found`.
- **Причина:** пропатченные бандлы имеют другой хэш в имени, чем в OBB, и там их нет.
- **Исправлено:** `read_zip_entry` в [unity_www.cpp](../port/jni/unity_www.cpp) после промаха ищет файл в
  `EW3_BUNDLE_CACHE`, а затем просит его у сервера. Сервер пишет подготовленные бандлы в тот же каталог
  (`EW3_BUNDLE_CACHE`, по умолчанию `<data>/bundle_cache`).

### 7.5. Чёрный экран и 0 FPS

- **Видно:** загрузка доходит до конца, счётчик в `status.json` (`frame=`) встаёт на 60, 90 или 150, экран чёрный
  с «0.0 FPS», приложение в фокусе. В конце кадра сервер видит только `client connected` от Gluon.
- **Как нашли:** профилировщик показал, что поток движка всё время в `mono_unity_liveness_stop_gc_world`, внутри —
  цикл `nanosleep`: Unity остановил мир сборщика мусора Boehm и ждёт подтверждений. Обёртка читает дополнительные
  аргументы qemu из `qemu_args.txt`, с `-strace` в логе видно: `SIGPWR` (остановка потока) отправлен двум только что
  созданным потокам Mono около 1300 раз каждому и ни разу не доставлен, остальные потоки спят в `rt_sigsuspend`.
  `GC_RETRY_SIGNALS` ([main.cpp](../port/src/main.cpp), потерянный сигнал остановки) этот случай не закрывает.
- **Причина:** включённый отладочный профилировщик (`EW3_PC_PROF`, настройка `PROFILING`): он шлёт потоку движка
  `SIGPROF` 250 раз в секунду. Без него два запуска подряд (100 и 120 секунд) шли на ~60 кадрах/с без зависаний.
  Точный механизм, по которому сигналы теряются у новых потоков, не выяснен.
- **Исправлено:** `PROFILING` по умолчанию выключен ([GameProcess.java](../apk/src/com/jamescrumble/ew3/GameProcess.java)),
  в настройках подписано, что он может подвесить игру.

### 7.6. Остальное

- Закрепление на «быстрых ядрах» (`CPU_PRIME`, маска `c0`) подходило только OnePlus, поэтому по умолчанию выключено.
- Иконка приложения — нейтральная, её рисует `apk/make_icon.py`: материалы игры в релиз не входят.
- Порт принимает от обёртки только `touch`, `key`, `pause`, `resume`, `quit`, поэтому управление сенсорное;
  статус содержит `state` и `frame` (поля `menu` нет, обёртка выходит с экрана загрузки по числу кадров).
- Релиз: `tools/make_release.sh` кладёт в `release/v<версия>/` APK (подпись release-ключом `apk/build/release.keystore`,
  пароль в `apk/build/release.pass`; оба вне git, копию надо хранить), архив исходников рабочего дерева,
  `qemu-patches.zip`, `INSTALL.txt`, `RELEASE_NOTES.md` и `SHA256SUMS`. Тег `v0.1` указывает на коммит, из которого
  собран этот релиз.

## Что осталось

- Данные игры для сервера: магазин, продажа, слияние, эволюция, руны, рулетка (бесплатно), квесты — таблицы
  `StoreDataConfig`, `GachaItemList`, `FusionList`… лежат в бандлах без typetree, нужен декодер по C#-классам.
- Башня, рейд-боссы, PvP, гильдии — отвечают «недоступно».
- `MethodBase.GetCurrentMethod()` под Mono (5.4).
- Потолок 60 кадров/с.
- Свой exe для Windows: эмулятор Linux-процесса на dynarmic вместо qemu (`host/src/` пока только привязка dynarmic
  и память, без `main`, ELF-загрузчика, сисколлов, потоков и сокетов), сервер на портативном Python, упаковка,
  меню настроек (окно / без рамки / полный экран).
- Android: уровни из `.ipa` на телефоне не проверялись; причина потери `SIGPWR` (7.5); геймпад.
