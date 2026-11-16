"""The ephemeral-world forge: backup choice, the read-only guard and the build plan.

Nothing here starts MySQL or touches a network. The plan is a list of steps and
the tests drive it with a recording runner.
"""

from __future__ import annotations

import gzip
import pathlib
import tempfile
import unittest
from unittest import mock

from forge import build, classes, restore, scrub

OLD = "wow-dev-characters-20261113T051002Z.sql.gz"
NEW = "wow-dev-characters-20261114T051003Z.sql.gz"


def write_dump(
    directory: pathlib.Path, name: str, complete: bool = True
) -> pathlib.Path:
    path = directory / name
    tail = (
        b"-- Dump completed on 2026-11-14\n"
        if complete
        else b"INSERT INTO t VALUES (1);\n"
    )
    with gzip.open(path, "wb") as handle:
        handle.write(b"CREATE DATABASE acore_characters;\n" + tail)
    return path


class NewestBackup(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_picks_the_newest_stamp(self) -> None:
        write_dump(self.dir, OLD)
        write_dump(self.dir, NEW)
        found = restore.newest_backup(self.dir)
        self.assertEqual((found.path.name, found.stamp), (NEW, "20261114T051003Z"))

    def test_ignores_partials_and_other_files(self) -> None:
        write_dump(self.dir, OLD)
        (self.dir / (NEW + ".partial")).write_bytes(b"x")
        (self.dir / "notes.txt").write_text("x")
        (self.dir / "wow-dev-characters-latest.sql.gz").write_bytes(b"x")
        self.assertEqual(restore.newest_backup(self.dir).path.name, OLD)

    def test_no_backup_is_an_error_not_an_empty_template(self) -> None:
        with self.assertRaises(restore.NoBackup):
            restore.newest_backup(self.dir)

    def test_a_truncated_dump_is_refused(self) -> None:
        path = write_dump(self.dir, NEW, complete=False)
        with self.assertRaises(restore.IncompleteDump):
            restore.verify_dump_complete(path)

    def test_a_complete_dump_passes(self) -> None:
        restore.verify_dump_complete(write_dump(self.dir, NEW))

    def test_a_file_that_is_not_gzip_is_refused(self) -> None:
        path = self.dir / NEW
        path.write_bytes(b"not gzip at all")
        with self.assertRaises(restore.IncompleteDump):
            restore.verify_dump_complete(path)

    def test_the_backup_is_never_opened_for_writing(self) -> None:
        path = write_dump(self.dir, NEW)
        before = path.stat().st_mtime_ns
        restore.verify_dump_complete(path)
        restore.newest_backup(self.dir)
        self.assertEqual(path.stat().st_mtime_ns, before)


class LocalOnly(unittest.TestCase):
    def test_loopback_hosts_are_allowed(self) -> None:
        for host in ("127.0.0.1", "localhost", "::1"):
            restore.assert_local_mysql(host)

    def test_any_other_host_is_refused(self) -> None:
        for host in ("mysql", "mysql.wow-dev.svc", "192.0.2.5", "db.example.com", ""):
            with self.assertRaises(restore.NotLocal, msg=host):
                restore.assert_local_mysql(host)

    def test_the_restore_command_pipes_the_dump_into_a_loopback_client(self) -> None:
        backup = restore.Backup(pathlib.Path("/backups") / OLD, "20261113T051002Z")
        argv = restore.restore_command(backup, port=3307)
        self.assertEqual(argv[:2], ["sh", "-c"])
        script = argv[2]
        self.assertIn("gunzip -c /backups/" + OLD, script)
        self.assertIn("-h127.0.0.1", script)
        self.assertIn("-P3307", script)
        self.assertNotIn("password", script.lower())
        self.assertNotRegex(script, r"\s-p")

    def test_a_dump_path_with_shell_metacharacters_is_quoted(self) -> None:
        backup = restore.Backup(
            pathlib.Path("/backups/a b;rm -rf x.sql.gz"), "20261113T051002Z"
        )
        script = restore.restore_command(backup, port=3306)[2]
        self.assertIn("'/backups/a b;rm -rf x.sql.gz'", script)


class Config(unittest.TestCase):
    def test_a_class_must_be_lean_or_full(self) -> None:
        with self.assertRaises(ValueError):
            build.Config(
                template_class="medium",
                backup_dir=pathlib.Path("/b"),
                workdir=pathlib.Path("/w"),
            )

    def test_a_non_loopback_mysql_host_is_refused_at_config_time(self) -> None:
        with self.assertRaises(restore.NotLocal):
            build.Config(
                template_class="full",
                backup_dir=pathlib.Path("/b"),
                workdir=pathlib.Path("/w"),
                mysql_host="mysql",
            )

    def test_a_workdir_must_be_a_plain_absolute_path(self) -> None:
        bad = (
            "relative/dir",
            "/with space/work",
            "/w;rm -rf /",
            "/w$(id)",
            "/w`id`",
            "/w'quote",
            '/w"quote',
            "/w|x",
            "/w&x",
            "/w\nnewline",
            "/w/../etc",
            "/",
            "",
        )
        for workdir in bad:
            with self.assertRaises(ValueError, msg=repr(workdir)):
                build.Config(
                    template_class="full",
                    backup_dir=pathlib.Path("/b"),
                    workdir=pathlib.PurePosixPath(workdir),
                )

    def test_ordinary_workdirs_are_accepted(self) -> None:
        for workdir in (
            "/w",
            "/var/lib/forge/work-1",
            "/var/lib/forge/work.d",
            "C:/work/forge",
        ):
            build.Config(
                template_class="full",
                backup_dir=pathlib.Path("/b"),
                workdir=pathlib.PurePosixPath(workdir),
            )

    def test_the_mysql_script_is_one_word_per_path_after_shell_splitting(self) -> None:
        import shlex

        cfg = build.Config(
            template_class="full",
            backup_dir=pathlib.Path("/b"),
            workdir=pathlib.PurePosixPath("/var/lib/forge/work-1"),
            registry="registry.example.invalid/eph",
        )
        with tempfile.TemporaryDirectory() as tmp:
            write_dump(pathlib.Path(tmp), NEW)
            cfg = build.Config(
                template_class="full",
                backup_dir=pathlib.Path(tmp),
                workdir=cfg.workdir,
                registry=cfg.registry,
            )
            step = next(
                s
                for s in build.plan(cfg, classes.load_classes())
                if s.name == "start-mysql"
            )
        words = shlex.split(step.argv[2])
        datadirs = [w for w in words if w.startswith("--datadir=")]
        self.assertEqual(datadirs, ["--datadir=/var/lib/forge/work-1/datadir"] * 2)

    def test_the_datadir_is_shell_quoted_in_the_script_text(self) -> None:
        import shlex

        with tempfile.TemporaryDirectory() as tmp:
            write_dump(pathlib.Path(tmp), NEW)
            cfg = build.Config(
                template_class="full",
                backup_dir=pathlib.Path(tmp),
                workdir=pathlib.PurePosixPath("/w"),
                registry="registry.example.invalid/eph",
            )
            step = next(
                s
                for s in build.plan(cfg, classes.load_classes())
                if s.name == "start-mysql"
            )
        self.assertIn(shlex.quote("--datadir=/w/datadir"), step.argv[2])

    def test_the_image_ref_uses_class_and_stamp(self) -> None:
        self.assertEqual(
            build.image_tag("lean", "20261114T051003Z"),
            "wow-eph-template:lean-20261114T051003Z",
        )

    def test_a_stamp_that_is_not_a_backup_stamp_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            build.image_tag("lean", "1; DROP TABLE x")


class Plan(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = pathlib.Path(self._tmp.name)
        write_dump(self.dir, NEW)
        self.classes = classes.load_classes(classes.DEFAULT_PATH)

    def plan(self, template_class: str, **kw) -> list[build.Step]:
        cfg = build.Config(
            template_class=template_class,
            backup_dir=self.dir,
            workdir=self.dir / "work",
            registry="registry.example.invalid/eph",
            **kw,
        )
        return build.plan(cfg, self.classes)

    def names(self, template_class: str, **kw) -> list[str]:
        return [s.name for s in self.plan(template_class, **kw)]

    def test_full_runs_every_stage_in_order_without_a_lean_trim(self) -> None:
        self.assertEqual(
            self.names("full"),
            [
                "verify-backup",
                "start-mysql",
                "restore",
                "db-import",
                "auth",
                "playerbots-scrub",
                "state-scrub",
                "marker",
                "credential-audit",
                "shutdown",
                "package",
                "push",
                "prune",
            ],
        )

    def test_lean_adds_the_trim_after_the_state_scrub(self) -> None:
        names = self.names("lean")
        self.assertIn("lean-trim", names)
        self.assertEqual(names.index("lean-trim"), names.index("state-scrub") + 1)

    def test_the_credential_audit_runs_before_the_datadir_is_packaged(self) -> None:
        names = self.names("lean")
        self.assertLess(names.index("credential-audit"), names.index("shutdown"))
        self.assertLess(names.index("credential-audit"), names.index("package"))
        self.assertLess(names.index("auth"), names.index("credential-audit"))

    def test_mysql_starts_with_the_throwaway_settings(self) -> None:
        step = next(s for s in self.plan("full") if s.name == "start-mysql")
        joined = " ".join(step.argv)
        for flag in (
            "--innodb-flush-log-at-trx-commit=0",
            "--skip-log-bin",
            "--innodb-doublewrite=0",
        ):
            self.assertIn(flag, joined)
        self.assertIn("--bind-address=127.0.0.1", joined)

    def test_shutdown_is_a_clean_slow_shutdown(self) -> None:
        step = next(s for s in self.plan("full") if s.name == "shutdown")
        self.assertIn("innodb_fast_shutdown=0", " ".join(step.sql))

    def test_the_marker_holds_class_stamp_and_source_backup(self) -> None:
        step = next(s for s in self.plan("lean") if s.name == "marker")
        text = "\n".join(step.sql)
        self.assertIn("ephemeral_world", text)
        self.assertIn("'lean'", text)
        self.assertIn("20261114T051003Z", text)
        self.assertIn(NEW, text)

    def test_without_an_auth_dump_accounts_are_synthesised(self) -> None:
        step = next(s for s in self.plan("full") if s.name == "auth")
        self.assertEqual(
            list(step.sql[: len(scrub.auth_synthesis_statements("mysql"))]),
            scrub.auth_synthesis_statements("mysql"),
        )

    def test_the_auth_step_always_scrubs_last(self) -> None:
        step = next(s for s in self.plan("full") if s.name == "auth")
        self.assertEqual(
            list(step.sql[-len(scrub.auth_scrub_statements("mysql")) :]),
            scrub.auth_scrub_statements("mysql"),
        )

    def test_an_auth_dump_is_restored_then_scrubbed_not_synthesised(self) -> None:
        auth = self.dir / "auth.sql.gz"
        with gzip.open(auth, "wb") as handle:
            handle.write(b"-- Dump completed\n")
        step = next(s for s in self.plan("full", auth_dump=auth) if s.name == "auth")
        self.assertEqual(
            list(step.sql[: len(scrub.auth_scrub_statements("mysql"))]),
            scrub.auth_scrub_statements("mysql"),
        )
        self.assertNotIn(
            "ACCT", "\n".join(step.sql[: len(scrub.auth_scrub_statements("mysql"))])
        )
        self.assertTrue(
            any(
                "gunzip" in " ".join(s.argv)
                for s in self.plan("full", auth_dump=auth)
                if s.name == "auth-restore"
            )
        )

    def test_the_push_names_the_class_and_stamp_and_the_prune_keeps_three(self) -> None:
        plan = self.plan("lean")
        push = next(s for s in plan if s.name == "push")
        self.assertIn(
            "registry.example.invalid/eph/wow-eph-template:lean-20261114T051003Z",
            " ".join(push.argv),
        )
        self.assertEqual(next(s for s in plan if s.name == "prune").keep, 3)

    def test_no_step_mentions_a_realm_hostname_or_namespace(self) -> None:
        for step in self.plan("lean"):
            blob = " ".join([*step.argv, *step.sql])
            self.assertNotIn(
                "wow-dev", blob.replace(NEW, "").replace("wow-dev-characters", "")
            )

    def test_every_sql_step_runs_against_the_loopback_server_only(self) -> None:
        for step in self.plan("lean"):
            self.assertNotIn("--host=mysql", " ".join(step.argv))


class Prune(unittest.TestCase):
    def test_keeps_the_newest_three_per_class(self) -> None:
        tags = [
            "lean-20261110T051000Z",
            "lean-20261111T051000Z",
            "lean-20261112T051000Z",
            "lean-20261113T051000Z",
            "full-20261113T051000Z",
            "full-20261114T051000Z",
        ]
        self.assertEqual(build.tags_to_prune(tags, keep=3), ["lean-20261110T051000Z"])

    def test_foreign_tags_are_never_pruned(self) -> None:
        self.assertEqual(
            build.tags_to_prune(["latest", "lean-oops", "keepme"], keep=1), []
        )


class Execution(unittest.TestCase):
    class Recorder:
        def __init__(self, audit_counts: list[int] | None = None) -> None:
            self.calls: list[str] = []
            self.audit_counts = audit_counts if audit_counts is not None else [0]

        def argv(self, step: build.Step) -> int:
            self.calls.append(step.name)
            return 0

        def sql(self, step: build.Step) -> list[list[int]]:
            self.calls.append(step.name)
            if step.name == "credential-audit":
                return [[c] for c in self.audit_counts]
            if step.name == "lean-trim":
                return [[150]]
            return []

    def steps(self, template_class: str = "lean") -> list[build.Step]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        directory = pathlib.Path(tmp.name)
        write_dump(directory, NEW)
        cfg = build.Config(
            template_class=template_class,
            backup_dir=directory,
            workdir=directory / "w",
            registry="r.example.invalid/x",
        )
        return build.plan(cfg, classes.load_classes(classes.DEFAULT_PATH))

    def test_a_clean_run_executes_every_step(self) -> None:
        rec = self.Recorder()
        build.execute(self.steps(), rec)
        self.assertEqual(rec.calls[-1], "prune")
        self.assertIn("push", rec.calls)

    def test_a_credential_in_the_audit_stops_the_build_before_packaging(self) -> None:
        rec = self.Recorder(audit_counts=[0, 2])
        with self.assertRaises(build.CredentialLeft):
            build.execute(self.steps(), rec)
        self.assertNotIn("package", rec.calls)
        self.assertNotIn("push", rec.calls)

    def test_a_failing_command_stops_the_build(self) -> None:
        class Failing(self.Recorder):
            def argv(self, step: build.Step) -> int:
                super().argv(step)
                return 1 if step.name == "restore" else 0

        rec = Failing()
        with self.assertRaises(build.StepFailed):
            build.execute(self.steps(), rec)
        self.assertNotIn("push", rec.calls)

    def test_the_runner_is_closed_even_when_a_step_fails(self) -> None:
        class Closing(self.Recorder):
            closed = 0

            def argv(self, step: build.Step) -> int:
                super().argv(step)
                return 1 if step.name == "restore" else 0

            def close(self) -> None:
                self.closed += 1

        rec = Closing()
        with self.assertRaises(build.StepFailed):
            build.execute(self.steps(), rec)
        self.assertEqual(rec.closed, 1)

    def test_close_terminates_a_running_server(self) -> None:
        class Server:
            terminated = False

            def poll(self):
                return None

            def terminate(self) -> None:
                self.terminated = True

            def wait(self, timeout=None) -> int:
                return 0

        cfg = build.Config(
            template_class="full",
            backup_dir=pathlib.Path("/b"),
            workdir=pathlib.Path("/w"),
        )
        runner = build.SubprocessRunner(cfg)
        server = Server()
        runner._server = server
        runner.close()
        runner.close()
        self.assertTrue(server.terminated)

    def test_a_lean_trim_that_leaves_nothing_stops_the_build(self) -> None:
        class Empty(self.Recorder):
            def sql(self, step: build.Step) -> list[list[int]]:
                super().sql(step)
                if step.name == "lean-trim":
                    raise scrub.EmptyKeepSet("keep set is empty")
                return []

        with self.assertRaises(build.StepFailed):
            build.execute(self.steps(), Empty())


class Done:
    def __init__(self, code: int = 0, out: str = "", err: str = "") -> None:
        self.returncode, self.stdout, self.stderr = code, out, err


class RunnerCommands(unittest.TestCase):
    def runner(self, outputs: dict[str, Done] | None = None):
        calls: list[list[str]] = []
        outputs = outputs or {}

        def fake_run(argv, **kw):
            calls.append(list(argv))
            for needle, done in outputs.items():
                if needle in " ".join(argv):
                    return done
            return Done()

        cfg = build.Config(
            template_class="lean",
            backup_dir=pathlib.Path("/b"),
            workdir=pathlib.Path("/w"),
        )
        return build.SubprocessRunner(cfg, run=fake_run), calls

    def test_sql_goes_through_a_loopback_client_with_no_password_on_argv(self) -> None:
        runner, calls = self.runner({"SELECT COUNT": Done(out="3\n")})
        step = build.Step("credential-audit", sql=("SELECT COUNT(*) FROM t",))
        self.assertEqual(runner.sql(step), [[3]])
        argv = calls[0]
        self.assertIn("-h127.0.0.1", argv)
        self.assertFalse(
            [a for a in argv if a.startswith("-p") or "password" in a.lower()]
        )

    def test_a_failing_statement_raises(self) -> None:
        runner, _ = self.runner({"DELETE": Done(code=1, err="boom")})
        with self.assertRaises(build.StepFailed):
            runner.sql(build.Step("state-scrub", sql=("DELETE FROM t",)))

    def test_an_empty_keep_set_stops_before_any_delete(self) -> None:
        runner, calls = self.runner({"_forge_keep": Done(out="0\n")})
        step = build.Step(
            "lean-trim",
            sql=(scrub.KEEP_COUNT_SQL, "DELETE FROM acore_characters.characters"),
        )
        with self.assertRaises(scrub.EmptyKeepSet):
            runner.sql(step)
        self.assertFalse([c for c in calls if "DELETE" in " ".join(c)])

    def test_prune_deletes_only_the_old_template_tags(self) -> None:
        listing = (
            "\n".join(f"lean-2026111{d}T051000Z" for d in range(1, 6)) + "\nlatest\n"
        )
        runner, calls = self.runner({"crane ls": Done(out=listing)})
        step = build.Step(
            "prune",
            argv=("crane", "ls", "r.example.invalid/x/wow-eph-template"),
            keep=3,
        )
        self.assertEqual(runner.argv(step), 0)
        deleted = [c[-1] for c in calls if c[:2] == ["crane", "delete"]]
        self.assertEqual(
            deleted,
            [
                "r.example.invalid/x/wow-eph-template:lean-20261111T051000Z",
                "r.example.invalid/x/wow-eph-template:lean-20261112T051000Z",
            ],
        )


class Cli(unittest.TestCase):
    def test_check_classes_exits_nonzero_for_an_unclassified_table(self) -> None:
        from forge import __main__ as cli

        with tempfile.TemporaryDirectory() as tmp:
            tables = pathlib.Path(tmp) / "tables.txt"
            fixture = (
                pathlib.Path(__file__).parent
                / "fixtures"
                / "forge_acore_characters_tables.txt"
            )
            tables.write_text(
                fixture.read_text(encoding="utf-8") + "brand_new\n", encoding="utf-8"
            )
            self.assertEqual(cli.main(["check-classes", "--tables", str(tables)]), 1)
            tables.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
            self.assertEqual(cli.main(["check-classes", "--tables", str(tables)]), 0)

    def test_build_dry_run_lists_the_steps_and_rejects_a_bad_workdir(self) -> None:
        from forge import __main__ as cli

        with tempfile.TemporaryDirectory() as tmp:
            write_dump(pathlib.Path(tmp), NEW)
            base = ["build", "--class", "lean", "--backup-dir", tmp, "--dry-run"]
            with mock.patch.dict(
                "os.environ", {"FORGE_REGISTRY": "registry.example.invalid/eph"}
            ):
                self.assertEqual(
                    cli.main([*base, "--workdir", "/var/lib/forge/work"]), 0
                )
                with self.assertRaises(ValueError):
                    cli.main([*base, "--workdir", "/w; rm -rf /"])


class Documented(unittest.TestCase):
    """AGENTS.md: a file that reads real config ships an example for it."""

    root = pathlib.Path(__file__).resolve().parent.parent

    def test_every_environment_variable_the_forge_reads_is_in_the_example(self) -> None:
        import re

        names: set[str] = set()
        for path in (self.root / "forge").glob("*.py"):
            names |= set(
                re.findall(
                    r'environ(?:\.get)?\(\s*"([A-Z][A-Z0-9_]+)"',
                    path.read_text(encoding="utf-8"),
                )
            )
        self.assertIn("FORGE_REGISTRY", names)
        example = (self.root / "forge" / "config.example.env").read_text(
            encoding="utf-8"
        )
        for name in sorted(names):
            self.assertRegex(example, rf"(?m)^{name}=")

    def test_the_example_holds_only_placeholders(self) -> None:
        example = (self.root / "forge" / "config.example.env").read_text(
            encoding="utf-8"
        )
        self.assertIn("example.invalid", example)

    def test_the_readme_gives_the_build_command_and_prerequisites(self) -> None:
        readme = (self.root / "README.md").read_text(encoding="utf-8")
        for needle in (
            "python -m forge build",
            "FORGE_REGISTRY",
            "config.example.env",
            "crane",
            "mysqld",
        ):
            self.assertIn(needle, readme)


if __name__ == "__main__":
    unittest.main()
