# Eternity Warriors 3 Bridge (Windows 11): состояние проекта

Цель: запустить Eternity Warriors 3 v4.1.0 (Glu, Android armeabi-v7a) на Windows 11 x64 той же прослойкой,
что `../shadowgun-probe`, но вместо qemu-user — dynarmic. Сохранить возможность Android-сборки
(qemu + Java-обёртка, как в shadowgun) с пробросом типа устройства.

Обновлено: 2026-10-15.

## Игра (`gamebin/`, не в git)
- `E-Warriors-3-v4-1-0.apk`: `lib/armeabi-v7a/{libmain,libmono,libunity}.so`, `classes.dex` + `classes2.dex`
  (SDK Glu, Tapjoy, AWS).
- `E-Warriors-3-v4-1-0-cache.zip` -> `com.glu.ewarriors3/main.4100.com.glu.ewarriors3.obb` (90 МБ).
- **Unity 4.5.2f1, Mono** (не IL2CPP): managed-DLL лежат в OBB, `assets/bin/Data/Managed/`:
  `Assembly-CSharp.dll` (3 МБ), `Assembly-CSharp-firstpass.dll`, `Photon3Unity3D.dll`, `UnityEngine*.dll`,
  `mscorlib`, `System*`, `Mono.Security`. Распакованы в `extracted/obb/`.
- Сеть: Photon (Photon3Unity3D) + Java-SDK Glu/AWS. Серверы, скорее всего, давно мертвы.

## Окружение
- WSL Ubuntu 20.04 (glibc 2.31), Windows 11 (26200) доступен через interop (`cmd.exe` и `.exe` запускаются).
- Есть: `arm-linux-gnueabihf-g++`, `qemu-arm`, docker, python 3.8.
- На Windows уже стоит: VS 2026 Community (`.../Microsoft Visual Studio/18/Community`, MSVC 14.50 и 14.44,
  `vcvars64.bat`), CMake 4.2.3 и `ninja.exe` из VS (`Common7/IDE/CommonExtensions/Microsoft/CMake/`),
  dotnet SDK 10.0.203 / 8.0.411 (`/mnt/c/Program Files/dotnet/dotnet.exe`).
- llvm-mingw не подходит: его сборки под Ubuntu 22.04 не запускаются на glibc 2.31. Поэтому для Windows
  собираем через MSVC.
- **Правило: ничего не ставить глобально.** Всё лежит в проекте, переменные — `source env.sh`.
  Python — только venv в проекте.

## Структура (как в остальных `*-probe`)
| Каталог | Что | git |
|---|---|---|
| `gamebin/` | APK и cache-zip как скачаны | нет |
| `ew3data/` | рабочие данные игры: `com.glu.ewarriors3/main.4100.com.glu.ewarriors3.obb`, потом `lib/`, `saves/` | нет |
| `extracted/` | извлечённое для анализа: `obb/` (assets из OBB), `decompiled/<сборка>/` (ilspycmd) | нет |
| `dotnet/` | .NET 8 SDK (Linux), `tools/` (ilspycmd 9.1), `home/`, `nuget/` | нет |
| `third_party/` | `dynarmic/` (клон), `boost/` (заголовки 1.86) | нет |
| `downloads/` | исходные архивы (`boost.tar.gz`, `dotnet-install/`) | нет |
| `env.sh` | `EW3_PROBE`, `EW3_GAMEDIR`, `DOTNET_*`, `BOOST_ROOT`, PATH | да |

Код порта появится в `port/` (с `portbase/` и `game/`), утилиты — в `tools/`, документация — в `docs/`.

## Сделано
- `git init` (ветка main, без remote). Пока ничего не закоммичено.
- `third_party/dynarmic` — клон `azahar-emu/dynarmic` (a4660158, 2026-09-26) с сабмодулями
  (fmt, mcl, xbyak, zydis, robin-map и др.).
- `third_party/boost` — заголовки Boost 1.86 (`downloads/boost.tar.gz`, распакован только `boost/`).
- .NET 8 SDK для Linux поставлен в `dotnet/` (`dotnet-install.sh --channel 8.0 --install-dir dotnet --no-path`);
  Windows-dotnet с UNC-путём падал (код 137). ilspycmd 9.1.0.7988 (8.x требует .NET 6):
  `source env.sh && dotnet tool install ilspycmd --version 9.1.0.7988 --tool-path dotnet/tools`.
- Декомпилировано (`ilspycmd -p -o extracted/decompiled/<A> -r <Managed> <A>.dll`):
  Assembly-CSharp (1604 файла, ~201 тыс. строк), Assembly-CSharp-firstpass (214), Photon3Unity3D (40).

## Прототип: стартовый экран (2026-10-15)
Гостевой ARM32-лоадер (`port/`, основа — shadowgun) под qemu-arm в WSL + llvmpipe доходит до **экрана загрузки игры**
(арт EW3, полоса загрузки, подсказка; `scratch/shot_last.png`) и останавливается на диалоге
«Sorry: Failed to Connect to Server [Retry]» (`AppManager.OnServerPostFailedDialog`) — блокер serverpost из `docs/NETWORK.md`.
- Сборка: `./build.sh` -> `port/build/ew3`. Запуск: `tools/run_local.sh [сек]`, лог `logs/local.log`, кадры `ctl/shot_*.bmp`
  (`EW3_SHOT_EVERY`). Данные: `ew3data/{base.apk -> gamebin, lib/armeabi-v7a/*.so, Android/obb/com.glu.ewarriors3/*.obb,
  glu_properties.txt}`. `glu_properties.txt` делает `tools/extract_properties.sh` (AES-ключ из `AJTUtil.GetProperty`).
- Отличия от shadowgun, найденные по дороге:
  - Unity 4.5: `nativeRecreateGfxState(Surface)`, `nativeResize(IIII)`, `nativeSetDefaultDisplay(I)`; размер поверхности
    движок спрашивает через `UnityPlayer.triggerResizeCall()` -> синхронный `nativeResize` (без этого рисовал в 128x128).
  - libunity 4.5 импортирует zlib и `_ZSt7nothrow`/`__cxa_guard_abort` -> `src/symtab_zlib.cpp`.
  - **`__fpclassifyf` возвращал константы glibc** (FP_ZERO=2), а bionic — битовые флаги (FP_ZERO=0x10). PhysX 2.8 проверяет
    `tst r0,#3` и считал каждый 0.0f в матрице позы NaN/Inf -> `NxActorDesc is not valid` -> NULL-актёр -> SIGSEGV.
    Исправлено в `thunks/libc/legacy.cpp`. **Та же ошибка есть в соседних проектах** (общая заготовка thunks).
  - Mono превращает SIGSEGV в JIT-коде в NullReferenceException. Мост `sigaction` глотал обработчики фатальных сигналов;
    теперь обработчик из libmono.so запоминается, и `crash.cpp` отдаёт ему падения вне загруженных модулей (JIT-код).
  - Java-плагины Glu: `jni/glu_plugins.cpp`. `dyn_inert_prefix()` — неизвестные вызовы классов `com/glu/`, `com/tapjoy/`, ...,
    возвращающие объект, получают пустой объект нужного класса (C# бросает исключение на null). `AJTUtil.GetProperty` —
    из `glu_properties.txt`, `GetDeviceLanguage` -> "en", `AJTUI.ShowAlert` — в лог.
- Отладка: `EW3_TRAP_AT=<hex>[,<hex>...]` ставит `udf` в libunity, отчёт о падении печатает r4-r11 и память по ним.

## Не доделано
- **Windows-хост (приоритет)**: `ew3host.exe` на dynarmic + GL-мост на ANGLE, исполняющий тот же `port/build/ew3`.
  Сборка dynarmic через MSVC из WSL ещё не проверялась.
- Дальше старта: ответ на serverpost и `DynamicContentInfo.json` (локальные файлы через `jni/unity_www.cpp` или мок),
  затем Gluon/CGS (логин, сохранения) — см. `docs/NETWORK.md`.
- Разобрать декомпилированный код: сетевые точки (Photon, HTTP/WWW, Glu SDK) -> окончательный план сервера.
- Сборка MSVC+Ninja из UNC-пути `\\wsl.localhost\Ubuntu-20.04\...` ещё не проверена. Если будет медленно или
  сломается, держать build-каталог на диске Windows.

## Архитектура (план)
```
 ew3host.exe (Windows x64, MSVC)                         гостевой ARM32 Linux-процесс
 ┌──────────────────────────────────────┐            ┌────────────────────────────────────┐
 │ linux-user на dynarmic:              │            │ порт-лоадер из shadowgun (glibc armhf)│
 │  ELF + ld-linux, syscalls ARM EABI   │  syscalls  │  bionic ELF loader                 │
 │  mmap/futex/clone(=поток Windows)    │ ◄────────► │  libunity / libmono / libmain      │
 │  сигналы (GC Mono, SIGSEGV null-ref) │            │  dyn JNI, Android API на заглушках │
 │  cacheflush -> InvalidateCacheRange  │            │  gl_bridge: тот же wire-протокол   │
 │ host-мост: GLES -> ANGLE, звук, ввод │ ◄─ pipe ── │                                    │
 └──────────────────────────────────────┘            └────────────────────────────────────┘
```
- Гостевая часть (лоадер, thunks, JNI, gl_bridge) общая с Android-сборкой. Хост-слой сменный:
  `windows` (dynarmic + C++-порт GlBridge.java на ANGLE) | `android` (qemu + Java-обёртка из shadowgun).
- Тип устройства пробрасывается через JNI-обработчики (`Build.*`, Display), чтобы игра видела нужное устройство.
- dynarmic: один Jit на поток, общий fastmem на 4 ГБ, общий ExclusiveMonitor; инвалидация кэша рассылается
  всем потокам. Mono генерирует код в рантайме и зовёт `cacheflush` (ARM syscall 0xf0002). Для точного PC
  при SIGSEGV (null-ref в Mono) — `check_halt_on_memory_access` + `HaltReason::MemoryAbort`,
  запасной вариант — `MONO_DEBUG=explicit-null-checks`.
- GLES на Windows: ANGLE (`libEGL.dll`/`libGLESv2.dll`, можно скопировать из Edge/Chrome в проект).
- Отладка гостевой части: сначала под `qemu-arm` в WSL + llvmpipe (как `tools/run_local.sh` в shadowgun),
  чтобы отделять баги порта от багов эмулятора.
- Unity 4.5 `UnityPlayer` (порядок натив-вызовов) отличается от 5.3: снять заново из `classes.dex`
  (`dexdump`, `tools/dexclass.py` из shadowgun).

## Сервер (план)
Гибрид, окончательно решается после декомпиляции `Assembly-CSharp.dll`:
1. HTTP(S)-запросы (Glu/AWS, конфиги, сохранения, магазин) — мок-сервер на Python (локальный venv).
   Адреса подменить в DLL или через `UnityEngine.WWW` в порте (`jni/unity_www.cpp`) и хост-резолвер.
2. Photon (бинарный протокол, мультиплеер) — эмулировать нецелесообразно: патч IL (dnlib/Mono.Cecil,
   локальный NuGet) в копии `Assembly-CSharp.dll` внутри копии OBB, чтобы онлайн-методы сразу возвращали
   «успех/офлайн».
3. Java-SDK Glu (логин, IAP, реклама) — заглушки в dyn JNI порта, как плагины в shadowgun.

## Управление
Отложено (по просьбе пользователя). Потом: убрать мобильный UI на ПК, описать схему клавиатура/мышь/геймпад.
