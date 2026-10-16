# Как делался Eternity Warriors 3 Bridge: разбор по шагам

ETERNITY WARRIORS 3 4.1.0 (Glu) — игра на Unity 4.5.2 с кодом на Mono. От остальных проектов семейства она
отличается двумя вещами. Во-первых, это онлайн-игра: экипировку, валюты и награды считал сервер Glu, а серверов
давно нет — без своего сервера игра не проходит дальше экрана загрузки. Во-вторых, целевая платформа — Windows:
графика идёт на видеокарту ПК через ANGLE, а не на телефон.

Каждый шаг описан одинаково: что было видно, как нашли причину, что и где исправили. Текущее состояние —
в [PROJECT_STATE.md](../PROJECT_STATE.md), сетевой протокол — в [NETWORK.md](NETWORK.md).

Состояние: меню, выбор героя, город, вход в сюжетные уровни, бой; звук; 60 кадров/с на RX 9070 XT при 720p
(процессор эмулирует qemu-arm в WSL).

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
переводит WASD/мышь/клавиши в касания (мультитач). Это хост, игра и порт не меняются, Android-сборка не
затронута. `EW3_GL_KEYMAP=0` выключает, F1 — режим мыши, `ctl/keymap.txt` — координаты кнопок.
Джойстик ставится через пару кадров после касания, иначе центр окажется в смещённой точке.
Стик рисует сама игра, убрать его без изменения игры нельзя — точка касания в углу экрана.

## Что осталось

- Данные игры для сервера: магазин, продажа, слияние, эволюция, руны, рулетка (бесплатно), квесты — таблицы
  `StoreDataConfig`, `GachaItemList`, `FusionList`… лежат в бандлах без typetree, нужен декодер по C#-классам.
- Башня, рейд-боссы, PvP, гильдии — отвечают «недоступно».
- `MethodBase.GetCurrentMethod()` под Mono (5.4).
- Потолок 60 кадров/с.
- Свой exe: эмулятор Linux-процесса на dynarmic вместо qemu, сервер на портативном Python, упаковка,
  меню настроек (окно / без рамки / полный экран).
