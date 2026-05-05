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
SUITE_PATH = ROOT / "suites" / "qqmusic_app_tasks.json"
STATE_DIR = ROOT / ".task_state"
PACKAGE = "com.tencent.qqmusic"
APP_ROOT = f"/data/user/0/{PACKAGE}"
PLAYER_PREF = f"{APP_ROOT}/shared_prefs/qqmusicplayer.xml"
VIDEO_PREF = f"{APP_ROOT}/shared_prefs/FILE_KEY_VIDEO_AUTO_PLAY_SETTING.xml"
SOUND_PREF = f"{APP_ROOT}/shared_prefs/SuperSound.xml"
QQMUSIC_DB = f"{APP_ROOT}/databases/QQMusic"
SUITE_PREFIX = "openend_qqmusic_"


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
    return adb_shell(serial, f"sqlite3 {shlex.quote(QQMUSIC_DB)} {quoted}", check=False).strip()


def sqlite_exec(serial, sql):
    quoted = shlex.quote(sql)
    adb_shell(serial, f"sqlite3 {shlex.quote(QQMUSIC_DB)} {quoted}", check=False)


def permission_granted(serial, permission):
    output = adb_shell(serial, f"dumpsys package {PACKAGE}")
    for line in output.splitlines():
        if permission in line and "granted=" in line:
            return "granted=true" in line
    return False


def set_permission(serial, permission, target):
    action = "grant" if target else "revoke"
    adb_shell(serial, f"pm {action} {PACKAGE} {permission}", check=False)


def clear_runtime_environment(serial):
    adb_shell(serial, "input keyevent HOME", check=False)
    adb_shell(serial, f"am force-stop {PACKAGE}", check=False)
    adb_shell(serial, "am kill-all", check=False)
    adb_shell(serial, "input keyevent HOME", check=False)


def song_params(template, rng):
    return dict(rng.choice(template["parameters"]["songs"]))


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

    if template["id"] == "qqmusic_play_song_random":
        song = song_params(template, rng)
        task.update({
            "instruction": template["instruction_template"].format(song_name=song["song_name"]),
            "parameters": song,
            "init": {"sqlite_delete": [{
                "table": "PlaySongHistoryTable",
                "where": f"songId = {song['id']}"
            }]},
            "verify": {"sqlite_exists": [{
                "table": "PlaySongHistoryTable",
                "where": f"songId = {song['id']}",
                "weight": "play_history"
            }]}
        })
    elif template["id"] == "qqmusic_like_song_random":
        song = song_params(template, rng)
        folder = template["parameters"]["favorite_folder"]
        task.update({
            "instruction": template["instruction_template"].format(song_name=song["song_name"]),
            "parameters": {**song, "folderid": folder["folderid"], "folder_uin": folder["uin"]},
            "init": {"sqlite_delete": [{
                "table": "User_Folder_Song_table",
                "where": f"id = {song['id']} and folderid = {folder['folderid']}"
            }]},
            "verify": {"sqlite_exists": [{
                "table": "User_Folder_Song_table",
                "where": f"id = {song['id']} and folderid = {folder['folderid']}",
                "weight": "liked_song"
            }]}
        })
    elif template["id"] == "qqmusic_download_song_random":
        song = song_params(template, rng)
        task.update({
            "instruction": template["instruction_template"].format(song_name=song["song_name"]),
            "parameters": song,
            "init": {"sqlite_delete": [
                {"table": "download_song_table", "where": f"d_songid = {song['id']}"},
                {"table": "downloads", "where": f"song_name_sort = {sql_quote(song['song_name'])} or new_text_1 = {sql_quote(song['song_name'])}"}
            ]},
            "verify": {"sqlite_exists": [
                {
                    "table": "download_song_table",
                    "where": f"d_songid = {song['id']}",
                    "weight": "download_record"
                },
                {
                    "table": "downloads",
                    "where": f"song_name_sort = {sql_quote(song['song_name'])} or new_text_1 = {sql_quote(song['song_name'])}",
                    "weight": "download_record"
                }
            ], "match_any": True}
        })
    elif template["id"] == "qqmusic_play_mode_random":
        option = dict(rng.choice(template["parameters"]["options"]))
        task.update({
            "instruction": template["instruction_template"].format(mode_zh=option["mode_zh"]),
            "parameters": option,
            "init": {"prefs": [{"path": PLAYER_PREF, "values": {"playmode": option["baseline"]}}]},
            "verify": {"prefs": [{"path": PLAYER_PREF, "key": "playmode", "equals": option["target"], "weight": "playmode"}]}
        })
    elif template["id"] == "qqmusic_video_autoplay_random":
        option = dict(rng.choice(template["parameters"]["options"]))
        task.update({
            "instruction": template["instruction_template"].format(target_zh=option["target_zh"]),
            "parameters": option,
            "init": {"prefs": [{"path": VIDEO_PREF, "values": {"KEY_VIDEO_AUTO_PLAY_SETTING": option["baseline"]}}]},
            "verify": {"prefs": [{"path": VIDEO_PREF, "key": "KEY_VIDEO_AUTO_PLAY_SETTING", "equals": option["target"], "weight": "video_autoplay"}]}
        })
    elif template["id"] == "qqmusic_sound_effect_random":
        option = dict(rng.choice(template["parameters"]["options"]))
        task.update({
            "instruction": template["instruction_template"].format(effect_zh=option["effect_zh"]),
            "parameters": option,
            "init": {"prefs": [{"path": SOUND_PREF, "values": {"EffectTypeSetting": option["baseline"]}}]},
            "verify": {"prefs": [{"path": SOUND_PREF, "key": "EffectTypeSetting", "equals": option["target"], "weight": "sound_effect"}]}
        })
    elif template["id"] == "qqmusic_permission_random":
        option = dict(rng.choice(template["parameters"]["options"]))
        task.update({
            "instruction": template["instruction_template"].format(action_zh=option["action_zh"], permission_zh=option["permission_zh"]),
            "parameters": option,
            "init": {"permissions": [{"permission": option["permission"], "granted": not option["target"]}]},
            "verify": {"permissions": [{"permission": option["permission"], "granted": option["target"], "weight": "runtime_permission"}]}
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
    clear_runtime_environment(serial)
    init = task.get("init", {})
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
        checks.append({
            "name": pref["weight"],
            "passed": actual == pref["equals"],
            "expected": pref["equals"],
            "actual": actual,
            "weight": weights.get(pref["weight"], 0)
        })

    for perm in task.get("verify", {}).get("permissions", []):
        actual = permission_granted(serial, perm["permission"])
        checks.append({
            "name": perm["weight"],
            "passed": actual == perm["granted"],
            "expected": perm["granted"],
            "actual": actual,
            "weight": weights.get(perm["weight"], 0)
        })

    sqlite_checks = []
    for exists in task.get("verify", {}).get("sqlite_exists", []):
        raw = sqlite_scalar(serial, f"select count(*) from {exists['table']} where {exists['where']};")
        try:
            count = int(raw.splitlines()[-1] or "0")
        except ValueError:
            count = 0
        sqlite_checks.append({
            "name": exists["weight"],
            "passed": count > 0,
            "expected": "count > 0",
            "actual": count,
            "weight": weights.get(exists["weight"], 0)
        })
    if task.get("verify", {}).get("match_any") and sqlite_checks:
        passed = any(item["passed"] for item in sqlite_checks)
        weight_name = sqlite_checks[0]["name"]
        checks.append({
            "name": weight_name,
            "passed": passed,
            "expected": "any count > 0",
            "actual": [item["actual"] for item in sqlite_checks],
            "weight": weights.get(weight_name, 0)
        })
    else:
        checks.extend(sqlite_checks)

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
