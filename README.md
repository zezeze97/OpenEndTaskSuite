# Commercial App Android Task Suites

这个仓库提供一组可复现、可初始化、可自动验证的 Android 商业 app 任务模板。任务运行环境以 **redroid 虚拟机** 为准：agent 在 GUI 中完成任务，验证脚本通过 root ADB 读取 app 私有数据、系统权限状态和部分缓存请求来计算 reward。

## 测试环境

- Android 环境：redroid 虚拟机
- ADB：需要能连接到 redroid，并且 `adb shell id` 最终为 `uid=0(root)`
- 设备序列号：以 `adb devices` 输出为准，常见形式包括 `emulator-5554` 或 `<host>:5555`
- Python：`python3`
- 当前 redroid 实测 app：
  - Booking.com：`com.booking`，`versionName=64.6.0.11`，`versionCode=901724`

验证脚本会读取这些 app 的私有目录，例如：

```text
/data/user/0/com.booking
```

因此 redroid 必须允许 root ADB。脚本会尝试执行 `adb root`；如果设备不支持 root，初始化和验证会失败。

## 快速开始

先确认 redroid 已连接：

```bash
adb devices
adb root
adb shell id
```

如果有多台设备，建议显式指定序列号：

```bash
export ANDROID_SERIAL=<adb-devices-里的序列号>
```

也可以在每条命令前加 `--serial <serial>`。例如：

```bash
python3 scripts/booking_taskctl.py --serial "$ANDROID_SERIAL" verify run_001
```

列出 Booking 模板：

```bash
python3 scripts/booking_taskctl.py list
```

生成一个可复现任务实例：

```bash
python3 scripts/booking_taskctl.py materialize stay_search_complex_filter_random --seed 42 --id run_booking_42
```

初始化任务：

```bash
python3 scripts/booking_taskctl.py init run_booking_42
```

初始化会把目标 app 调整到“明确未完成”的基线状态，然后回到桌面并强制停止 app。agent 接手时应从 redroid 桌面启动目标 app。

验证任务：

```bash
python3 scripts/booking_taskctl.py verify run_booking_42
```

输出示例：

```json
{
  "task_id": "run_booking_42",
  "reward": 1.0,
  "checks": {
    "dates": true,
    "destination": true,
    "occupancy": true,
    "rooms": true,
    "sort": true,
    "latest_saba_query": true
  }
}
```


## Booking 任务

| 模板 ID | 类型 | 变化范围 | 验证来源 |
|---|---|---|---|
| `stay_search_random` | 住宿搜索 | 目的地、入住/退房日期、成人/儿童、房间数 | `general_query` / `specific_query` |
| `stay_search_sort_random` | 住宿搜索 + 排序 | 基础搜索参数 + 价格、住客评分、距离、星级等排序 | `general_query` / `specific_query`，必要时参考最新 SABA 请求 |
| `stay_search_saba_filter_random` | 住宿搜索 + 单筛选 | 免费取消、早餐、评分、住宿类型、星级、浴室、停车、Wi-Fi、泳池、空调等 | 最新 `mobile.saba` 请求 |
| `stay_search_complex_filter_random` | 复杂住宿搜索 | 基础搜索参数 + 2 到 3 个筛选项 + 排序 | `general_query` / `specific_query` + 最新 `mobile.saba` 请求 |
| `currency_random` | 货币偏好 | EUR、JPY、GBP、AUD、CAD 等 | `com.booking_preferences.xml` |
| `language_random` | 语言偏好 | 西班牙语、法语、德语、意大利语、葡萄牙语等 | `com.booking_preferences.xml` |
| `privacy_cookie_random` | Cookie/隐私设置 | 营销、功能、分析 Cookie 组合 | `gdpr_settings.xml` 或 OneTrust prefs |
| `booking_permission_random` | Android 权限 | 通知、相机、位置、麦克风、日历 | `dumpsys package` |


## 初始化原则

初始化只写入“未完成但可自然完成”的基线状态，流程通常是：

1. 强制停止目标 app
2. 写入基线设置、数据库记录或权限状态
3. 清理可能影响验证的缓存或历史数据
4. 回到 Home
5. 再次强制停止目标 app

这样 agent 每次都从 redroid 桌面开始，任务状态可复现，验证结果也更稳定。
