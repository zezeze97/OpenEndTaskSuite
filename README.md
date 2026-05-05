# OpenEndWorld Booking Task Suite

这个仓库包含一套面向 `OpenEndWorld` 安卓模拟器中 Booking app（`com.booking`）的任务模板。模板会先随机生成一个具体任务实例，实例里的中文指令符合正常手机用户表达方式，并且每个实例都有可程序化的初始化和奖励验证。

## 已确认环境

- AVD: `OpenEndWorld`
- adb serial: 通常为 `emulator-5554`
- Booking package: `com.booking`
- 已观察版本: `64.6.0.1`
- app 私有数据可通过 root adb 读取：`/data/user/0/com.booking`

## 文件

- `suites/booking_app_tasks.json`: 模板定义、采样空间、初始化策略、验证断言、奖励权重。
- `scripts/booking_taskctl.py`: 生成实例、初始化、验证和列出模板的命令行工具。

## 用法

列出模板：

```bash
python3 scripts/booking_taskctl.py list
```

从模板生成一个可复现的任务实例：

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
python3 scripts/booking_taskctl.py init run_sort_42
```

验证并输出奖励：

```bash
python3 scripts/booking_taskctl.py verify run_sort_42
```

指定设备：

```bash
python3 scripts/booking_taskctl.py --serial emulator-5554 verify run_sort_42
```

当前模板包括：

- `stay_search_random`: 随机目的地、日期、成人数、儿童年龄和房间数。
- `stay_search_sort_random`: 基础搜索 + 随机排序。
- `stay_search_business_random`: 基础搜索 + 商务出行目的。
- `stay_search_saba_filter_random`: 基础搜索 + 单个结果页筛选项。
- `stay_search_complex_filter_random`: 基础搜索 + 2 到 3 个结果页筛选项 + 排序 + 商务出行。
- `currency_random`: 随机切换 Booking 货币。
- `language_random`: 随机切换 Booking app 语言。
- `privacy_cookie_random`: 随机调整隐私/Cookie 类别。
- `booking_permission_random`: 随机调整 Booking 的 Android 权限。

## 验证来源

搜索类任务读取 `shared_prefs/com.booking_preferences.xml` 里的 `general_query` 和 `specific_query` JSON。

偏好类任务读取同一个 XML 里的 `currency`、`locale`。

隐私类任务读取 `shared_prefs/gdpr_settings.xml` 里的 `marketing`、`functional`、`analytical`。

权限类任务读取 Android package runtime permission 状态，必要时用 `pm grant`/`pm revoke` 初始化。

随机住宿搜索模板会把目的地、日期、成人数、儿童年龄、房间数等参数采样成一个具体任务。扩展模板还支持排序、商务出行目的，以及通过最新 `cache/saba-http-cache` 中的 `mobile.saba` 请求参数验证结果页筛选项。筛选项按类别分组采样，避免生成“四星 + 五星”或“酒店 + 公寓”这类互斥组合。

## 初始化原则

每个实例初始化到“明确未完成但用户可自然完成”的状态。例如让用户把货币改成 CAD 前，初始化会把 `currency` 设置为 `USD`；让用户做复杂住宿筛选前，初始化会放入另一组不同的搜索参数，并清空 SABA 搜索缓存，避免旧结果页请求污染验证。
