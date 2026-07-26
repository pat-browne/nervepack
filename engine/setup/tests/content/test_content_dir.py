import os, subprocess, sys, tempfile, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_lib"))
from nptest import u  # cross-platform Windows path form (no-op off Windows)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
NP_CONTENT = os.path.join(REPO, "engine", "nervepack_engine", "np_content.py")


def _setup_script(name):
    return os.path.join(REPO, "engine", "setup", name)


_CLI = os.path.join(REPO, "engine", "nervepack_engine", "cli.py")


def _doctor(env):
    """Run the Python doctor (phase 15; np-doctor.sh retired) with a custom env."""
    return subprocess.run([sys.executable, _CLI, "doctor"],
                          capture_output=True, text=True, env=env)


def _run(verb, env=None, home=None):
    """Run `np_content.py <verb>` as a native subprocess (np-content-lib.sh retired,
    phase 18 — np_content.py is the sole resolver). Native-form paths (no MSYS u()),
    since np_content.py runs on sys.executable, not through bash — host-agnostic."""
    e = dict(os.environ)
    e.pop("NP_CONTENT_DIR", None)
    if home is not None:
        e["HOME"] = home
    if env:
        e.update(env)
    return subprocess.run([sys.executable, NP_CONTENT, verb],
                          capture_output=True, text=True, env=e)


def resolve(env=None, home=None):
    """np_content.py content_dir: prints the overlay root (exit 1 if it doesn't exist)."""
    return _run("content_dir", env=env, home=home)


def origin(env=None, home=None):
    """np_content.py content_origin: prints env | config | default."""
    return _run("content_origin", env=env, home=home)


def is_explicit(env=None, home=None):
    """np_content.py is_explicit: exits 0 when explicit (env/config), 1 on fallback."""
    return _run("is_explicit", env=env, home=home)


class TestContentDir(unittest.TestCase):
    def test_default_is_repo_root(self):
        r = resolve(home=tempfile.gettempdir())  # no env, no config file
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), REPO)

    def test_env_overrides(self):
        with tempfile.TemporaryDirectory() as d:
            r = resolve(env={"NP_CONTENT_DIR": d})
            self.assertEqual(r.stdout.strip(), d)

    def test_config_file_used_when_env_unset(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as content:
            cfgdir = os.path.join(home, ".config", "nervepack")
            os.makedirs(cfgdir)
            with open(os.path.join(cfgdir, "content-dir"), "w") as fh:
                fh.write(content + "\n")
            r = resolve(home=home)
            self.assertEqual(r.stdout.strip(), content)

    def test_config_file_crlf_is_tolerated(self):
        # A CRLF-terminated content-dir config file (common on Windows) must still
        # resolve to the bare path — _first_line strips \r as well as \n, so the
        # path isn't "<dir>\r" (which would fail os.path.isdir and return "").
        # Regression for the Windows-lane content-resolution bug (phase 18).
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as content:
            cfgdir = os.path.join(home, ".config", "nervepack")
            os.makedirs(cfgdir)
            with open(os.path.join(cfgdir, "content-dir"), "w", newline="") as fh:
                fh.write(content + "\r\n")   # explicit CRLF, exercised on every OS
            r = resolve(home=home)
            self.assertEqual(r.returncode, 0)
            self.assertEqual(r.stdout.strip(), content)

    def test_env_beats_config(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as c1, tempfile.TemporaryDirectory() as c2:
            cfgdir = os.path.join(home, ".config", "nervepack")
            os.makedirs(cfgdir)
            with open(os.path.join(cfgdir, "content-dir"), "w") as fh:
                fh.write(c1 + "\n")
            r = resolve(env={"NP_CONTENT_DIR": c2}, home=home)
            self.assertEqual(r.stdout.strip(), c2)

    def test_bad_explicit_path_errors(self):
        # np_content.py content_dir exits non-zero with no stdout when an explicit
        # path doesn't exist (the bash lib's loud "not found" stderr is retired).
        r = resolve(env={"NP_CONTENT_DIR": "/no/such/dir/xyz"})
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "")

    # --- origin classification (issue #12): one source of truth for explicit-vs-implicit ---
    # np_content_dir's stdout (the resolved path) must stay byte-identical for every case;
    # np_content_dir_origin is a pure-additive sibling that classifies HOW it resolved, so
    # the writers + the doctor share one detector. np_content_is_explicit is the boolean
    # the writers gate on.

    def test_origin_env_is_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            r = origin(env={"NP_CONTENT_DIR": d})
            self.assertEqual(r.stdout.strip(), "env")
            self.assertEqual(is_explicit(env={"NP_CONTENT_DIR": d}).returncode, 0)

    def test_origin_config_is_explicit_even_at_engine_root(self):
        # A single-repo user opts in DELIBERATELY by writing the config file pointing at
        # the engine root. That is explicit, not the accidental fallback — writers commit.
        with tempfile.TemporaryDirectory() as home:
            cfgdir = os.path.join(home, ".config", "nervepack")
            os.makedirs(cfgdir)
            with open(os.path.join(cfgdir, "content-dir"), "w") as fh:
                fh.write(REPO + "\n")   # config == engine root, set on purpose
            r = origin(home=home)
            self.assertEqual(r.stdout.strip(), "config")
            self.assertEqual(is_explicit(home=home).returncode, 0)

    def test_origin_default_is_implicit(self):
        # NP_CONTENT_DIR unset AND no config file -> the silent engine-root fallback.
        # This is the accidental case; np_content_is_explicit must report NON-zero.
        r = origin(home=tempfile.gettempdir())
        self.assertEqual(r.stdout.strip(), "default")
        self.assertNotEqual(is_explicit(home=tempfile.gettempdir()).returncode, 0)

    def test_origin_does_not_change_resolved_path(self):
        # Backward-compat: adding origin detection must not move the resolved path.
        r = resolve(home=tempfile.gettempdir())
        self.assertEqual(r.stdout.strip(), REPO)

    @unittest.skipIf(os.name == "nt", "symlink creation privilege-gated on Windows")
    def test_link_skills_merges_engine_and_overlay(self):
        # A fake engine (np-eng-demo) + an overlay (np-kb-demo). np_link_skills.link
        # (phase 17: 30-link-skills.sh retired) must link BOTH into a temp DST, with
        # the overlay skill pointing into the overlay dir. NP_DIR is a temp fake engine
        # so INDEX.md and the engine-skill resolution stay hermetic (never the repo).
        with tempfile.TemporaryDirectory() as overlay, tempfile.TemporaryDirectory() as dst, \
             tempfile.TemporaryDirectory() as fake_np:
            for name, root in (("np-eng-demo", fake_np), ("np-kb-demo", overlay)):
                d = os.path.join(root, "skills", name)
                os.makedirs(d)
                with open(os.path.join(d, "SKILL.md"), "w") as fh:
                    fh.write("---\nname: %s\ndescription: d\n---\n# demo\n" % name)
            e = dict(os.environ); e.update({
                "NP_CONTENT_DIR": u(overlay),
                "NP_SKILLS_DST": u(dst),
                "NP_DIR": u(fake_np),      # hermetic engine root (INDEX + engine skills)
                "HOME": u(fake_np),
            })
            e.pop("NP_TEAM_DIR", None)
            subprocess.run([sys.executable, _setup_script("np_link_skills.py")],
                           capture_output=True, text=True, env=e)
            links = set(os.listdir(dst))
            self.assertIn("np-kb-demo", links)      # overlay skill linked
            self.assertIn("np-eng-demo", links)     # engine skill still linked
            self.assertTrue(os.path.realpath(os.path.join(dst, "np-kb-demo")).startswith(os.path.realpath(overlay)))

    @unittest.skipIf(os.name == "nt", "symlink creation privilege-gated on Windows")
    def test_link_skills_overlay_missing_skills_dir_still_links_engine(self):
        # np-test: link-skills | failure
        # Failure path: the content overlay exists but has NO skills/ subdir. The linker
        # guards each source base (skips a non-existent dir), so it must still link the
        # ENGINE's own skills (the overlay simply contributes nothing) — no crash, clean
        # exit, and no broken/extra links from the absent overlay dir.
        with tempfile.TemporaryDirectory() as overlay, tempfile.TemporaryDirectory() as dst, \
             tempfile.TemporaryDirectory() as fake_np:
            # overlay is a valid content dir (it exists) but has no skills/ child.
            self.assertFalse(os.path.exists(os.path.join(overlay, "skills")))
            esk = os.path.join(fake_np, "skills", "np-eng-demo")
            os.makedirs(esk)
            with open(os.path.join(esk, "SKILL.md"), "w") as fh:
                fh.write("---\nname: np-eng-demo\ndescription: d\n---\n# demo\n")
            e = dict(os.environ); e.update({
                "NP_CONTENT_DIR": u(overlay),
                "NP_SKILLS_DST": u(dst),
                "NP_DIR": u(fake_np),      # hermetic engine root (INDEX + engine skills)
                "HOME": u(fake_np),
            })
            e.pop("NP_TEAM_DIR", None)
            subprocess.run([sys.executable, _setup_script("np_link_skills.py")],
                           capture_output=True, text=True, env=e)
            # The link pass must not blow up on the absent overlay skills/ dir
            # (each source base is skipped when it doesn't exist). Its real side
            # effect: the ENGINE skills are still linked into dst. (The trailing
            # best-effort INDEX regen runs under the hermetic NP_DIR redirect, same
            # as the happy test; its exit isn't the linker's contract — the LINKS are.)
            links = set(os.listdir(dst))
            # Engine skills are still present...
            self.assertIn("np-eng-demo", links, f"engine skill missing; dst={links}")
            # ...and every link points back into the ENGINE skills tree (not the overlay).
            engine_skills = os.path.realpath(os.path.join(fake_np, "skills"))
            for name in links:
                tgt = os.path.realpath(os.path.join(dst, name))
                self.assertTrue(tgt.startswith(engine_skills),
                                f"{name} -> {tgt} not under engine skills")

    def test_episodic_recall_reads_from_content_dir(self):
        # Point NP_CONTENT_DIR at a temp overlay with one episodic topic; recall must find it.
        with tempfile.TemporaryDirectory() as content:
            ep = os.path.join(content, "memory", "episodic")
            os.makedirs(ep)
            with open(os.path.join(ep, "INDEX.md"), "w") as fh:
                fh.write("| topic | last_updated | keywords |\n|---|---|---|\n| widget | 2026-01-01 | frobnicate |\n")
            with open(os.path.join(ep, "widget.md"), "w") as fh:
                fh.write("# widget notes\n")
            # NOT u()-converted: cli.py is invoked as a native subprocess.executable
            # child (not through bash), so it needs a native-form path, unlike the
            # bash-invoked scripts elsewhere in this file.
            e = dict(os.environ); e.update({"NP_CONTENT_DIR": content,
                                            "EPISODIC_STATE_DIR": os.path.join(content, "_state")})
            payload = '{"session_id":"t","prompt":"please frobnicate the widget"}'
            cli_path = os.path.join(REPO, "engine", "nervepack_engine", "cli.py")
            r = subprocess.run([sys.executable, cli_path, "hook", "episodic-recall"],
                                input=payload, capture_output=True, text=True, env=e)
            self.assertIn("widget", r.stdout)


    def test_aggregate_writes_metrics_under_content_dir(self):
        with tempfile.TemporaryDirectory() as content, tempfile.TemporaryDirectory() as conf_dir:
            ddir = os.path.join(content, "dashboard", "data"); os.makedirs(ddir)
            inbox = os.path.join(content, "_inbox"); os.makedirs(inbox)
            # Use a recent timestamp so the retention pruner (retain_days=90 default)
            # never prunes this record — this test is about content-dir routing, not retention.
            import datetime
            ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            rec = f'{{"session_id":"s1","ts":"{ts}","project":"p","signals":{{}},"contribution_score":1}}'
            with open(os.path.join(inbox, "s1.jsonl"), "w") as fh:
                fh.write(rec + "\n")
            # Provide a toggles.conf that keeps retain_days=0 (unlimited) so an old
            # timestamp in the test record would still survive — belt-and-suspenders.
            conf = os.path.join(conf_dir, "toggles.conf")
            with open(conf, "w") as fh:
                fh.write("evaluator|shared|runtime|on|retain_days=0\n")
            # NOT u()-converted: np_aggregate.py is invoked as a native
            # subprocess.executable child (not through bash), and it reads
            # NP_TOGGLES_CONF/np_toggle.py directly in-process too -- both need
            # native-form paths, unlike the bash-invoked scripts elsewhere in
            # this file.
            e = dict(os.environ); e.update({"NP_CONTENT_DIR": content,
                                            "EVAL_INBOX": inbox,
                                            "NP_AGG_NO_COMMIT": "1",
                                            "NP_TOGGLES_CONF": conf,
                                            "NP_TOGGLES_LOCAL": "/dev/null"})
            subprocess.run([sys.executable, _setup_script("np_aggregate.py")],
                           capture_output=True, text=True, env=e)
            out = os.path.join(ddir, "metrics.jsonl")
            self.assertTrue(os.path.exists(out))
            with open(out) as fh:
                self.assertIn("s1", fh.read())


    def test_doctor_passes_content_capability_with_default(self):
        # With no overlay configured, the default (repo root) has the content dirs, so the
        # content capability must PASS. Run the doctor and assert the content line isn't FAIL.
        r = _doctor({**os.environ})
        line = [l for l in (r.stdout + r.stderr).splitlines() if "content" in l.lower()]
        self.assertTrue(line, "doctor produced no 'content' capability line")
        self.assertFalse(any("FAIL" in l for l in line), f"content check failed: {line}")

    def test_doctor_warns_on_implicit_fallback(self):
        # issue #12 (option 4): with NO overlay configured (env unset + no config file),
        # the content dir resolves via the IMPLICIT engine-root fallback. The dir exists
        # so the check still PASSes (fail-open), but the doctor must WARN so the user is
        # told to configure it. HOME is redirected to a dir with no content-dir config.
        with tempfile.TemporaryDirectory() as home:
            e = {k: v for k, v in os.environ.items() if k != "NP_CONTENT_DIR"}
            e["HOME"] = u(home)
            r = _doctor(e)
            cline = [l for l in (r.stdout + r.stderr).splitlines() if "content" in l.lower()]
            self.assertTrue(cline, "doctor produced no 'content' capability line")
            self.assertFalse(any("FAIL" in l for l in cline), f"content check failed: {cline}")
            joined = "\n".join(cline).lower()
            self.assertIn("implicit", joined,
                          f"doctor did not warn about the implicit fallback: {cline}")

    def test_doctor_no_implicit_warning_with_explicit_overlay(self):
        # The mirror: when an overlay is explicitly configured, the doctor must NOT emit
        # the implicit-fallback warning (only the accidental case warns).
        with tempfile.TemporaryDirectory() as content:
            e = dict(os.environ); e["NP_CONTENT_DIR"] = u(content)
            r = _doctor(e)
            cline = [l for l in (r.stdout + r.stderr).splitlines() if "content" in l.lower()]
            joined = "\n".join(cline).lower()
            self.assertNotIn("implicit", joined,
                             f"doctor wrongly warned with an explicit overlay: {cline}")

    # --- dashboard-data bridge checks (35-link-dashboard-data / doctor dashboard-data cap) ---

    def test_doctor_dashboard_data_pass_when_symlink_resolves(self):
        # In a split layout, when dashboard/data is a symlink pointing at an existing dir,
        # the doctor must report PASS (not WARN/FAIL) for the dashboard-data capability.
        # We use the live engine which already has the symlink in place.
        e = dict(os.environ)
        r = _doctor(e)
        ddlines = [l for l in (r.stdout + r.stderr).splitlines() if "dashboard-data" in l.lower()]
        self.assertTrue(ddlines, f"doctor produced no dashboard-data line; full output:\n{r.stdout}{r.stderr}")
        # Should be PASS when the symlink resolves correctly.
        # (If the live engine is in single-repo layout this also returns PASS — both are fine.)
        self.assertFalse(
            any("FAIL" in l for l in ddlines),
            f"dashboard-data check failed when it should PASS: {ddlines}"
        )

    def test_doctor_dashboard_data_warns_when_bridge_missing(self):
        # np-test: dashboard-data-bootstrap | failure
        # Simulate a fresh clone: NP_CONTENT_DIR points at a content overlay but the
        # engine's dashboard/data symlink does not exist (removed). The doctor must
        # report WARN (not FAIL / not PASS) for the dashboard-data capability.
        # We temporarily rename dashboard/data, run the doctor, then restore it.
        import shutil
        dash_data = os.path.join(REPO, "dashboard", "data")
        backup = dash_data + "._test_bak"
        was_link = os.path.islink(dash_data)
        was_dir = os.path.isdir(dash_data) and not was_link

        # Remove the live link/dir.
        if was_link:
            link_target = os.readlink(dash_data)
            os.unlink(dash_data)
        elif was_dir:
            shutil.move(dash_data, backup)

        try:
            with tempfile.TemporaryDirectory() as content:
                # content overlay exists but has no dashboard/data subdir yet (fresh clone).
                e = dict(os.environ); e["NP_CONTENT_DIR"] = u(content)
                r = _doctor(e)
            ddlines = [l for l in (r.stdout + r.stderr).splitlines() if "dashboard-data" in l.lower()]
            self.assertTrue(ddlines, f"doctor produced no dashboard-data line; output:\n{r.stdout}{r.stderr}")
            joined = "\n".join(ddlines).lower()
            self.assertIn("warn", joined,
                          f"doctor did not WARN about missing dashboard-data bridge: {ddlines}")
        finally:
            # Restore the original state.
            if was_link:
                os.symlink(link_target, dash_data)
            elif was_dir:
                shutil.move(backup, dash_data)


if __name__ == "__main__":
    unittest.main()
