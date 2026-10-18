# Eternity Warriors 3 Bridge (Windows 11): состояние проекта

Цель: запустить Eternity Warriors 3 v4.1.0 (Glu, Android armeabi-v7a) на Windows 11 x64 прослойкой на базе `dynarmic` + `ANGLE` и локальным сервером Gluon/CGS, а также восстановить недостающий CDN-контент (миры, мобы, боссы) из архивной iOS-сборки v0.1.0.

Обновлено: 2026-10-18.

## Игра (`gamebin/` и корень, не в git)
- `E-Warriors-3-v4-1-0.apk`: `lib/armeabi-v7a/{libmain,libmono,libunity}.so`, `classes.dex` + `classes2.dex`
  (SDK Glu, Tapjoy, AWS). Движок в APK — **Unity 4.6.1p5** (`armeabi-v7a`, Mono).
- `E-Warriors-3-v4-1-0-cache.zip` -> `ew3data/Android/obb/com.glu.ewarriors3/main.4100.com.glu.ewarriors3.obb` (90 МБ).
- `31263-Eternity-Warriors-3-v0-1-0.ipa`: архивная iOS-сборка v0.1.0 (Unity 4.2.1f4), содержащая все базовые сцены, окружение, мобов и боссов 3 королевств.
- Managed-DLL лежат в OBB (`assets/bin/Data/Managed/`): `Assembly-CSharp.dll`, `Assembly-CSharp-firstpass.dll`,
  `Photon3Unity3D.dll`, `UnityEngine*.dll`. Декомпилированы в `extracted/decompiled/`.

## Структура проекта
| Каталог / файл | Назначение | git |
|---|---|---|
| `host/` | Windows x64 хост (`ew3host.exe`): `dynarmic` ARM32 JIT, эмуляция Linux-сисколлов/сигналов/потоков, GL-мост через ANGLE, звук и ввод (SDL2) | да |
| `port/` | Гостевой ARM32-лоадер (`port/build/ew3`): Bionic ELF loader, thunks, JNI-заглушки Glu/Tapjoy/WWW, перехват сети и GLES wire-протокол | да |
| `server/` | Локальный бэкенд (`ew3server.py`, `edge.py`, `cgs.py`, `cgs_state.py`, `bundle_patcher.py`, `generated/game_data.json`) | да |
| `play_win.cmd` / `play_win.py` | Скрипт запуска локального сервера и `ew3host.exe` | да |
| `ew3data/` | Рабочие данные игры (OBB, распакованные `.so`, сохранения `ew3data/server/players.json`, кэш бандлов `ew3data/server/bundle_cache/`) | нет |
| `extracted/` | Извлечённые данные OBB и декомпилированный C#-код (`ilspycmd`) | нет |
| `third_party/` | `dynarmic/`, `boost/` (1.86) | нет |

## Что сделано и работает (2026-10-18)

### 1. Windows x64 хост (`host/`, `ew3host.exe`) и ARM32 гость (`port/`)
- Полностью рабочий запуск на Windows 11 x64 через `ew3host.exe` (MSVC + `dynarmic` + `ANGLE` + `SDL2`) без WSL во время игры.
- Поддержка многопоточности (`clone` -> потоки Windows, `futex`, TLS, общие таблицы памяти и `ExclusiveMonitor`), обработка JIT `cacheflush` (`InvalidateCacheRange`).
- Проброс `SIGSEGV` из JIT-кода Mono в обработчик `libmono.so` (корректная генерация `NullReferenceException` в C#).
- Исправлен `__fpclassifyf` в `port/thunks/libc/legacy.cpp` (битовые флаги Bionic вместо констант glibc, иначе PhysX 2.8 отвергал матрицы с `0.0f`).
- Перехват сетевых обращений (`symtab_net.cpp`, `unity_www.cpp`) и перенаправление HTTP на `127.0.0.1:18080` и Gluon TCP на `127.0.0.1:18024`.

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
- Проверить прохождение остальных восстановленных уровней и боссов (2-й регион Греции, Китай, Готика) по мере открытия кампании и при необходимости допатчить специфичные для отдельных сцен ассеты или скрипты.
- По желанию: улучшение управления с клавиатуры/мыши/геймпада и скрытие мобильных элементов HUD.
