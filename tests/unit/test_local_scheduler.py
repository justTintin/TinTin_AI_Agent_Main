"""tests/unit/test_local_scheduler.py — 本地定时任务管理测试。"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import testutil

testutil.ensure_studio_on_path()


class TestParseQueryInfo(unittest.TestCase):
    """_parse_query_info schtasks 输出解析测试。"""

    def test_parse_basic_output(self):
        from utils.local_scheduler import _parse_query_info
        out = (
            "下次运行时间: 2026/08/21 09:00:00\n"
            "上次运行时间: 2026/08/20 09:00:00\n"
            "上次结果: 0 (0x0)\n"
            "状态: 就绪\n"
        )
        info = _parse_query_info(out)
        self.assertEqual(info["下次运行时间"], "2026/08/21 09:00:00")
        self.assertEqual(info["上次运行时间"], "2026/08/20 09:00:00")
        self.assertEqual(info["上次结果"], "0 (0x0)")
        self.assertEqual(info["状态"], "就绪")

    def test_parse_english_output(self):
        from utils.local_scheduler import _parse_query_info
        out = (
            "Next Run Time: 8/21/2026 9:00:00 AM\n"
            "Last Run Time: 8/20/2026 9:00:00 AM\n"
            "Last Result: 0x41303\n"
            "Status: Ready\n"
        )
        info = _parse_query_info(out)
        self.assertEqual(info["Next Run Time"], "8/21/2026 9:00:00 AM")
        self.assertEqual(info["Last Run Time"], "8/20/2026 9:00:00 AM")
        self.assertEqual(info["Last Result"], "0x41303")
        self.assertEqual(info["Status"], "Ready")

    def test_parse_empty_lines(self):
        from utils.local_scheduler import _parse_query_info
        out = "Line without colon\n\n"
        info = _parse_query_info(out)
        self.assertEqual(info, {})

    def test_parse_key_only_no_value(self):
        from utils.local_scheduler import _parse_query_info
        out = "状态:\n"
        info = _parse_query_info(out)
        self.assertNotIn("状态", info)


class TestResultText(unittest.TestCase):
    """_result_text 结果码转文本测试。"""

    def test_success_zero(self):
        from utils.local_scheduler import _result_text
        self.assertEqual(_result_text("0"), "成功")

    def test_success_hex(self):
        from utils.local_scheduler import _result_text
        self.assertEqual(_result_text("0x0"), "成功")

    def test_never_run_decimal(self):
        from utils.local_scheduler import _result_text
        self.assertEqual(_result_text("267011"), "尚未运行")

    def test_never_run_hex(self):
        from utils.local_scheduler import _result_text
        self.assertEqual(_result_text("0x41303"), "尚未运行")

    def test_never_run_short(self):
        from utils.local_scheduler import _result_text
        self.assertEqual(_result_text("41303"), "尚未运行")

    def test_empty(self):
        from utils.local_scheduler import _result_text
        self.assertEqual(_result_text(""), "—")

    def test_none(self):
        from utils.local_scheduler import _result_text
        self.assertEqual(_result_text(None), "—")

    def test_unknown(self):
        from utils.local_scheduler import _result_text
        self.assertEqual(_result_text("1"), "1")

    def test_with_parentheses(self):
        from utils.local_scheduler import _result_text
        self.assertEqual(_result_text("(0)"), "成功")


class TestScheduleText(unittest.TestCase):
    """_schedule_text 调度配置展示测试。"""

    def test_daily_schedule(self):
        from utils.local_scheduler import _schedule_text
        result = _schedule_text({"mode": "daily", "time": "09:00"})
        self.assertEqual(result, "每天 09:00")

    def test_weekly_with_days(self):
        from utils.local_scheduler import _schedule_text
        result = _schedule_text({"mode": "weekly", "time": "10:30", "weekdays": [0, 2, 4]})
        self.assertEqual(result, "每周 周一、三、五 10:30")

    def test_weekly_no_days(self):
        from utils.local_scheduler import _schedule_text
        result = _schedule_text({"mode": "weekly", "time": "10:30", "weekdays": []})
        self.assertEqual(result, "每周 10:30")

    def test_default_schedule(self):
        from utils.local_scheduler import _schedule_text
        result = _schedule_text({})
        self.assertEqual(result, "每天 ")

    def test_none_schedule(self):
        from utils.local_scheduler import _schedule_text
        result = _schedule_text(None)
        self.assertEqual(result, "每天 ")

    def test_invalid_weekdays(self):
        from utils.local_scheduler import _schedule_text
        result = _schedule_text({"mode": "weekly", "time": "09:00", "weekdays": [7, -1, 3]})
        self.assertEqual(result, "每周 周四 09:00")


class TestCreateTask(unittest.TestCase):
    """create_task 任务创建测试。"""

    def test_invalid_mode(self):
        from utils.local_scheduler import create_task
        ok, msg = create_task("test", schedule={"mode": "hourly", "time": "10:00"})
        self.assertFalse(ok)
        self.assertIn("不支持的调度方式", msg)

    def test_invalid_task_type(self):
        from utils.local_scheduler import create_task
        ok, msg = create_task("test", task_type="unknown_type")
        self.assertFalse(ok)
        self.assertIn("不支持的本地任务类型", msg)

    def test_agent_missing_goal(self):
        from utils.local_scheduler import create_task
        ok, msg = create_task("test", task_type="agent")
        self.assertFalse(ok)
        self.assertIn("需要任务描述", msg)

    def test_invalid_time_format(self):
        from utils.local_scheduler import create_task
        ok, msg = create_task("test", schedule={"mode": "daily", "time": "invalid"})
        self.assertFalse(ok)
        self.assertIn("时间格式应为 HH:MM", msg)

    def test_empty_name(self):
        from utils.local_scheduler import create_task
        ok, msg = create_task("")
        self.assertFalse(ok)
        self.assertIn("任务名称不能为空", msg)

    def test_default_time(self):
        from utils.local_scheduler import create_task
        with mock.patch("utils.local_scheduler._load", return_value=[]), \
             mock.patch("utils.local_scheduler._schtasks", return_value=(0, "")), \
             mock.patch("utils.local_scheduler._save", return_value=True), \
             mock.patch("utils.local_scheduler.PYTHON_EMBEDED_DIR", "/fake/python"), \
             mock.patch("os.path.isfile", return_value=True):
            ok, msg = create_task("test")
        self.assertTrue(ok)
        self.assertIn("TinTinAI_test", msg)

    def test_invalid_weekdays(self):
        from utils.local_scheduler import create_task
        ok, msg = create_task("test", schedule={"mode": "weekly", "time": "10:00", "weekdays": []})
        self.assertFalse(ok)
        self.assertIn("至少选择一个星期", msg)

    def test_special_chars_in_name(self):
        from utils.local_scheduler import create_task
        with mock.patch("utils.local_scheduler._load", return_value=[]), \
             mock.patch("utils.local_scheduler._schtasks", return_value=(0, "")), \
             mock.patch("utils.local_scheduler._save", return_value=True), \
             mock.patch("utils.local_scheduler.PYTHON_EMBEDED_DIR", "/fake/python"), \
             mock.patch("os.path.isfile", return_value=True):
            ok, msg = create_task("test@#$%^&*()name")
        self.assertTrue(ok)

    def test_duplicate_task(self):
        from utils.local_scheduler import create_task
        with mock.patch("utils.local_scheduler._load", return_value=[{"task_name": "TinTinAI_test"}]):
            ok, msg = create_task("test")
        self.assertFalse(ok)
        self.assertIn("同名任务已存在", msg)

    def test_schtasks_failure(self):
        from utils.local_scheduler import create_task
        with mock.patch("utils.local_scheduler._load", return_value=[]), \
             mock.patch("utils.local_scheduler._schtasks", return_value=(1, "Access denied")), \
             mock.patch("utils.local_scheduler.PYTHON_EMBEDED_DIR", "/fake/python"), \
             mock.patch("os.path.isfile", return_value=True):
            ok, msg = create_task("test")
        self.assertFalse(ok)
        self.assertIn("Access denied", msg)

    def test_agent_task_with_plan(self):
        from utils.local_scheduler import create_task
        with mock.patch("utils.local_scheduler._load", return_value=[]), \
             mock.patch("utils.local_scheduler._schtasks", return_value=(0, "")), \
             mock.patch("utils.local_scheduler._save", return_value=True), \
             mock.patch("utils.local_scheduler.PYTHON_EMBEDED_DIR", "/fake/python"), \
             mock.patch("os.path.isfile", return_value=True):
            plan = {"goal": "test", "steps": [{"id": "s1"}]}
            ok, msg = create_task("agent_test", task_type="agent", goal="测试目标", plan=plan)
        self.assertTrue(ok)

    def test_weekly_task_creation(self):
        from utils.local_scheduler import create_task
        with mock.patch("utils.local_scheduler._load", return_value=[]), \
             mock.patch("utils.local_scheduler._schtasks", return_value=(0, "")), \
             mock.patch("utils.local_scheduler._save", return_value=True), \
             mock.patch("utils.local_scheduler.PYTHON_EMBEDED_DIR", "/fake/python"), \
             mock.patch("os.path.isfile", return_value=True):
            ok, msg = create_task("weekly_test", schedule={"mode": "weekly", "time": "14:00", "weekdays": [1, 3, 5]})
        self.assertTrue(ok)


class TestListTasks(unittest.TestCase):
    """list_tasks 任务列表测试。"""

    def test_empty_list(self):
        from utils.local_scheduler import list_tasks
        with mock.patch("utils.local_scheduler._load", return_value=[]):
            tasks = list_tasks()
        self.assertEqual(tasks, [])

    def test_with_registered_tasks(self):
        from utils.local_scheduler import list_tasks
        tasks_data = [{"task_name": "TinTinAI_test", "name": "test"}]
        schtasks_out = (
            "下次运行时间: 2026/08/21 09:00:00\n"
            "上次运行时间: 2026/08/20 09:00:00\n"
            "上次结果: 0 (0x0)\n"
        )
        with mock.patch("utils.local_scheduler._load", return_value=tasks_data), \
             mock.patch("utils.local_scheduler._schtasks", return_value=(0, schtasks_out)):
            tasks = list_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertTrue(tasks[0]["registered"])
        self.assertEqual(tasks[0]["next_run"], "2026/08/21 09:00:00")
        self.assertEqual(tasks[0]["last_result"], "0 (0x0)")

    def test_with_unregistered_tasks(self):
        from utils.local_scheduler import list_tasks
        tasks_data = [{"task_name": "TinTinAI_test", "name": "test"}]
        with mock.patch("utils.local_scheduler._load", return_value=tasks_data), \
             mock.patch("utils.local_scheduler._schtasks", return_value=(1, "not found")):
            tasks = list_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertFalse(tasks[0]["registered"])


class TestDeleteTask(unittest.TestCase):
    """delete_task 任务删除测试。"""

    def test_delete_existing(self):
        from utils.local_scheduler import delete_task
        tasks_data = [
            {"task_name": "TinTinAI_test", "name": "test"},
            {"task_name": "TinTinAI_other", "name": "other"},
        ]
        with mock.patch("utils.local_scheduler._load", return_value=tasks_data), \
             mock.patch("utils.local_scheduler._schtasks", return_value=(0, "")), \
             mock.patch("utils.local_scheduler._save", return_value=True):
            ok, msg = delete_task("test")
        self.assertTrue(ok)
        self.assertEqual(msg, "TinTinAI_test")

    def test_delete_by_task_name(self):
        from utils.local_scheduler import delete_task
        tasks_data = [{"task_name": "TinTinAI_test", "name": "test"}]
        with mock.patch("utils.local_scheduler._load", return_value=tasks_data), \
             mock.patch("utils.local_scheduler._schtasks", return_value=(0, "")), \
             mock.patch("utils.local_scheduler._save", return_value=True):
            ok, msg = delete_task("TinTinAI_test")
        self.assertTrue(ok)

    def test_delete_nonexistent(self):
        from utils.local_scheduler import delete_task
        with mock.patch("utils.local_scheduler._load", return_value=[]):
            ok, msg = delete_task("nonexistent")
        self.assertFalse(ok)
        self.assertIn("任务不在本地清单中", msg)

    def test_delete_schtasks_failure(self):
        from utils.local_scheduler import delete_task
        tasks_data = [{"task_name": "TinTinAI_test", "name": "test"}]
        with mock.patch("utils.local_scheduler._load", return_value=tasks_data), \
             mock.patch("utils.local_scheduler._schtasks", return_value=(1, "Access denied")):
            ok, msg = delete_task("test")
        self.assertFalse(ok)
        self.assertIn("Access denied", msg)


class TestRunNow(unittest.TestCase):
    """run_now 立即运行测试。"""

    def test_run_success(self):
        from utils.local_scheduler import run_now
        with mock.patch("utils.local_scheduler._schtasks", return_value=(0, "SUCCESS")):
            ok, msg = run_now("TinTinAI_test")
        self.assertTrue(ok)

    def test_run_failure(self):
        from utils.local_scheduler import run_now
        with mock.patch("utils.local_scheduler._schtasks", return_value=(1, "Access denied")):
            ok, msg = run_now("TinTinAI_test")
        self.assertFalse(ok)
        self.assertIn("Access denied", msg)


class TestLoadSave(unittest.TestCase):
    """_load / _save 读写测试。"""

    def test_save_and_load(self):
        from utils.local_scheduler import _load, _save, TASKS_FILE
        import tempfile
        import json
        tasks = [{"task_name": "TinTinAI_test", "name": "test"}]
        with mock.patch("utils.local_scheduler.TASKS_FILE", tempfile.mktemp(suffix=".json")):
            result = _save(tasks)
            self.assertTrue(result)
            loaded = _load()
            self.assertEqual(loaded, tasks)

    def test_load_missing_file(self):
        from utils.local_scheduler import _load
        with mock.patch("utils.local_scheduler.TASKS_FILE", "/nonexistent/tasks.json"):
            result = _load()
        self.assertEqual(result, [])

    def test_load_invalid_json(self):
        from utils.local_scheduler import _load
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("invalid json{{{")
            tmp_path = f.name
        try:
            with mock.patch("utils.local_scheduler.TASKS_FILE", tmp_path):
                result = _load()
            self.assertEqual(result, [])
        finally:
            os.unlink(tmp_path)

    def test_save_os_error(self):
        from utils.local_scheduler import _save
        with mock.patch("builtins.open", side_effect=OSError("disk full")):
            result = _save([{"task_name": "test"}])
        self.assertFalse(result)
