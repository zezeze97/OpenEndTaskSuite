#!/usr/bin/env python3
import argparse
import copy
import datetime as dt
import json
import os
import random
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
SUITE_PATH = ROOT / "suites" / "booking_app_tasks.json"
STATE_DIR = ROOT / ".task_state"
PACKAGE = "com.booking"
APP_ROOT = f"/data/user/0/{PACKAGE}"
PREFS_PATH = f"{APP_ROOT}/shared_prefs/com.booking_preferences.xml"
GDPR_PATH = f"{APP_ROOT}/shared_prefs/gdpr_settings.xml"
ADB_TIMEOUT_SECONDS = 30
ADB_ROOT_TIMEOUT_SECONDS = 10
ADB_PROBE_TIMEOUT_SECONDS = 5


def adb(serial, *args, check=True, text=True, timeout=ADB_TIMEOUT_SECONDS):
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += list(args)
    try:
        proc = subprocess.run(cmd, check=False, text=text, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Command timed out after {timeout}s: {' '.join(cmd)}\n"
            "adb may be wedged; try `adb kill-server && adb start-server`, then rerun the task."
        ) from exc
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return proc.stdout


def adb_shell(serial, command, check=True, timeout=ADB_TIMEOUT_SECONDS):
    return adb(serial, "shell", command, check=check, timeout=timeout)


def load_suite():
    return json.loads(SUITE_PATH.read_text(encoding="utf-8"))


def find_task(suite, task_id):
    for task in suite["tasks"]:
        if task["id"] == task_id:
            return task
    instance_path = STATE_DIR / f"{task_id}.json"
    if instance_path.exists():
        return json.loads(instance_path.read_text(encoding="utf-8"))
    raise SystemExit(f"Unknown task id: {task_id}")


def find_template(suite, template_id):
    for template in suite.get("task_templates", []):
        if template["id"] == template_id:
            return template
    raise SystemExit(f"Unknown template id: {template_id}")


def ensure_device(serial):
    state = adb(serial, "get-state", timeout=ADB_PROBE_TIMEOUT_SECONDS).strip()
    if state != "device":
        raise RuntimeError(f"adb device is not ready: {state or 'unknown'}")
    identity = adb_shell(serial, "id", check=False, timeout=ADB_PROBE_TIMEOUT_SECONDS)
    if "uid=0" not in identity:
        adb(serial, "root", check=False, timeout=ADB_ROOT_TIMEOUT_SECONDS)
        adb(serial, "wait-for-device", timeout=ADB_TIMEOUT_SECONDS)
        identity = adb_shell(serial, "id", check=False, timeout=ADB_PROBE_TIMEOUT_SECONDS)
    if "uid=0" not in identity:
        raise RuntimeError("adb shell is not root; app private data cannot be initialized or verified.")
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


def resolve_base_template(suite, template):
    inherited = template.get("parameters", {}).get("inherits")
    if not inherited:
        return template
    return find_template(suite, inherited)


def sample_date(rng, start, end):
    start_date = dt.date.fromisoformat(start)
    end_date = dt.date.fromisoformat(end)
    return start_date + dt.timedelta(days=rng.randint(0, (end_date - start_date).days))


def sample_children(rng, spec):
    count = rng.choice(spec["count"])
    return sorted(rng.randint(spec["age_min"], spec["age_max"]) for _ in range(count))


def sample_search_params(suite, template, rng):
    params = resolve_base_template(suite, template)["parameters"]
    destination = copy.deepcopy(rng.choice(params["destinations"]))
    arrival = sample_date(rng, params["arrival_start"], params["arrival_end"])
    departure = arrival + dt.timedelta(days=rng.choice(params["nights"]))
    return {
        "destination": destination,
        "arrival_date": arrival.isoformat(),
        "departure_date": departure.isoformat(),
        "adult_count": rng.choice(params["adult_count"]),
        "children_ages": sample_children(rng, params["children"]),
        "room_count": rng.choice(params["room_count"]),
    }


def params_signature(params):
    return {
        "destination": params["destination"]["name"],
        "dates": [params["arrival_date"], params["departure_date"]],
        "adult_count": params["adult_count"],
        "children_ages": params["children_ages"],
        "room_count": params["room_count"],
    }


def shares_reward_dimension(left, right):
    return (
        left["destination"]["name"] == right["destination"]["name"]
        or left["arrival_date"] == right["arrival_date"]
        or left["departure_date"] == right["departure_date"]
        or left["adult_count"] == right["adult_count"]
        or left["children_ages"] == right["children_ages"]
        or left["room_count"] == right["room_count"]
    )


def params_to_query(params, sort=None, travel_purpose="not_selected"):
    destination = params["destination"]
    return {
        "arrival_date": params["arrival_date"],
        "departure_date": params["departure_date"],
        "location": {
            "id": destination["id"],
            "city": destination["name"],
            "type": destination.get("type", "city"),
            "name": destination["name"],
            "country_code": destination["country_code"],
        },
        "adult_count": params["adult_count"],
        "children_ages": params["children_ages"],
        "room_count": params["room_count"],
        "sort": sort or {"id": "auto", "name": "auto"},
        "travel_purpose": travel_purpose,
    }


def occupancy_zh(params):
    parts = [f"{params['adult_count']} 位成人"]
    if params["children_ages"]:
        ages = " 和 ".join(f"{age} 岁" for age in params["children_ages"])
        parts.append(f"{len(params['children_ages'])} 位儿童（{ages}）")
    return "、".join(parts)


def materialize_template(suite, template, seed=None, instance_id=None):
    if seed is None:
        seed = random.SystemRandom().randint(1, 2**31 - 1)
    rng = random.Random(seed)
    category = template["category"]
    if instance_id is None:
        instance_id = f"{template['id']}_{seed}"

    if category == "preferences":
        option = copy.deepcopy(rng.choice(template["parameters"]["options"]))
        key = "currency" if "currency" in template["id"] else "locale"
        instruction = template["instruction_template"].format(
            currency_zh=option.get("name_zh", ""),
            currency_code=option.get("code", ""),
            language_zh=option.get("name_zh", ""),
        )
        return {
            "id": instance_id,
            "template_id": template["id"],
            "seed": seed,
            "instruction": instruction,
            "category": category,
            "parameters": {"target": option["code"], "baseline": option["baseline"]},
            "init": {"prefs": {key: option["baseline"]}},
            "verify": {"prefs": {key: option["code"]}},
            "reward": copy.deepcopy(template["reward"]),
        }

    if category == "privacy":
        option = copy.deepcopy(rng.choice(template["parameters"]["options"]))
        return {
            "id": instance_id,
            "template_id": template["id"],
            "seed": seed,
            "instruction": template["instruction_template"].format(privacy_action_zh=option["action_zh"]),
            "category": category,
            "parameters": {"target": option["target"], "baseline": option["baseline"]},
            "init": {"gdpr": option["baseline"]},
            "verify": {"gdpr": option["target"]},
            "reward": copy.deepcopy(template["reward"]),
        }

    if category == "android_permission":
        option = copy.deepcopy(rng.choice(template["parameters"]["options"]))
        permissions = [option["permission"]]
        if option.get("paired_permission"):
            permissions.append(option["paired_permission"])
        init_permissions_map = {permission: option["baseline"] for permission in permissions}
        verify_permissions = {permission: option["target"] for permission in permissions}
        weight = round(1.0 / len(permissions), 4)
        return {
            "id": instance_id,
            "template_id": template["id"],
            "seed": seed,
            "instruction": template["instruction_template"].format(
                permission_action_zh=option["action_zh"],
                permission_zh=option["name_zh"],
            ),
            "category": category,
            "parameters": {"target": verify_permissions, "baseline": init_permissions_map},
            "init": {"permissions": init_permissions_map},
            "verify": {"permissions": verify_permissions},
            "reward": {"max": 1.0, "weights": {permission: weight for permission in permissions}},
        }

    target = sample_search_params(suite, template, rng)
    baseline = sample_search_params(suite, template, rng)
    attempts = 0
    while shares_reward_dimension(target, baseline) and attempts < 100:
        baseline = sample_search_params(suite, template, rng)
        attempts += 1

    params = template.get("parameters", {})
    sort = None
    travel_purpose = None
    filter_option = None
    filter_options = []
    if "sort_options" in params:
        probability = params.get("include_sort_probability", 1.0)
        if rng.random() <= probability:
            sort = copy.deepcopy(rng.choice(params["sort_options"]))
    if "travel_purpose" in params:
        travel_purpose = params["travel_purpose"]["id"]
    elif rng.random() <= params.get("include_business_probability", 0.0):
        travel_purpose = "business"
    if "filters" in params:
        if "filter_count" in params:
            count = rng.choice(params["filter_count"])
            shuffled = copy.deepcopy(params["filters"])
            rng.shuffle(shuffled)
            seen_groups = set()
            for option in shuffled:
                group = option.get("group", option["id"])
                if group in seen_groups:
                    continue
                filter_options.append(option)
                seen_groups.add(group)
                if len(filter_options) >= count:
                    break
        else:
            filter_option = copy.deepcopy(rng.choice(params["filters"]))
            filter_options = [filter_option]

    instruction = template["instruction_template"].format(
        destination_zh=target["destination"]["name_zh"],
        arrival_date=target["arrival_date"],
        departure_date=target["departure_date"],
        occupancy_zh=occupancy_zh(target),
        room_count_zh=f"{target['room_count']} 间房",
        sort_zh=sort["name_zh"] if sort else "",
        filter_zh=filter_option["name_zh"] if filter_option else "",
        filters_zh="、".join(option["name_zh"] for option in filter_options),
        sort_clause_zh=f"，并按{sort['name_zh']}排序" if sort else "",
        business_clause_zh="，同时标记为商务出行" if travel_purpose == "business" else "",
    )

    target_query = params_to_query(
        target,
        sort={"id": sort["id"], "name": sort["name"]} if sort else None,
        travel_purpose=travel_purpose or "not_selected",
    )
    baseline_query = params_to_query(baseline)
    verify_query = {
        "arrival_date": target["arrival_date"],
        "departure_date": target["departure_date"],
        "location_contains": target["destination"]["name"],
        "country_code": target["destination"]["country_code"],
        "adult_count": target["adult_count"],
        "children_ages": target["children_ages"],
        "room_count": target["room_count"],
    }
    if sort:
        verify_query["sort"] = {"id": sort["id"], "name": sort["name"]}
    if travel_purpose:
        verify_query["travel_purpose"] = travel_purpose

    task = {
        "id": instance_id,
        "template_id": template["id"],
        "seed": seed,
        "instruction": instruction,
        "category": template["category"],
        "parameters": {
            "target": params_signature(target),
            "baseline": params_signature(baseline),
        },
        "init": {"query": baseline_query},
        "verify": {"query": verify_query},
        "reward": copy.deepcopy(template["reward"]),
    }
    if filter_options:
        task["init"]["clear_saba_cache"] = True
        task["parameters"]["filters"] = [option["id"] for option in filter_options]
        task["verify"]["latest_saba_query"] = [
            {
                "destination": target["destination"]["name"],
                "arrival_date": target["arrival_date"],
                "departure_date": target["departure_date"],
                "param": option["saba_param"],
                "contains_any": option["contains_any"],
            }
            for option in filter_options
        ]
    target_query.pop("sort", None)
    task["parameters"]["target_query_example"] = target_query
    return task


def save_instance(task):
    STATE_DIR.mkdir(exist_ok=True)
    path = STATE_DIR / f"{task['id']}.json"
    path.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


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


def clear_runtime_environment(serial):
    adb_shell(serial, "input keyevent HOME", check=False)
    adb_shell(serial, f"am force-stop {PACKAGE}", check=False)
    adb_shell(serial, "am kill-all", check=False)
    adb_shell(serial, "input keyevent HOME", check=False)


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
    if "sort" in expected:
        details["sort"] = any(
            query.get("sort", {}).get("id") == expected["sort"].get("id")
            or query.get("sort", {}).get("name") == expected["sort"].get("name")
            for query in queries
        )
    if "travel_purpose" in expected:
        details["travel_purpose"] = field_ok("travel_purpose")
    return details


def latest_saba_urls(serial):
    command = (
        "for f in /data/user/0/com.booking/cache/saba-http-cache/*; do "
        "strings \"$f\" 2>/dev/null | grep -E '^https?://.*mobile\\.saba' | "
        "while read u; do echo \"$(stat -c %Y \"$f\") $u\"; done; "
        "done | sort -nr"
    )
    lines = adb_shell(serial, command, check=False).splitlines()
    return [line.split(" ", 1)[1] for line in lines if " " in line]


def saba_query_matches(serial, expected):
    if isinstance(expected, list):
        return all(saba_query_matches(serial, item) for item in expected)
    for url in latest_saba_urls(serial):
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if expected.get("arrival_date") and query.get("arrival_date", [""])[0] != expected["arrival_date"]:
            continue
        if expected.get("departure_date") and query.get("departure_date", [""])[0] != expected["departure_date"]:
            continue
        if expected.get("destination") and expected["destination"].lower() not in unquote(url).lower():
            continue
        value = query.get(expected["param"], [""])[0] if expected.get("param") else ""
        haystack = unquote(value).lower()
        raw_haystack = (value + " " + url).lower()
        return any(token.lower() in haystack or token.lower() in raw_haystack for token in expected["contains_any"])
    return False


def init_task(serial, task):
    ensure_device(serial)
    clear_runtime_environment(serial)
    init = task.get("init", {})
    if init.get("clear_saba_cache"):
        adb_shell(serial, "rm -f /data/user/0/com.booking/cache/saba-http-cache/*", check=False)
    if "query" in init:
        set_query(serial, init["query"])
    if "prefs" in init:
        update_xml_values(serial, PREFS_PATH, init["prefs"])
    if "gdpr" in init:
        update_xml_values(serial, GDPR_PATH, init["gdpr"])
    if "permissions" in init:
        init_permissions(serial, init["permissions"])
    clear_runtime_environment(serial)


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
    if "latest_saba_query" in verify:
        checks["latest_saba_query"] = saba_query_matches(serial, verify["latest_saba_query"])

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
    materialize_parser = sub.add_parser("materialize")
    materialize_parser.add_argument("template_id")
    materialize_parser.add_argument("--seed", type=int)
    materialize_parser.add_argument("--id", dest="instance_id")
    materialize_parser.add_argument("--init", action="store_true", help="Initialize the generated task immediately")
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
        for template in suite.get("task_templates", []):
            print(f"{template['id']}\tTEMPLATE:{template['category']}\t{template['description']}")
        return

    if args.command == "materialize":
        template = find_template(suite, args.template_id)
        task = materialize_template(suite, template, seed=args.seed, instance_id=args.instance_id)
        path = save_instance(task)
        if args.init:
            init_task(args.serial, task)
        print(json.dumps({"task_id": task["id"], "path": str(path), "instruction": task["instruction"]}, ensure_ascii=False, indent=2))
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
