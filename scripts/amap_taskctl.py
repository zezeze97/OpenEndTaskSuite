#!/usr/bin/env python3
import argparse
import json
import random
import shlex
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUITE_PATH = ROOT / "suites" / "amap_app_tasks.json"
STATE_DIR = ROOT / ".task_state"
PACKAGE = "com.autonavi.minimap"
APP_ROOT = f"/data/user/0/{PACKAGE}"
TEXT_SIZE_PREF = f"{APP_ROOT}/shared_prefs/MapTextSizeSet.xml"
LANGUAGE_PREF = f"{APP_ROOT}/shared_prefs/appLanguage.xml"
LAYER_PREF = f"{APP_ROOT}/shared_prefs/SP_NAME_layer_checked.xml"
PUSH_PREF = f"{APP_ROOT}/shared_prefs/push_state.xml"
AMAP_DB = f"{APP_ROOT}/databases/aMap.db"
SUITE_PREFIX = "openend_amap_"


def adb(serial, *args, check=True, text=True):
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += list(args)
    proc = subprocess.run(cmd, check=False, text=text, capture_output=True)
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return proc.stdout


def adb_shell(serial, command, check=True):
    return adb(serial, "shell", command, check=check)


def load_suite():
    return json.loads(SUITE_PATH.read_text(encoding="utf-8"))


def find_template(suite, template_id):
    for template in suite.get("task_templates", []):
        if template["id"] == template_id:
            return template
    raise SystemExit(f"Unknown template id: {template_id}")


def find_task(suite, task_id):
    for task in suite.get("tasks", []):
        if task["id"] == task_id:
            return task
    instance_path = STATE_DIR / f"{task_id}.json"
    if instance_path.exists():
        return json.loads(instance_path.read_text(encoding="utf-8"))
    raise SystemExit(f"Unknown task id: {task_id}")


def ensure_device(serial):
    adb(serial, "root")
    adb_shell(serial, f"pm path {PACKAGE}")


def app_linux_user(serial):
    output = adb_shell(serial, f"dumpsys package {PACKAGE}")
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("userId="):
            uid = int(line.split("=", 1)[1])
            return f"u0_a{uid - 10000}"
    return None


def pull_text(serial, remote_path):
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "file.xml"
        adb(serial, "pull", remote_path, str(local), check=False)
        if local.exists():
            return local.read_text(encoding="utf-8")
    return "<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n<map />\n"


def push_text(serial, remote_path, content):
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "file.xml"
        local.write_text(content, encoding="utf-8")
        adb(serial, "push", str(local), remote_path)
    linux_user = app_linux_user(serial)
    if linux_user:
        adb_shell(serial, f"chown {linux_user}:{linux_user} {remote_path}", check=False)
    adb_shell(serial, f"chmod 660 {remote_path}", check=False)


def parse_map(xml_text):
    root = ET.fromstring(xml_text)
    values = {}
    for child in root:
        name = child.attrib.get("name")
        if not name:
            continue
        if child.tag == "string":
            values[name] = child.text or ""
        elif child.tag == "int":
            values[name] = int(child.attrib.get("value", "0"))
        elif child.tag == "long":
            values[name] = int(child.attrib.get("value", "0"))
        elif child.tag == "boolean":
            values[name] = child.attrib.get("value") == "true"
    return values


def infer_pref_tag(value):
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "int"
    return "string"


def set_pref_element(root, key, value):
    target = None
    for child in root:
        if child.attrib.get("name") == key:
            target = child
            break
    if target is None:
        target = ET.SubElement(root, infer_pref_tag(value))
        target.set("name", key)
    if target.tag == "string":
        target.attrib.pop("value", None)
        target.text = str(value)
    elif target.tag == "boolean":
        target.text = None
        target.set("value", str(bool(value)).lower())
    elif target.tag in ("int", "long", "float"):
        target.text = None
        target.set("value", str(value))
    else:
        target.text = str(value)


def render_xml_map(xml_text, updates):
    root = ET.fromstring(xml_text)
    for key, value in updates.items():
        set_pref_element(root, key, value)
    body = ET.tostring(root, encoding="unicode")
    return "<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n" + body + "\n"


def update_xml_values(serial, remote_path, updates):
    xml_text = pull_text(serial, remote_path)
    push_text(serial, remote_path, render_xml_map(xml_text, updates))


def pref_value(serial, remote_path, key):
    return parse_map(pull_text(serial, remote_path)).get(key)


def sql_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def sqlite_scalar(serial, sql):
    quoted = shlex.quote(sql)
    return adb_shell(serial, f"sqlite3 {shlex.quote(AMAP_DB)} {quoted}", check=False).strip()


def sqlite_exec(serial, sql):
    quoted = shlex.quote(sql)
    adb_shell(serial, f"sqlite3 {shlex.quote(AMAP_DB)} {quoted}", check=False)


def delete_suite_db_rows(serial):
    prefix = sql_quote(SUITE_PREFIX + "%")
    sqlite_exec(serial, f"delete from SAVE_POINT where KEY like {prefix};")
    sqlite_exec(serial, f"delete from RouteHistory where ID like {prefix};")
    sqlite_exec(serial, f"delete from SAVE_ROUTE where KEY like {prefix};")


def permission_granted(serial, permission):
    output = adb_shell(serial, f"dumpsys package {PACKAGE}")
    for line in output.splitlines():
        if permission in line and "granted=" in line:
            return "granted=true" in line
    return False


def set_permission(serial, permission, target):
    action = "grant" if target else "revoke"
    adb_shell(serial, f"pm {action} {PACKAGE} {permission}", check=False)


def sample_route_params(template, rng):
    route = dict(rng.choice(template["parameters"]["routes"]))
    mode = dict(rng.choice(template["parameters"]["route_modes"]))
    return {
        "route_id": route["id"],
        "from": route["from"],
        "to": route["to"],
        "route_mode": mode["id"],
        "route_type": mode["route_type"],
        "route_mode_zh": mode["route_mode_zh"]
    }


def materialize_template(suite, template, seed=None, instance_id=None):
    if seed is None:
        seed = random.randint(1, 2**31 - 1)
    rng = random.Random(seed)
    instance_id = instance_id or f"{template['id']}_{seed}"
    task = {
        "id": instance_id,
        "template_id": template["id"],
        "seed": seed,
        "reward": template["reward"]
    }

    if template["id"] == "amap_map_text_size_random":
        option = dict(rng.choice(template["parameters"]["options"]))
        task.update({
            "instruction": template["instruction_template"].format(target_zh=option["target_zh"]),
            "parameters": option,
            "init": {"prefs": [{"path": TEXT_SIZE_PREF, "values": {"map_text_size": option["baseline"]}}]},
            "verify": {"prefs": [{"path": TEXT_SIZE_PREF, "key": "map_text_size", "equals": option["target"], "weight": "map_text_size"}]}
        })
    elif template["id"] == "amap_language_random":
        option = dict(rng.choice(template["parameters"]["options"]))
        task.update({
            "instruction": template["instruction_template"].format(target_zh=option["target_zh"]),
            "parameters": option,
            "init": {"prefs": [{"path": LANGUAGE_PREF, "values": {"language_switch_option": option["baseline"]}}]},
            "verify": {"prefs": [{"path": LANGUAGE_PREF, "key": "language_switch_option", "equals": option["target"], "weight": "language_switch_option"}]}
        })
    elif template["id"] == "amap_layer_toggle_random":
        layer = dict(rng.choice(template["parameters"]["layers"]))
        action = dict(rng.choice(template["parameters"]["actions"]))
        task.update({
            "instruction": template["instruction_template"].format(action_zh=action["action_zh"], layer_zh=layer["layer_zh"]),
            "parameters": {**layer, **action},
            "init": {"prefs": [{"path": LAYER_PREF, "values": {layer["id"]: not action["target"]}}]},
            "verify": {"prefs": [{"path": LAYER_PREF, "key": layer["id"], "equals": action["target"], "weight": "layer_checked"}]}
        })
    elif template["id"] == "amap_push_setting_random":
        option = dict(rng.choice(template["parameters"]["options"]))
        task.update({
            "instruction": template["instruction_template"].format(action_zh=option["action_zh"]),
            "parameters": option,
            "init": {"prefs": [{"path": PUSH_PREF, "values": {"push_setting": not option["target"]}}]},
            "verify": {"prefs": [{"path": PUSH_PREF, "key": "push_setting", "equals": option["target"], "weight": "push_setting"}]}
        })
    elif template["id"] == "amap_permission_random":
        option = dict(rng.choice(template["parameters"]["options"]))
        task.update({
            "instruction": template["instruction_template"].format(action_zh=option["action_zh"], permission_zh=option["permission_zh"]),
            "parameters": option,
            "init": {"permissions": [{"permission": option["permission"], "granted": not option["target"]}]},
            "verify": {"permissions": [{"permission": option["permission"], "granted": option["target"], "weight": "runtime_permission"}]}
        })
    elif template["id"] == "amap_saved_point_random":
        poi = dict(rng.choice(template["parameters"]["pois"]))
        task_key = SUITE_PREFIX + "point_" + poi["id"]
        task.update({
            "instruction": template["instruction_template"].format(poi_zh=poi["name"]),
            "parameters": {**poi, "db_key": task_key},
            "init": {
                "clear_db_rows": True,
                "sqlite_delete": [{
                    "table": "SAVE_POINT",
                    "where": f"(COMMON_NAME = {sql_quote(poi['name'])} or POI_JSON like {sql_quote('%' + poi['name'] + '%')})"
                }]
            },
            "verify": {"sqlite_exists": [{
                "table": "SAVE_POINT",
                "where": f"(COMMON_NAME = {sql_quote(poi['name'])} or POI_JSON like {sql_quote('%' + poi['name'] + '%')})",
                "weight": "saved_point"
            }]}
        })
    elif template["id"] == "amap_route_history_random":
        params = sample_route_params(template, rng)
        task.update({
            "instruction": template["instruction_template"].format(from_zh=params["from"], to_zh=params["to"], route_mode_zh=params["route_mode_zh"]),
            "parameters": params,
            "init": {
                "clear_db_rows": True,
                "sqlite_delete": [{
                    "table": "RouteHistory",
                    "where": (
                        f"(ROUTE_NAME like {sql_quote('%' + params['from'] + '%')} or FROM_POI_JSON like {sql_quote('%' + params['from'] + '%')}) and "
                        f"(ROUTE_NAME like {sql_quote('%' + params['to'] + '%')} or TO_POI_JSON like {sql_quote('%' + params['to'] + '%')})"
                    )
                }]
            },
            "verify": {"sqlite_exists": [{
                "table": "RouteHistory",
                "where": (
                    f"ROUTE_TYPE = {params['route_type']} and "
                    f"(ROUTE_NAME like {sql_quote('%' + params['from'] + '%')} or FROM_POI_JSON like {sql_quote('%' + params['from'] + '%')}) and "
                    f"(ROUTE_NAME like {sql_quote('%' + params['to'] + '%')} or TO_POI_JSON like {sql_quote('%' + params['to'] + '%')})"
                ),
                "weight": "route_history"
            }]}
        })
    elif template["id"] == "amap_saved_route_random":
        params = sample_route_params(template, rng)
        task.update({
            "instruction": template["instruction_template"].format(from_zh=params["from"], to_zh=params["to"], route_mode_zh=params["route_mode_zh"]),
            "parameters": params,
            "init": {
                "clear_db_rows": True,
                "sqlite_delete": [{
                    "table": "SAVE_ROUTE",
                    "where": (
                        f"(ROUTE_NAME like {sql_quote('%' + params['from'] + '%')} or FROM_POI_JSON like {sql_quote('%' + params['from'] + '%')}) and "
                        f"(ROUTE_NAME like {sql_quote('%' + params['to'] + '%')} or TO_POI_JSON like {sql_quote('%' + params['to'] + '%')})"
                    )
                }]
            },
            "verify": {"sqlite_exists": [{
                "table": "SAVE_ROUTE",
                "where": (
                    f"ROUTE_TYPE = {params['route_type']} and "
                    f"(ROUTE_NAME like {sql_quote('%' + params['from'] + '%')} or FROM_POI_JSON like {sql_quote('%' + params['from'] + '%')}) and "
                    f"(ROUTE_NAME like {sql_quote('%' + params['to'] + '%')} or TO_POI_JSON like {sql_quote('%' + params['to'] + '%')})"
                ),
                "weight": "saved_route"
            }]}
        })
    else:
        raise SystemExit(f"Template materializer is not implemented: {template['id']}")

    return task


def save_instance(task):
    STATE_DIR.mkdir(exist_ok=True)
    path = STATE_DIR / f"{task['id']}.json"
    path.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def init_task(serial, task):
    ensure_device(serial)
    adb_shell(serial, f"am force-stop {PACKAGE}", check=False)
    init = task.get("init", {})
    if init.get("clear_db_rows"):
        delete_suite_db_rows(serial)
    for delete in init.get("sqlite_delete", []):
        sqlite_exec(serial, f"delete from {delete['table']} where {delete['where']};")
    for pref in init.get("prefs", []):
        update_xml_values(serial, pref["path"], pref["values"])
    for perm in init.get("permissions", []):
        set_permission(serial, perm["permission"], perm["granted"])
    adb_shell(serial, f"monkey -p {PACKAGE} -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1", check=False)
    time.sleep(1)


def verify_task(serial, task):
    ensure_device(serial)
    weights = task.get("reward", {}).get("weights", {})
    checks = []

    for pref in task.get("verify", {}).get("prefs", []):
        actual = pref_value(serial, pref["path"], pref["key"])
        passed = actual == pref["equals"]
        checks.append({
            "name": pref["weight"],
            "passed": passed,
            "expected": pref["equals"],
            "actual": actual,
            "weight": weights.get(pref["weight"], 0)
        })

    for perm in task.get("verify", {}).get("permissions", []):
        actual = permission_granted(serial, perm["permission"])
        passed = actual == perm["granted"]
        checks.append({
            "name": perm["weight"],
            "passed": passed,
            "expected": perm["granted"],
            "actual": actual,
            "weight": weights.get(perm["weight"], 0)
        })

    for exists in task.get("verify", {}).get("sqlite_exists", []):
        table = exists["table"]
        where = exists["where"]
        raw = sqlite_scalar(serial, f"select count(*) from {table} where {where};")
        try:
            count = int(raw.splitlines()[-1] or "0")
        except ValueError:
            count = 0
        checks.append({
            "name": exists["weight"],
            "passed": count > 0,
            "expected": "count > 0",
            "actual": count,
            "weight": weights.get(exists["weight"], 0)
        })

    score = sum(item["weight"] for item in checks if item["passed"])
    return {
        "task_id": task["id"],
        "template_id": task.get("template_id"),
        "score": round(score, 4),
        "max": task.get("reward", {}).get("max", 1.0),
        "checks": checks
    }


def list_templates(suite):
    for template in suite.get("task_templates", []):
        print(f"{template['id']}\t{template['category']}\t{template['description']}")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", default="emulator-5554")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list")

    mat = sub.add_parser("materialize")
    mat.add_argument("template_id")
    mat.add_argument("--seed", type=int)
    mat.add_argument("--id")
    mat.add_argument("--init", action="store_true")

    init_p = sub.add_parser("init")
    init_p.add_argument("task_id")

    verify_p = sub.add_parser("verify")
    verify_p.add_argument("task_id")

    args = parser.parse_args(argv)
    suite = load_suite()

    if args.cmd == "list":
        list_templates(suite)
    elif args.cmd == "materialize":
        task = materialize_template(suite, find_template(suite, args.template_id), args.seed, args.id)
        path = save_instance(task)
        print(json.dumps({"saved": str(path), "task": task}, ensure_ascii=False, indent=2))
        if args.init:
            init_task(args.serial, task)
    elif args.cmd == "init":
        init_task(args.serial, find_task(suite, args.task_id))
    elif args.cmd == "verify":
        print(json.dumps(verify_task(args.serial, find_task(suite, args.task_id)), ensure_ascii=False, indent=2))
    else:
        parser.error("unknown command")


if __name__ == "__main__":
    main(sys.argv[1:])
