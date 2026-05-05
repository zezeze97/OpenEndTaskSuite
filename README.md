# OpenEndWorld Android Task Suites

这个仓库包含面向 `OpenEndWorld` 安卓模拟器的可验证任务模板。模板会先随机生成一个具体任务实例，实例里的中文指令符合正常手机用户表达方式，并且每个实例都有可程序化的初始化和奖励验证。

## 已确认环境

- AVD: `OpenEndWorld`
- adb serial: 通常为 `emulator-5554`
- Booking package: `com.booking`，已观察版本 `64.6.0.1`
- 高德地图 package: `com.autonavi.minimap`，已观察版本 `16.13.7.2010`
- app 私有数据可通过 root adb 读取，例如 `/data/user/0/com.booking` 和 `/data/user/0/com.autonavi.minimap`

## 文件

- `suites/booking_app_tasks.json`: Booking 模板定义、采样空间、初始化策略、验证断言、奖励权重。
- `scripts/booking_taskctl.py`: Booking 生成实例、初始化、验证和列出模板的命令行工具。
- `suites/amap_app_tasks.json`: 高德地图模板定义、采样空间、初始化策略、验证断言、奖励权重。
- `scripts/amap_taskctl.py`: 高德地图生成实例、初始化、验证和列出模板的命令行工具。

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

高德地图任务同样使用 `list`、`materialize`、`init`、`verify`：

```bash
python3 scripts/amap_taskctl.py list
python3 scripts/amap_taskctl.py materialize amap_saved_point_random --seed 7 --id amap_point_7
python3 scripts/amap_taskctl.py init amap_point_7
python3 scripts/amap_taskctl.py verify amap_point_7
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

## 高德地图任务模板

| 模板 ID | 类型 | 随机参数/任务变化 | 验证来源 | 示例指令 |
|---|---|---|---|---|
| `amap_map_text_size_random` | 地图显示偏好 | 地图文字大小：小号、标准、大号；初始化为不同大小 | `MapTextSizeSet.xml` 里的 `map_text_size` | 把高德地图里的地图文字大小改成大号。 |
| `amap_language_random` | App 语言偏好 | 语言选项：跟随系统、中文、英文；初始化为不同选项 | `appLanguage.xml` 里的 `language_switch_option` | 把高德地图的语言设置改成英文。 |
| `amap_layer_toggle_random` | 地图图层 | 图层：景区手绘图、精品景区、水体环境、天气地图；动作：打开或关闭 | `SP_NAME_layer_checked.xml` 里对应图层 ID 的 boolean | 在高德地图的图层设置里打开天气地图图层。 |
| `amap_push_setting_random` | App 内通知设置 | 消息推送：开启或关闭；初始化为相反状态 | `push_state.xml` 里的 `push_setting` | 在高德地图的设置里关闭消息推送。 |
| `amap_permission_random` | Android 权限 | 权限：精确位置、相机、麦克风、通知；动作：允许或关闭 | Android runtime permission 状态 | 允许高德地图的精确位置权限。 |
| `amap_saved_point_random` | 收藏地点 | 地点：北京南站、上海虹桥站、广州塔、西湖 | `aMap.db` 的 `SAVE_POINT` 表 | 在高德地图里搜索西湖，并把它收藏起来。 |
| `amap_route_history_random` | 路线规划 | 起终点组合 + 路线方式：驾车、步行、公交 | `aMap.db` 的 `RouteHistory` 表 | 在高德地图里规划从上海虹桥站到外滩的驾车路线。 |
| `amap_saved_route_random` | 保存路线 | 起终点组合 + 路线方式：驾车、步行 | `aMap.db` 的 `SAVE_ROUTE` 表 | 在高德地图里规划从广州塔到广州东站的步行路线，并把这条路线保存起来。 |
| `amap_route_with_via_random` | 带途经点路线规划 | 起点、终点、途经点组合 + 路线方式：驾车、步行 | `aMap.db` 的 `RouteHistory` 表 | 在高德地图里规划从上海虹桥站到外滩的驾车路线，并添加人民广场作为途经点。 |
| `amap_start_navigation_random` | 开始导航 | 目的地：天安门、外滩、广州东站、杭州东站；方式：驾车、步行 | `aMap.db` 的 `NAVI_HISTORY` 表 | 在高德地图里搜索天安门，然后开始驾车导航。 |
| `amap_saved_route_with_via_random` | 保存带途经点路线 | 起点、终点、途经点组合；驾车路线 | `aMap.db` 的 `SAVE_ROUTE` 表 | 在高德地图里规划从广州塔到广州东站的驾车路线，途经体育西路，并把这条路线保存起来。 |
| `amap_vehicle_add_random` | 导航车辆设置 | 车牌：京/沪/粤/浙样例车牌 | `aMap.db` 的 `VEHICLES_LOCAL` 表 | 在高德地图的车辆设置里添加车牌沪B3K9M7，用于驾车导航和限行提醒。 |
| `amap_vehicle_default_random` | 常用车辆切换 | 初始化预置两辆车，目标车初始非常用；任务要求切换常用车辆 | `aMap.db` 的 `VEHICLES_LOCAL` 表 | 在高德地图的车辆设置里，把车牌粤A5Q2R8设为常用车辆。 |
| `amap_truck_route_guide_random` | 货车路线引导 | 开启或关闭货车路线引导 | `user_route_method_info.xml` 里的 `need_guide_truck` | 在高德地图路线规划设置里开启货车路线引导。 |

## 验证来源

搜索类任务读取 `shared_prefs/com.booking_preferences.xml` 里的 `general_query` 和 `specific_query` JSON。

偏好类任务读取同一个 XML 里的 `currency`、`locale`。

隐私类任务读取 `shared_prefs/gdpr_settings.xml` 里的 `marketing`、`functional`、`analytical`。

权限类任务读取 Android package runtime permission 状态，必要时用 `pm grant`/`pm revoke` 初始化。

随机住宿搜索模板会把目的地、日期、成人数、儿童年龄、房间数等参数采样成一个具体任务。扩展模板还支持排序、商务出行目的，以及通过最新 `cache/saba-http-cache` 中的 `mobile.saba` 请求参数验证结果页筛选项。筛选项按类别分组采样，避免生成“四星 + 五星”或“酒店 + 公寓”这类互斥组合。

高德地图设置类任务读取 `shared_prefs` 里的实际开关值；权限类任务读取 Android runtime permission；收藏、路线、导航和车辆类任务读取 `databases/aMap.db` 里的 `SAVE_POINT`、`RouteHistory`、`SAVE_ROUTE`、`NAVI_HISTORY`、`VEHICLES_LOCAL` 表。初始化会清掉目标相关测试记录、预置未完成的车辆状态，或把开关设为目标的相反状态，但不会写入任务要求的完成状态。

## JSON 字段

[`suites/booking_app_tasks.json`](suites/booking_app_tasks.json) 是整套任务的源定义。它不直接要求用户执行某个固定任务，而是定义“任务模板”，再由 `materialize` 命令采样成具体任务实例。

顶层字段：

| 字段 | 含义 |
|---|---|
| `suite_id` | 任务套件 ID，用来标识这套 Booking Android 任务定义。 |
| `app` | 目标 app 和模拟器信息，包括 app 名称、包名、AVD 名称、已测试版本。 |
| `verification_model` | 验证模型说明，列出奖励验证会读取哪些 Android/app 后台状态。 |
| `task_templates` | 任务模板数组，是当前 suite 的主要内容。每个模板描述一种可随机生成的任务类型。 |
| `tasks` | 固定任务数组。当前为空数组 `[]`，因为本套件已改为全模板化；具体任务会生成到 `.task_state/<task_id>.json`。 |

`app` 字段：

| 字段 | 含义 |
|---|---|
| `name` | app 显示名称。 |
| `package` | Android 包名，当前为 `com.booking`。 |
| `avd_name` | 目标模拟器名称，当前为 `OpenEndWorld`。 |
| `tested_version` | 设计和验证时观察到的 Booking app 版本。 |

`verification_model` 字段：

| 字段 | 含义 |
|---|---|
| `principle` | 验证原则：不靠截图或 UI 文本，而是读取系统状态或 app 后台数据。 |
| `app_data_root` | Booking 私有数据目录。 |
| `primary_files` | 主要读取的 app 数据文件，例如 `com.booking_preferences.xml`、`gdpr_settings.xml`、`saba-http-cache`。 |
| `system_sources` | 主要读取的 Android 系统状态，例如 `dumpsys package com.booking` 的 runtime permissions。 |

每个 `task_templates[]` 元素：

| 字段 | 含义 |
|---|---|
| `id` | 模板 ID，也是 `materialize` 命令使用的名字。 |
| `category` | 模板类别，例如 `accommodation_search`、`preferences`、`privacy`、`android_permission`。 |
| `description` | 模板的人类可读说明。 |
| `instruction_template` | 中文指令模板。生成实例时会把 `{destination_zh}`、`{arrival_date}`、`{currency_code}` 等占位符替换成采样结果。 |
| `parameters` | 采样空间和模板专有配置。不同模板的结构不同。 |
| `reward` | 奖励配置，包括满分和各检查项权重。 |

常见 `parameters` 子字段：

| 字段 | 出现位置 | 含义 |
|---|---|---|
| `destinations` | 住宿搜索模板 | 可采样目的地列表。每个目的地包含英文名、中文名、国家码、Booking 城市 ID、类型。 |
| `arrival_start` / `arrival_end` | 住宿搜索模板 | 入住日期采样范围。 |
| `nights` | 住宿搜索模板 | 入住晚数候选。退房日期由入住日期 + 晚数得到。 |
| `adult_count` | 住宿搜索模板 | 成人数量候选。 |
| `room_count` | 住宿搜索模板 | 房间数量候选。 |
| `children` | 住宿搜索模板 | 儿童数量候选和年龄范围。 |
| `inherits` | 扩展搜索模板 | 继承基础搜索模板的采样空间，例如排序/筛选模板继承 `stay_search_random`。 |
| `sort_options` | 排序/复杂搜索模板 | 可采样排序方式。 |
| `travel_purpose` | 商务搜索模板 | 目标出行目的和初始化基线。 |
| `filters` | 筛选/复杂搜索模板 | 可采样筛选项。每项包含中文名、SABA 参数名、可匹配 token、分组。 |
| `filter_count` | 复杂搜索模板 | 一次任务要采样几个筛选项。 |
| `include_sort_probability` | 复杂搜索模板 | 是否附加排序要求的概率。当前复杂模板设为 `1.0`。 |
| `include_business_probability` | 复杂搜索模板 | 是否附加商务出行要求的概率。当前复杂模板设为 `1.0`。 |
| `options` | 偏好/隐私/权限模板 | 可采样目标列表，例如币种、语言、Cookie 组合、Android 权限。 |

筛选项字段：

| 字段 | 含义 |
|---|---|
| `id` | 筛选项内部 ID。 |
| `name_zh` | 中文描述，会写入用户指令。 |
| `saba_param` | 预期出现在最新 `mobile.saba` 请求里的参数名，通常是 `categories_filter`。 |
| `contains_any` | 验证时接受的 token 列表。命中任意一个即认为该筛选项通过。 |
| `group` | 筛选互斥分组。复杂模板采样时同组最多选一个，避免生成互斥任务。 |

`reward` 字段：

| 字段 | 含义 |
|---|---|
| `max` | 该任务满分，当前通常为 `1.0`。 |
| `weights` | 各检查项权重。搜索类常见检查项包括 `dates`、`destination`、`occupancy`、`rooms`、`sort`、`travel_purpose`、`latest_saba_query`。偏好类使用 `currency` / `locale`，隐私类使用 `marketing` / `functional` / `analytical`，权限类使用具体 permission 名称。 |

生成后的任务实例字段：

| 字段 | 含义 |
|---|---|
| `id` | 实例 ID，由 `--id` 指定或自动生成。 |
| `template_id` | 来源模板 ID。 |
| `seed` | 随机种子。相同模板和 seed 可复现同一组参数。 |
| `instruction` | 最终给 agent/用户执行的中文任务指令。 |
| `parameters` | 本次采样到的目标和初始化基线，方便调试。 |
| `init` | 初始化策略。可能写入旧搜索 query、设置偏好基线、设置隐私基线、设置权限基线、清空 SABA 缓存。 |
| `verify` | 验证断言。会被 `verify_task` 读取并转换成奖励检查。 |
| `reward` | 从模板复制来的奖励配置。 |

## 初始化原则

每个实例初始化到“明确未完成但用户可自然完成”的状态。例如让用户把货币改成 CAD 前，初始化会把 `currency` 设置为 `USD`；让用户做复杂住宿筛选前，初始化会放入另一组不同的搜索参数，并清空 SABA 搜索缓存，避免旧结果页请求污染验证。
