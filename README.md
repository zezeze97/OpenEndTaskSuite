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

## 任务模板

| 模板 ID | 类型 | 随机参数/任务变化 | 验证来源 | 示例指令 |
|---|---|---|---|---|
| `stay_search_random` | 住宿搜索 | 目的地：巴黎、东京、纽约、伦敦、罗马、曼谷；入住日期：`2026-06-01` 到 `2026-10-31`；晚数：1 到 5；成人：1 到 4 位；儿童：0 到 2 位，年龄 1 到 15 岁；房间：1 或 2 间 | `general_query` / `specific_query` | 在 Booking 里搜索罗马的住宿，入住 2026-07-20，退房 2026-07-25，3 位成人、1 位儿童（1 岁），1 间房。 |
| `stay_search_sort_random` | 住宿搜索 + 排序 | 基础搜索参数 + 排序方式：价格从低到高、住客评分、距离市中心、星级从高到低 | `general_query` / `specific_query` | 在 Booking 里搜索曼谷的住宿，入住 2026-06-29，退房 2026-06-30，3 位成人，1 间房，并把结果按住客评分排序。 |
| `stay_search_business_random` | 住宿搜索 + 出行目的 | 基础搜索参数 + 商务出行标记 | `general_query` / `specific_query` | 在 Booking 里搜索巴黎的住宿，入住 2026-08-13，退房 2026-08-15，4 位成人、1 位儿童（11 岁），1 间房，并把这次住宿标记为商务出行。 |
| `stay_search_saba_filter_random` | 住宿搜索 + 单筛选 | 基础搜索参数 + 一个结果页筛选项：免费取消、包含早餐、评分 8 分以上、酒店、公寓、青旅/旅舍、四星、五星、私人浴室、停车、Wi-Fi、游泳池、空调 | 最新 `mobile.saba` 请求参数 | 在 Booking 里搜索伦敦的住宿，入住 2026-10-12，退房 2026-10-17，1 位成人，2 间房，并在结果页筛选出酒店类型的住宿。 |
| `stay_search_complex_filter_random` | 复杂住宿搜索 | 基础搜索参数 + 2 到 3 个结果页筛选项 + 排序 + 商务出行；筛选项按组采样，避免“四星 + 五星”“酒店 + 公寓”等互斥组合 | `general_query` / `specific_query` + 最新 `mobile.saba` 请求参数 | 在 Booking 里搜索罗马的住宿，入住 2026-07-20，退房 2026-07-25，3 位成人、1 位儿童（1 岁），1 间房，筛选出有空调的住宿、可免费取消的住宿，并按住客评分排序，同时标记为商务出行。 |
| `currency_random` | App 偏好 | 目标币种：EUR、JPY、GBP、AUD、CAD；初始化为 USD | `currency` | 把 Booking 里的货币单位改成加元 CAD。 |
| `language_random` | App 偏好 | 目标语言：西班牙语、法语、德语、意大利语、葡萄牙语；初始化为英语 | `locale` | 把 Booking app 的语言改成葡萄牙语。 |
| `privacy_cookie_random` | 隐私/Cookie | Cookie 类别组合：关闭营销、关闭营销和分析、开启功能和分析但关闭营销、重新开启营销/功能/分析 | `gdpr_settings.xml` 里的 `marketing`、`functional`、`analytical` | 在 Booking 的隐私或 Cookie 设置里只保留必要/功能类 Cookie，关闭营销类和分析类 Cookie。 |
| `booking_permission_random` | Android 权限 | 权限：通知、相机、当前位置、麦克风、日历；动作：关闭或允许 | Android runtime permission 状态 | 关闭 Booking app 的日历权限。 |

## 验证来源

搜索类任务读取 `shared_prefs/com.booking_preferences.xml` 里的 `general_query` 和 `specific_query` JSON。

偏好类任务读取同一个 XML 里的 `currency`、`locale`。

隐私类任务读取 `shared_prefs/gdpr_settings.xml` 里的 `marketing`、`functional`、`analytical`。

权限类任务读取 Android package runtime permission 状态，必要时用 `pm grant`/`pm revoke` 初始化。

随机住宿搜索模板会把目的地、日期、成人数、儿童年龄、房间数等参数采样成一个具体任务。扩展模板还支持排序、商务出行目的，以及通过最新 `cache/saba-http-cache` 中的 `mobile.saba` 请求参数验证结果页筛选项。筛选项按类别分组采样，避免生成“四星 + 五星”或“酒店 + 公寓”这类互斥组合。

## 初始化原则

每个实例初始化到“明确未完成但用户可自然完成”的状态。例如让用户把货币改成 CAD 前，初始化会把 `currency` 设置为 `USD`；让用户做复杂住宿筛选前，初始化会放入另一组不同的搜索参数，并清空 SABA 搜索缓存，避免旧结果页请求污染验证。
