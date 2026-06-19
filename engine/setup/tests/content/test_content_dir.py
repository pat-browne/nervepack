import os, subprocess, tempfile, unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
LIB = os.path.join(REPO, "engine", "setup", "np-content-lib.sh")


def resolve(env=None, home=None):
    """Run `source np-content-lib.sh; np_content_dir` with a custom env/HOME."""
    e = dict(os.environ)
    e.pop("NP_CONTENT_DIR", None)
    if home is not None:
        e["HOME"] = home
    if env:
        e.update(env)
    return subprocess.run(["bash", "-c", f'source "{LIB}"; np_content_dir'],
                          capture_output=True, text=True, env=e)


def origin(env=None, home=None):
    """Run `source np-content-lib.sh; np_content_dir_origin` with a custom env/HOME."""
    e = dict(os.environ)
    e.pop("NP_CONTENT_DIR", None)
    if home is not None:
        e["HOME"] = home
    if env:
        e.update(env)
    return subprocess.run(["bash", "-c", f'source "{LIB}"; np_content_dir_origin'],
                          capture_output=True, text=True, env=e)


def is_explicit(env=None, home=None):
    """Run `source np-content-lib.sh; np_content_is_explicit; echo $?`."""
    e = dict(os.environ)
    e.pop("NP_CONTENT_DIR", None)
    if home is not None:
        e["HOME"] = home
    if env:
        e.update(env)
    return subprocess.run(["bash", "-c", f'source "{LIB}"; np_content_is_explicit; echo "rc=$?"'],
                          capture_output=True, text=True, env=e)


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

    def test_env_beats_config(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as c1, tempfile.TemporaryDirectory() as c2:
            cfgdir = os.path.join(home, ".config", "nervepack")
            os.makedirs(cfgdir)
            with open(os.path.join(cfgdir, "content-dir"), "w") as fh:
                fh.write(c1 + "\n")
            r = resolve(env={"NP_CONTENT_DIR": c2}, home=home)
            self.assertEqual(r.stdout.strip(), c2)

    def test_bad_explicit_path_errors(self):
        r = resolve(env={"NP_CONTENT_DIR": "/no/such/dir/xyz"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not found", (r.stdout + r.stderr).lower())

    # --- origin classification (issue #12): one source of truth for explicit-vs-implicit ---
    # np_content_dir's stdout (the resolved path) must stay byte-identical for every case;
    # np_content_dir_origin is a pure-additive sibling that classifies HOW it resolved, so
    # the writers + the doctor share one detector. np_content_is_explicit is the boolean
    # the writers gate on.

    def test_origin_env_is_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            r = origin(env={"NP_CONTENT_DIR": d})
            self.assertEqual(r.stdout.strip(), "env")
            self.assertEqual(is_explicit(env={"NP_CONTENT_DIR": d}).stdout.strip(), "rc=0")

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
            self.assertEqual(is_explicit(home=home).stdout.strip(), "rc=0")

    def test_origin_default_is_implicit(self):
        # NP_CONTENT_DIR unset AND no config file -> the silent engine-root fallback.
        # This is the accidental case; np_content_is_explicit must report NON-zero.
        r = origin(home=tempfile.gettempdir())
        self.assertEqual(r.stdout.strip(), "default")
        self.assertNotEqual(is_explicit(home=tempfile.gettempdir()).stdout.strip(), "rc=0")

    def test_origin_does_not_change_resolved_path(self):
        # Backward-compat: adding origin detection must not move the resolved path.
        r = resolve(home=tempfile.gettempdir())
        self.assertEqual(r.stdout.strip(), REPO)

    def test_link_skills_merges_engine_and_overlay(self):
        # engine has its real skills; overlay adds np-kb-demo. Linker must link the overlay
        # skill AND the engine's own skills into a temp DST, with the overlay skill pointing
        # into the overlay dir.
        # NERVEPACK is redirected to a tmp dir so that 60-generate-index.sh writes
        # INDEX.md there instead of into the repo (test isolation).
        with tempfile.TemporaryDirectory() as overlay, tempfile.TemporaryDirectory() as dst, \
             tempfile.TemporaryDirectory() as fake_np:
            osk = os.path.join(overlay, "skills", "np-kb-demo")
            os.makedirs(osk)
            with open(os.path.join(osk, "SKILL.md"), "w") as fh:
                fh.write("---\nname: np-kb-demo\ndescription: d\n---\n# demo\n")
            e = dict(os.environ); e.update({
                "NP_CONTENT_DIR": overlay,
                "NP_SKILLS_DST": dst,
                "NERVEPACK": fake_np,   # redirect INDEX.md write away from the repo
            })
            subprocess.run([os.path.join(REPO, "engine", "setup", "30-link-skills.sh")],
                           capture_output=True, text=True, env=e)
            links = set(os.listdir(dst))
            self.assertIn("np-kb-demo", links)      # overlay skill linked
            self.assertIn("np-core-sync", links)     # engine skill still linked
            self.assertTrue(os.path.realpath(os.path.join(dst, "np-kb-demo")).startswith(os.path.realpath(overlay)))

    def test_link_skills_overlay_missing_skills_dir_still_links_engine(self):
        # np-test: link-skills | failure
        # Failure path for 30-link-skills.sh: the content overlay exists but has NO
        # skills/ subdir. The linker guards each source base with `[[ -d "$base" ]] ||
        # continue`, so it must still link the ENGINE's own skills (the overlay simply
        # contributes nothing) — no crash, clean exit, and no broken/extra links from
        # the absent overlay dir. Guards a regression where a missing overlay skills/
        # aborts the whole link pass (and thus a session loses ALL skills).
        with tempfile.TemporaryDirectory() as overlay, tempfile.TemporaryDirectory() as dst, \
             tempfile.TemporaryDirectory() as fake_np:
            # overlay is a valid content dir (it exists) but has no skills/ child.
            self.assertFalse(os.path.exists(os.path.join(overlay, "skills")))
            e = dict(os.environ); e.update({
                "NP_CONTENT_DIR": overlay,
                "NP_SKILLS_DST": dst,
                "NERVEPACK": fake_np,   # redirect INDEX.md write away from the repo
            })
            subprocess.run([os.path.join(REPO, "engine", "setup", "30-link-skills.sh")],
                           capture_output=True, text=True, env=e)
            # The link pass must not blow up on the absent overlay skills/ dir
            # (`[[ -d "$base" ]] || continue` guards each source base). Its real
            # side effect: the ENGINE skills are still linked into dst. (The
            # trailing best-effort INDEX regen runs under the fake NERVEPACK
            # redirect, same as the happy test; its exit isn't the linker's
            # contract — the LINKS are.)
            links = set(os.listdir(dst))
            # Engine skills are still present...
            self.assertIn("np-core-sync", links, f"engine skill missing; dst={links}")
            # ...and every link points back into the ENGINE skills tree (not the overlay).
            engine_skills = os.path.realpath(os.path.join(REPO, "skills"))
            for name in links:
                tgt = os.path.realpath(os.path.join(dst, name))
                self.assertTrue(tgt.startswith(engine_skills),
                                f"{name} -> {tgt} not under engine skills")

    def test_episodic_recall_reads_from_content_dir(self):
        # Point NP_CONTENT_DIR at a temp overlay with one episodic topic; recall must find it.
        with tempfile.TemporaryDirectory() as content:
            ep = os.path.join(content, "episodic")
            os.makedirs(ep)
            with open(os.path.join(ep, "INDEX.md"), "w") as fh:
                fh.write("| topic | last_updated | keywords |\n|---|---|---|\n| widget | 2026-01-01 | frobnicate |\n")
            with open(os.path.join(ep, "widget.md"), "w") as fh:
                fh.write("# widget notes\n")
            e = dict(os.environ); e.update({"NP_CONTENT_DIR": content,
                                            "EPISODIC_STATE_DIR": os.path.join(content, "_state")})
            payload = '{"session_id":"t","prompt":"please frobnicate the widget"}'
            r = subprocess.run([os.path.join(REPO, "engine", "setup", "episodic-recall.sh")],
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
            e = dict(os.environ); e.update({"NP_CONTENT_DIR": content,
                                            "EVAL_INBOX": inbox,
                                            "NP_AGG_NO_COMMIT": "1",
                                            "NP_TOGGLES_CONF": conf,
                                            "NP_TOGGLES_LOCAL": "/dev/null"})
            subprocess.run([os.path.join(REPO, "engine", "setup", "73-aggregate-metrics.sh")],
                           capture_output=True, text=True, env=e)
            out = os.path.join(ddir, "metrics.jsonl")
            self.assertTrue(os.path.exists(out))
            with open(out) as fh:
                self.assertIn("s1", fh.read())


    def test_doctor_passes_content_capability_with_default(self):
        # With no overlay configured, the default (repo root) has the content dirs, so the
        # content capability must PASS. Run the doctor and assert the content line isn't FAIL.
        r = subprocess.run([os.path.join(REPO, "engine", "setup", "np-doctor.sh")],
                           capture_output=True, text=True, env={**os.environ})
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
            e["HOME"] = home
            r = subprocess.run([os.path.join(REPO, "engine", "setup", "np-doctor.sh")],
                               capture_output=True, text=True, env=e)
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
            e = dict(os.environ); e["NP_CONTENT_DIR"] = content
            r = subprocess.run([os.path.join(REPO, "engine", "setup", "np-doctor.sh")],
                               capture_output=True, text=True, env=e)
            cline = [l for l in (r.stdout + r.stderr).splitlines() if "content" in l.lower()]
            joined = "\n".join(cline).lower()
            self.assertNotIn("implicit", joined,
                             f"doctor wrongly warned with an explicit overlay: {cline}")


if __name__ == "__main__":
    unittest.main()
