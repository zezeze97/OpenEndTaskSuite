#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUITE_PATH = ROOT / "suites" / "booking_app_tasks.json"
PACKAGE = "com.booking"
APP_ROOT = f"/data/user/0/{PACKAGE}"
PREFS_PATH = f"{APP_ROOT}/shared_prefs/com.booking_preferences.xml"
GDPR_PATH = f"{APP_ROOT}/shared_prefs/gdpr_settings.xml"


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


def find_task(suite, task_id):
    for task in suite["tasks"]:
        if task["id"] == task_id:
            return task
    raise SystemExit(f"Unknown task id: {task_id}")


def ensure_device(serial):
    adb(serial, "root")
    adb_shell(serial, f"pm path {PACKAGE}")


def pull_text(serial, remote_path):
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "file.xml"
        adb(serial, "pull", remote_path, str(local))
        return local.read_text(encoding="utf-8")


def app_linux_user(serial):
    output = adb_shell(serial, f"dumpsys package {PACKAGE}")
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("userId="):
            uid = int(line.split("=", 1)[1])
            return f"u0_a{uid - 10000}"
    return None


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
    tag = target.tag if target is not None else infer_pref_tag(value)
    if target is None:
        target = ET.SubElement(root, tag)
        target.set("name", key)
    if tag == "string":
        target.text = str(value)
        target.attrib.pop("value", None)
    elif tag == "boolean":
        target.text = None
        target.set("value", str(bool(value)).lower())
    elif tag in ("int", "long", "float"):
        target.text = None
        target.set("value", str(value))
    else:
        target.text = str(value)


def render_existing_map(xml_text, updates):
    root = ET.fromstring(xml_text)
    for key, value in updates.items():
        set_pref_element(root, key, value)
    rough = ET.tostring(root, encoding="unicode")
    return "<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n" + rough + "\n"


def update_xml_values(serial, remote_path, updates):
    xml_text = pull_text(serial, remote_path)
    push_text(serial, remote_path, render_existing_map(xml_text, updates))


def normalized_query(query):
    base = {
        "sort": {"id": "auto", "name": "auto"},
        "location": {
            "location_source": "recents",
            "autocomplete_position": 0
        }
    }
    out = dict(query)
    location = dict(base["location"])
    location.update(query.get("location", {}))
    out["location"] = location
    out.setdefault("sort", base["sort"])
    out.setdefault("children_ages", [])
    out.setdefault("room_count", 1)
    out.setdefault("travel_purpose", "not_selected")
    return out


def set_query(serial, query):
    query_json = json.dumps(normalized_query(query), separators=(",", ":"), ensure_ascii=False)
    update_xml_values(serial, PREFS_PATH, {
        "general_query": query_json,
        "specific_query": query_json
    })


def init_permissions(serial, permissions):
    for permission, granted in permissions.items():
        action = "grant" if granted else "revoke"
        adb_shell(serial, f"pm {action} {PACKAGE} {permission}", check=False)


def permission_granted(serial, permission):
    output = adb_shell(serial, f"dumpsys package {PACKAGE}")
    marker = f"{permission}: granted=true"
    return marker in output


def get_queries(serial):
    prefs = parse_map(pull_text(serial, PREFS_PATH))
    queries = []
    for key in ("specific_query", "general_query"):
        if key in prefs:
            try:
                queries.append(json.loads(prefs[key]))
            except json.JSONDecodeError:
                pass
    return queries


def any_query_matches(serial, expected):
    queries = get_queries(serial)
    details = {}

    def field_ok(name):
        value = expected[name]
        return any(query.get(name) == value for query in queries)

    if "arrival_date" in expected and "departure_date" in expected:
        details["dates"] = any(
            query.get("arrival_date") == expected["arrival_date"]
            and query.get("departure_date") == expected["departure_date"]
            for query in queries
        )
    if "location_contains" in expected or "country_code" in expected:
        needle = expected.get("location_contains", "").lower()
        country = expected.get("country_code")
        details["destination"] = any(
            (not needle or needle in json.dumps(query.get("location", {})).lower())
            and (not country or query.get("location", {}).get("country_code") == country)
            for query in queries
        )
    if "adult_count" in expected or "children_ages" in expected:
        details["occupancy"] = any(
            ("adult_count" not in expected or query.get("adult_count") == expected["adult_count"])
            and ("children_ages" not in expected or sorted(query.get("children_ages", [])) == sorted(expected["children_ages"]))
            for query in queries
        )
    if "room_count" in expected:
        details["rooms"] = field_ok("room_count")
    return details


def init_task(serial, task):
    ensure_device(serial)
    adb_shell(serial, f"am force-stop {PACKAGE}", check=False)
    init = task.get("init", {})
    if "query" in init:
        set_query(serial, init["query"])
    if "prefs" in init:
        update_xml_values(serial, PREFS_PATH, init["prefs"])
    if "gdpr" in init:
        update_xml_values(serial, GDPR_PATH, init["gdpr"])
    if "permissions" in init:
        init_permissions(serial, init["permissions"])
    adb_shell(serial, f"monkey -p {PACKAGE} -c android.intent.category.LAUNCHER 1 >/dev/null")


def verify_task(serial, task):
    ensure_device(serial)
    verify = task.get("verify", {})
    weights = task.get("reward", {}).get("weights", {})
    checks = {}

    if "query" in verify:
        checks.update(any_query_matches(serial, verify["query"]))
    if "prefs" in verify:
        prefs = parse_map(pull_text(serial, PREFS_PATH))
        for key, expected in verify["prefs"].items():
            checks[key] = prefs.get(key) == expected
    if "gdpr" in verify:
        gdpr = parse_map(pull_text(serial, GDPR_PATH))
        for key, expected in verify["gdpr"].items():
            checks[key] = gdpr.get(key) == expected
    if "permissions" in verify:
        for permission, expected in verify["permissions"].items():
            checks[permission] = permission_granted(serial, permission) == expected

    reward = 0.0
    for name, ok in checks.items():
        reward += weights.get(name, 0.0) if ok else 0.0
    reward = min(task.get("reward", {}).get("max", 1.0), reward)
    return {"task_id": task["id"], "reward": round(reward, 4), "checks": checks}


def main():
    global SUITE_PATH
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", default=os.environ.get("ANDROID_SERIAL", "emulator-5554"))
    parser.add_argument("--suite", default=str(SUITE_PATH))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    init_parser = sub.add_parser("init")
    init_parser.add_argument("task_id")
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("task_id")
    args = parser.parse_args()

    SUITE_PATH = Path(args.suite)
    suite = load_suite()

    if args.command == "list":
        for task in suite["tasks"]:
            print(f"{task['id']}\t{task['category']}\t{task['instruction']}")
        return

    task = find_task(suite, args.task_id)
    if args.command == "init":
        init_task(args.serial, task)
        print(json.dumps({"task_id": task["id"], "initialized": True}, ensure_ascii=False))
    elif args.command == "verify":
        print(json.dumps(verify_task(args.serial, task), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
