"""Unit tests for tend. Run with `python3 -m unittest discover tests`.

launchd, lsof, ps and docker are replaced with fakes, so the tests run anywhere and touch nothing
outside a temporary HOME.
"""

import contextlib
import importlib.util
import io
import os
import plistlib
import tempfile
import time
import types
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
HOME = tempfile.mkdtemp(prefix="tend-test-home-")
# tend computes its state and log folders from HOME when it's loaded.
os.environ["HOME"] = HOME
_loader = SourceFileLoader("tend", str(ROOT / "tend"))
tend = importlib.util.module_from_spec(importlib.util.spec_from_loader("tend", _loader))
_loader.exec_module(tend)


def add_job(name, command, directory="/work/app"):
    tend.JOBS.mkdir(parents=True, exist_ok=True)
    with open(tend.plist_path(name), "wb") as f:
        plistlib.dump(
            {
                "Label": tend.label(name),
                "ProgramArguments": ["/bin/sh", "-c", command],
                "WorkingDirectory": directory,
                "StandardOutPath": str(tend.log_path(name)),
                "StandardErrorPath": str(tend.log_path(name)),
            },
            f,
        )


def write_log(name, text):
    tend.LOGS.mkdir(parents=True, exist_ok=True)
    tend.log_path(name).write_text(text)


class TendTest(unittest.TestCase):
    def setUp(self):
        for folder in (tend.JOBS, tend.LOGS):
            if folder.exists():
                for path in folder.iterdir():
                    path.unlink()
        os.environ.pop("TEND_THEME", None)
        os.environ.pop("TEND_FZF_COLORS", None)
        # No job is loaded in launchd unless a test says otherwise.
        patcher = mock.patch.object(tend, "job_status", return_value=(None, None))
        self.job_status = patcher.start()
        self.addCleanup(patcher.stop)


class ComposeParsingTest(TendTest):
    def test_compose_prefix(self):
        cases = {
            "docker compose up": ["docker", "compose"],
            "docker compose -f infra/db.yml -p x up --build": ["docker", "compose", "-f", "infra/db.yml", "-p", "x"],
            "docker-compose up": ["docker-compose"],
            "docker compose -f 'a b.yml' up": ["docker", "compose", "-f", "a b.yml"],
            "pnpm db:up && docker compose up": None,
            "docker compose logs -f": None,
            "npm run dev": None,
            "docker compose up 'unterminated": None,
        }
        for command, expected in cases.items():
            with self.subTest(command=command):
                self.assertEqual(tend.compose_prefix(command), expected)

    def test_project_dir(self):
        cases = [
            (["docker", "compose"], "/a"),
            (["docker", "compose", "-f", "infra/x.yml"], "/a/infra"),
            (["docker", "compose", "--file=b/y.yml"], "/a/b"),
            (["docker", "compose", "--project-directory", "../c", "-f", "x/y.yml"], "/c"),
            (["docker", "compose", "--project-directory=d"], "/a/d"),
        ]
        for prefix, expected in cases:
            with self.subTest(prefix=prefix):
                self.assertEqual(tend.project_dir("/a", prefix), expected)

    def test_compose_ports_matches_the_job_project(self):
        add_job("root", "docker compose up", "/work/app")
        add_job("infra", "docker compose -f infra/compose.yml up", "/work/app")
        containers = {
            "/work/app": [("Up 2 seconds", "0.0.0.0:8080->80/tcp")],
            "/work/app/infra": [("Up 2 seconds", "0.0.0.0:5432->5432/tcp, [::]:5432->5432/tcp")],
        }
        self.job_status.return_value = (42, None)
        with mock.patch.object(tend, "compose_containers", return_value=containers), mock.patch.object(
            tend, "started", return_value=None
        ):
            ports = {job["name"]: job["ports"] for job in tend.jobs()}
        self.assertEqual(ports, {"infra": [5432], "root": [8080]})


class NamesTest(TendTest):
    def test_patterns_and_exact_names(self):
        for name in ("pf-api", "pf-db", "pf-web", "other"):
            add_job(name, "npm run dev")
        self.assertEqual(tend.names(["pf*"]), ["pf-api", "pf-db", "pf-web"])
        self.assertEqual(tend.names(["pf-web", "pf*"]), ["pf-web", "pf-api", "pf-db"])
        self.assertEqual(tend.names(["other"]), ["other"])

    def test_errors(self):
        add_job("pf-api", "npm run dev")
        with self.assertRaisesRegex(tend.TendError, "no jobs match"):
            tend.names(["zz*"])
        with self.assertRaisesRegex(tend.TendError, "no such job"):
            tend.names(["missing"])
        with self.assertRaisesRegex(tend.TendError, "lowercase"):
            tend.names(["Bad Name"])


class OrderTest(TendTest):
    def setUp(self):
        super().setUp()
        add_job("pf-api", "dotnet run")
        add_job("pf-db", "docker compose up")
        add_job("pf-web", "npm run dev")

    def test_compose_starts_first_and_stops_last(self):
        selected = ["pf-api", "pf-db", "pf-web"]
        self.assertEqual(tend.start_order(selected), ["pf-db", "pf-api", "pf-web"])
        self.assertEqual(tend.stop_order(selected), ["pf-api", "pf-web", "pf-db"])

    def test_restart_stops_everything_then_waits_for_compose(self):
        events = []
        with mock.patch.object(tend, "stop_job", side_effect=lambda n, volumes=False: events.append(f"stop {n}")), \
                mock.patch.object(tend, "load", side_effect=lambda n, banner, mode: events.append(f"start {n}") or n), \
                mock.patch.object(tend, "wait_ready", side_effect=lambda n: events.append(f"wait {n}")), \
                contextlib.redirect_stdout(io.StringIO()):
            list(tend.restart_plan(["pf-api", "pf-db", "pf-web"]))
        self.assertEqual(
            events,
            ["stop pf-api", "stop pf-web", "stop pf-db", "start pf-db", "wait pf-db", "start pf-api", "start pf-web"],
        )

    def test_restart_of_compose_alone_doesnt_wait(self):
        with mock.patch.object(tend, "stop_job"), mock.patch.object(tend, "load", return_value="ok"), \
                mock.patch.object(tend, "wait_ready") as wait:
            list(tend.restart_plan(["pf-db"]))
        wait.assert_not_called()


class WaitReadyTest(TendTest):
    def setUp(self):
        super().setUp()
        add_job("db", "docker compose up", "/work/app")
        self.job_status.return_value = (42, None)
        patcher = mock.patch.object(tend.time, "sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_with(self, *polls):
        states = [{"/work/app": [(status, "") for status in poll]} for poll in polls]
        with mock.patch.object(tend, "compose_containers", side_effect=states) as containers:
            tend.wait_ready("db")
        return containers.call_count

    def test_waits_for_health_and_a_stable_container_count(self):
        polls = self.run_with(
            [],
            ["Up 1 second (health: starting)"],
            ["Up 2 seconds (healthy)"],
            ["Up 3 seconds (healthy)", "Up 1 second"],
            ["Up 4 seconds (healthy)", "Up 2 seconds"],
        )
        self.assertEqual(polls, 5)

    def test_unhealthy_fails(self):
        with self.assertRaisesRegex(tend.TendError, "unhealthy"):
            self.run_with(["Up 5 seconds (unhealthy)"])

    def test_exited_job_fails(self):
        self.job_status.return_value = (0, 1)
        with self.assertRaisesRegex(tend.TendError, "exited before"):
            self.run_with(["Up 1 second"])


class CandidatesTest(TendTest):
    def test_scripts_projects_and_compose_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"scripts": {"dev": "vite", "build": "vite build"}}')
            (root / "pnpm-lock.yaml").touch()
            (root / "compose.yaml").touch()
            (root / "docker-compose.yml").touch()
            for path in ("src/Api/Api.csproj", "node_modules/x/X.csproj", "a/b/c/d/Deep.csproj", "infra/compose.yml"):
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                (root / path).touch()
            found = [command for command, _ in tend.candidates(root)]
        self.assertEqual(
            found,
            [
                "pnpm run dev",
                "pnpm run build",
                "docker compose up",
                "docker compose -f infra/compose.yml up",
                "dotnet run --project src/Api/Api.csproj",
            ],
        )


class UrlTest(TendTest):
    def url(self, log, ports):
        add_job("web", "npm run dev")
        write_log("web", log)
        with mock.patch.object(tend, "jobs", return_value=iter([{"ports": ports}])):
            return tend.job_url("web")

    def test_vite_url_with_colors_from_the_current_run(self):
        log = (
            "old run http://localhost:9999/\n"
            "2026 tend: restarted: npm run dev\n"
            "  \x1b[1mLocal\x1b[22m:   \x1b[36mhttp://localhost:\x1b[1m5173\x1b[22m/app/\x1b[39m\n"
            "  Network: http://192.168.1.4:5173/\n"
        )
        self.assertEqual(self.url(log, [5173]), "http://localhost:5173/app/")

    def test_only_listening_ports_count(self):
        log = "2026 tend: started: dotnet run\nNow listening on: https://localhost:7001\nNow listening on: http://localhost:5126\n"
        self.assertEqual(self.url(log, [5126]), "http://localhost:5126")

    def test_fallback_and_nothing(self):
        self.assertEqual(self.url("2026 tend: started: x\nready\n", [8080]), "http://localhost:8080")
        self.assertIsNone(self.url("2026 tend: started: x\n", []))


class TableTest(TendTest):
    def test_fzf_rows_hide_nothing_and_put_the_directory_last(self):
        job = {
            "name": "pf-api", "state": "running", "since": "14:02", "exit_code": None, "ports": [5126],
            "dir": "/work/api", "command": "dotnet run", "busy": None,
        }
        busy = {**job, "name": "pf-db", "busy": "stopping", "ports": []}
        with mock.patch.object(tend, "jobs", return_value=[job, busy]):
            header, api, db = (line.split("\t") for line in tend.table(fzf=True))
        self.assertEqual([cell.strip() for cell in header], ["", "NAME", "STATUS", "PORTS", "COMMAND", "DIR"])
        self.assertEqual([cell.strip() for cell in api], ["●", "pf-api", "up since 14:02", "5126", "dotnet run", "/work/api"])
        self.assertEqual([cell.strip() for cell in db][:3], ["◐", "pf-db", "stopping…"])


class ThemeTest(TendTest):
    def test_frappe_is_the_default(self):
        self.assertIn("38;2;166;209;137m", tend.paint("x", "green"))
        self.assertIn(tend.FZF_COLORS, tend.style())

    def test_terminal_theme_leaves_fzf_colors_alone(self):
        os.environ["TEND_THEME"] = "terminal"
        self.assertEqual(tend.paint("x", "green"), "\x1b[32mx\x1b[0m")
        self.assertNotIn("--color", tend.style())

    def test_fzf_color_override_comes_after_the_theme(self):
        os.environ["TEND_FZF_COLORS"] = "pointer:#ff0000"
        options = tend.style()
        self.assertGreater(options.index("pointer:#ff0000"), options.index(tend.FZF_COLORS))


class LaunchTest(TendTest):
    def supervisor(self, name):
        return ["/bin/sh", "-c", tend.SUPERVISE, name, str(tend.busy_path(name))]

    def test_direnv_when_installed(self):
        with mock.patch.object(tend.shutil, "which", return_value="/bin/direnv"):
            args = tend.launch_args("web", Path("/work/app"), "npm run dev")
        launcher = ["/bin/sh", "-c", tend.DIRENV_LAUNCH, "/bin/direnv", "/work/app", "npm run dev"]
        self.assertEqual(args, self.supervisor("web") + launcher)
        self.assertEqual(tend.unsupervised(args), launcher)

    def test_plain_sh_without_direnv(self):
        with mock.patch.object(tend.shutil, "which", return_value=None):
            args = tend.launch_args("web", Path("/work/app"), "npm run dev")
        self.assertEqual(args, self.supervisor("web") + ["/bin/sh", "-c", "npm run dev"])

    def test_jobs_from_before_the_supervisor(self):
        old = ["/usr/bin/fish", "--login", "-c", "exec direnv exec $argv[1] /bin/sh -c $argv[2]", "/w", "npm run dev"]
        self.assertFalse(tend.supervised(old))
        self.assertEqual(tend.unsupervised(old), old)

    def test_stop_marks_the_job_busy_so_its_exit_isnt_a_crash(self):
        add_job("web", "npm run dev")
        seen = []
        with mock.patch.object(tend, "unload", side_effect=lambda name, timeout=10: seen.append(tend.busy_path(name).read_text())):
            tend.stop_job("web")
        self.assertEqual(seen, ["stopping"])
        self.assertFalse(tend.busy_path("web").exists())

    def test_keep_alive_and_saved_env_in_the_plist(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(tend.Path, "cwd", return_value=Path(tmp)), \
                mock.patch.object(tend, "load", return_value="started"), mock.patch.object(tend, "unload"), \
                mock.patch.dict(os.environ, {"PATH": "/custom/bin:/usr/bin"}), contextlib.redirect_stdout(io.StringIO()):
            tend.cmd_run(types.SimpleNamespace(command=["npm run dev"], name="web", keep_alive=True))
        job = tend.read_job("web")
        self.assertEqual(job["KeepAlive"], {"SuccessfulExit": False})
        self.assertEqual(job["EnvironmentVariables"]["PATH"], "/custom/bin:/usr/bin")
        self.assertTrue(tend.supervised(job["ProgramArguments"]))

    def test_compose_stop_runs_down_through_the_job_launcher(self):
        with mock.patch.object(tend.shutil, "which", return_value=None):
            arguments = tend.launch_args("db", Path("/work/app"), "docker compose -p x up")
        add_job("db", "docker compose -p x up")
        job = tend.read_job("db")
        job["ProgramArguments"] = arguments
        with open(tend.plist_path("db"), "wb") as f:
            plistlib.dump(job, f)
        with mock.patch.object(tend.subprocess, "run") as run, mock.patch.object(tend, "unload") as unload:
            run.return_value.returncode = 0
            tend.stop_job("db", volumes=True)
        self.assertEqual(run.call_args.args[0], ["/bin/sh", "-c", "docker compose -p x down -v"])
        unload.assert_called_once_with("db", tend.COMPOSE_TIMEOUT)

    def test_volumes_only_for_compose(self):
        add_job("web", "npm run dev")
        with self.assertRaisesRegex(tend.TendError, "only applies"):
            tend.stop_job("web", volumes=True)


class RenameTest(TendTest):
    def test_moves_plist_and_log(self):
        add_job("old", "npm run dev")
        job = tend.read_job("old")
        with mock.patch.object(tend.shutil, "which", return_value=None):
            job["ProgramArguments"] = tend.launch_args("old", Path("/work/app"), "npm run dev")
        with open(tend.plist_path("old"), "wb") as f:
            plistlib.dump(job, f)
        tend.ports_path("old").write_text("[5173]")
        write_log("old", "hello\n")
        with mock.patch.object(tend, "unload"):
            tend.rename("old", "new")
        job = tend.read_job("new")
        self.assertEqual(job["Label"], "local.tend.new")
        self.assertEqual(job["ProgramArguments"][3:5], ["new", str(tend.busy_path("new"))])
        self.assertEqual(job["StandardOutPath"], str(tend.log_path("new")))
        self.assertEqual(tend.log_path("new").read_text(), "hello\n")
        self.assertFalse(tend.plist_path("old").exists())
        self.assertEqual(tend.ports_path("new").read_text(), "[5173]")

    def test_rejects_taken_and_invalid_names(self):
        add_job("old", "npm run dev")
        add_job("taken", "npm run dev")
        with self.assertRaisesRegex(tend.TendError, "already exists"):
            tend.rename("old", "taken")
        with self.assertRaisesRegex(tend.TendError, "lowercase"):
            tend.rename("old", "Bad Name")


class FzfKeyTest(TendTest):
    def key(self, key, name="", prompt=tend.PROMPT, query=""):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"FZF_PROMPT": prompt, "FZF_QUERY": query}), contextlib.redirect_stdout(out):
            tend.cmd_fzf_key(types.SimpleNamespace(key=key, name=name))
        return out.getvalue().strip()

    def test_normal_mode(self):
        self.assertEqual(self.key("enter", "web"), f"become({tend.SELF} logs -f web)")
        self.assertEqual(self.key("esc"), "abort")

    def test_rename_mode(self):
        add_job("web", "npm run dev")
        add_job("taken", "npm run dev")
        start = self.key("ctrl-e", "web")
        self.assertIn("disable-search", start)
        self.assertIn(f"change-prompt(rename web {tend.PROMPT})", start)
        prompt = f"rename web {tend.PROMPT}"
        self.assertEqual(self.key("esc", prompt=prompt), tend.NORMAL_MODE)
        self.assertEqual(self.key("enter", "web", prompt, "web"), tend.NORMAL_MODE)
        self.assertIn("already exists", self.key("enter", "web", prompt, "taken"))
        # Parentheses in the error would end fzf's action argument early.
        self.assertIn("'Bad x'", self.key("enter", "web", prompt, "Bad (x)"))
        with mock.patch.object(tend, "in_background") as background:
            done = self.key("enter", "other", prompt, "site")
        self.assertEqual(background.call_args.args[:2], (["web"], "renaming"))
        self.assertTrue(done.endswith(f"reload({tend.SELF} ls --fzf)"))


class LogTrimTest(TendTest):
    def test_cuts_a_long_log_to_whole_lines_at_its_end(self):
        lines = [f"line {i:06d}\n" for i in range(5000)]
        write_log("web", "".join(lines))
        with mock.patch.object(tend, "LOG_LIMIT", 20_000), mock.patch.object(tend, "LOG_KEEP", 5_000):
            tend.trim_log("web")
        kept = tend.log_path("web").read_text().splitlines(keepends=True)
        self.assertLessEqual(len("".join(kept)), 5_000)
        self.assertEqual(kept, lines[-len(kept):])

    def test_leaves_a_short_log_alone(self):
        write_log("web", "short\n")
        tend.trim_log("web")
        self.assertEqual(tend.log_path("web").read_text(), "short\n")


class PortConflictTest(TendTest):
    def test_names_the_process_holding_a_remembered_port(self):
        add_job("web", "npm run dev")
        tend.remember_ports("web", [5173, 5174])
        held = {5173: [("node", 4242)], 5174: []}
        with mock.patch.object(tend, "holders", side_effect=lambda port: held[port]):
            self.assertEqual(tend.port_conflicts("web"), ["web: port 5173 is in use by node (pid 4242)"])

    def test_no_remembered_ports(self):
        self.assertEqual(tend.port_conflicts("web"), [])


class SinceTest(TendTest):
    def test_today_is_a_time_and_earlier_is_a_date(self):
        now = time.time()
        self.assertEqual(tend.since(now), time.strftime("%H:%M", time.localtime(now)))
        self.assertRegex(tend.since(now - 3 * 86400), r"^[A-Z][a-z]{2} \d{1,2}$")


class RefreshTest(TendTest):
    def refresh(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            tend.cmd_fzf_key(types.SimpleNamespace(key="refresh", name=""))
        return out.getvalue().strip()

    def test_reloads_only_when_rows_change(self):
        add_job("web", "npm run dev")
        with mock.patch.dict(os.environ, {"FZF_PORT": "test-refresh"}):
            tend.rows_cache().unlink(missing_ok=True)
            self.assertTrue(self.refresh().startswith("reload(cat "))
            self.assertEqual(self.refresh(), "")
            add_job("api", "dotnet run")
            self.assertTrue(self.refresh().startswith("reload(cat "))
            tend.rows_cache().unlink()


class CompleteTest(TendTest):
    def test_jobs_with_descriptions(self):
        add_job("web", "npm run dev")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            tend.cmd_complete(types.SimpleNamespace(what="jobs"))
        self.assertEqual(out.getvalue(), "web\tstopped: npm run dev\n")


if __name__ == "__main__":
    unittest.main()
