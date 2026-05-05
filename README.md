# OpenEndWorld Booking Task Suite

这个仓库包含一套面向 `OpenEndWorld` 安卓模拟器中 Booking app（`com.booking`）的任务套件。任务都按正常手机用户会说的方式写成中文指令，并且每个任务都有可程序化的初始化和奖励验证。

## 已确认环境

- AVD: `OpenEndWorld`
- adb serial: 通常为 `emulator-5554`
- Booking package: `com.booking`
- 已观察版本: `64.6.0.1`
- app 私有数据可通过 root adb 读取：`/data/user/0/com.booking`

## 文件

- `suites/booking_app_tasks.json`: 任务定义、初始化策略、验证断言、奖励权重。
- `scripts/booking_taskctl.py`: 初始化、验证和列出任务的命令行工具。

## 用法

列出任务：

```bash
python3 scripts/booking_taskctl.py list
```

从随机模板生成一个可复现的任务实例：

```bash
python3 scripts/booking_taskctl.py materialize stay_search_sort_random --seed 42 --id run_sort_42
```

也可以省略 `--seed` 让系统随机生成；生成后的实例会保存到 `.task_state/`，后续用实例 id 初始化和验证：

```bash
python3 scripts/booking_taskctl.py init run_sort_42
python3 scripts/booking_taskctl.py verify run_sort_42
```

初始化单个任务并启动 Booking：

```bash
python3 scripts/booking_taskctl.py init stay_search_paris_family
```

验证并输出奖励：

```bash
python3 scripts/booking_taskctl.py verify stay_search_paris_family
```

指定设备：

```bash
python3 scripts/booking_taskctl.py --serial emulator-5554 verify set_currency_eur
```

## 验证来源

搜索类任务读取 `shared_prefs/com.booking_preferences.xml` 里的 `general_query` 和 `specific_query` JSON。

偏好类任务读取同一个 XML 里的 `currency`、`locale`。

隐私类任务读取 `shared_prefs/gdpr_settings.xml` 里的 `marketing`、`functional`、`analytical`。

权限类任务读取 Android package runtime permission 状态，必要时用 `pm grant`/`pm revoke` 初始化。

随机住宿搜索模板会把目的地、日期、成人数、儿童年龄、房间数等参数采样成一个具体任务。扩展模板还支持排序、商务出行目的，以及通过最新 `cache/saba-http-cache` 中的 `mobile.saba` 请求参数验证结果页筛选项。

## 初始化原则

每个任务初始化到“明确未完成但用户可自然完成”的状态。例如让用户把货币改成 EUR 前，初始化会把 `currency` 设置为 `USD`；让用户搜索巴黎家庭房前，初始化会放入伦敦单人单房的旧搜索。
