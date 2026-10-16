# Eternity Warriors 3 v4.1.0: сетевые маршруты

Источник: декомпиляция `Assembly-CSharp.dll` (`extracted/decompiled/`). Проверено 2026-10-15:
все серверы мертвы (DNS не резолвится, S3-бакет `bjstudio` удалён), в Wayback Machine копий CDN нет.

Подстановки: `{root}` = `http://d2fo9k0pax5pvp.cloudfront.net/ew3` (Global; `GluOnConfig.CloudFront` из serverpost
может его заменить), `{plat}` = `android`, `{cfg}` = `live`, `{tag}` = `EW3_20150403-155116_r28787`
(`BUILD_TAG` из APK).

## Граф

![Сетевые маршруты](network.svg)

Исходник — [network.dot](network.dot) (`dot -Tsvg docs/network.dot -o docs/network.svg`). Тот же граф в Mermaid:

```mermaid
flowchart TD
  boot([AppManager: старт]) --> sel[CheckServerSelection]
  sel --> sp["GET {root}/{plat}/{cfg}/serverpost_{tag}.json?p=ts<br/>таймаут 5 с"]
  sp -- ошибка --> dlgSP[[Диалог IDS_NATIVE_SERVER_POST «Повторить» — БЛОКЕР]]
  sp -- JSON --> chk{BlockerPolicy / ForceUpdate / ServerMaintain}
  chk -- блок/обновление/техработы --> web[[WebView, игра стоит]]
  chk -- ок --> avail[OnServerAvailable]
  avail --> dci["GET {root}/{plat}/{cfg}/bundles/{tag}/DynamicContentInfo.json"]
  dci -- ошибка --> dlgB[[Диалог IDS_NATIVE_SERVER_BANDLE_FAILED — БЛОКЕР]]
  dci -- ок --> idx["GET .../AssetBundles/{AssetBundleTag}/index.version"]
  idx --> bnd["бандлы: base_* из OBB assets/AssetBundles,<br/>остальные миры — с CDN (утеряны)"]
  bnd --> title([Стартовый экран / город])

  title --> gluon["Gluon: HTTP EdgeLB lb.prod.gluon.glu.com:8015/edgeServer<br/>→ TCP gluon-prdedge-1.glu.com:4024"]
  gluon --> cgs["CGS (prd3ew3-maincgs-1.aws.glu.com):<br/>check_version, профиль, сохранения, почта, друзья, лидерборды"]
  title --> photon["Photon TCP: ns.exitgamescloud.com:5058,<br/>app-eu.exitgamescloud.com — PvP, рейды"]

  title -.-> side
  subgraph side [Неблокирующие]
    ops["{root}/{plat}/{cfg}/ops — LiveOps"]
    html["{root}/.../html/serverNews, tournament, shopBanner, cheater"]
    music["{root}/music"]
    iap["bjiap.glu.com/v3/private/i/{v,gt} — IAP"]
    gift["prdags-tc-1.glu.com:8443/gift, :8090"]
    misc["google-analytics, Kontagent, push, geoservice, graph.facebook.com, helpshift"]
  end
  title -.-> java["Java-SDK (Glu, Tapjoy, AWS) — через JNI"]
```

## Выводы для прототипа

1. **До стартового экрана** нужны только два JSON-ответа: `serverpost_{tag}.json` и `DynamicContentInfo.json`,
   плюс `index.version` (копия из OBB). Это крошечный Python-мок (или IL-патч `DoGetServerPost` /
   `GetDynamicContentInfo` на локальные ответы). Точные поля serverpost — в `EW3DownloadManager.cs:994-1210`.
2. **Gluon** — собственный TCP-протокол Glu (`glu.Gluon`, 427 классов сообщений). Профиль и сохранения
   лежат на сервере (CGS). Эмуляция — отдельный большой этап, сейчас отложена. Для прототипа — IL-патч
   `Gluon.AuthenticatePlayer`/`CGS` на офлайн-ответы, когда до этого дойдём.
3. **Photon** — патч IL (онлайн-режимы отключить), как и планировалось.
4. **Контент**: в OBB только базовые миры (город, деревня, greece_1). Остальные миры качались с CDN и,
   судя по всему, утеряны — играбельна только базовая часть, пока не найдётся источник бандлов.
