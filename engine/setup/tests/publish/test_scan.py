import os, subprocess, sys, tempfile, unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
SCAN = os.path.join(REPO, "publish", "np-publish-scan.py")


def run_scan(root):
    return subprocess.run([sys.executable, SCAN, root], capture_output=True, text=True)


class TestScan(unittest.TestCase):
    def _tree(self, files):
        d = tempfile.mkdtemp()
        for rel, content in files.items():
            p = os.path.join(d, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as fh:
                fh.write(content)
        return d

    def test_clean_tree_passes(self):
        d = self._tree({"setup/foo.sh": "#!/usr/bin/env bash\necho hello\n"})
        r = run_scan(d)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_planted_aws_key_blocks(self):
        d = self._tree({"x.md": "key AKIAABCDEFGHIJKLMNOP here\n"})
        r = run_scan(d)
        self.assertEqual(r.returncode, 1)
        self.assertIn("aws-akia", r.stderr)

    def test_planted_email_blocks(self):
        d = self._tree({"x.md": "contact pmb21656@gmail.com\n"})
        r = run_scan(d)
        self.assertEqual(r.returncode, 1)
        self.assertIn("pii-email", r.stderr)

    def test_home_path_blocks(self):
        d = self._tree({"x.sh": 'cd /home/pbrowne/Code\n'})
        r = run_scan(d)
        self.assertEqual(r.returncode, 1)

    def test_allowlisted_placeholder_is_ignored(self):
        d = self._tree({"engine/setup/tests/episodic/test_scrub.sh": "tok ghp_ABCDEFGHIJKLMNOPQRSTU end\n"})
        r = run_scan(d)
        self.assertEqual(r.returncode, 0, f"expected allowlisted placeholder to pass:\n{r.stderr}")

    def test_project_owner_handle_is_allowed(self):
        # pat-browne is the public repo owner (project identity), not PII to scrub.
        d = self._tree({"README.md": "clone https://github.com/pat-browne/nervepack\n"})
        r = run_scan(d)
        self.assertEqual(r.returncode, 0, f"pat-browne URL must not block:\n{r.stderr}")

    def test_pbrowne_net_still_blocks(self):
        # the personal SITE must still be caught (it should never appear in the engine).
        d = self._tree({"x.md": "see https://pbrowne.net for more\n"})
        r = run_scan(d)
        self.assertEqual(r.returncode, 1)

    def test_scanner_machinery_files_are_skipped(self):
        # The scanner's own source + tests + allowlist hold detection patterns /
        # planted fixtures by design; they must be skipped, not flag the guard
        # against itself. A control file with the same pattern still blocks.
        d = self._tree({
            "publish/np-publish-scan.py": "pmb21656@gmail.com /home/pbrowne\n",
            "engine/setup/tests/publish/test_scan.py": "pmb21656@gmail.com\n",
            "engine/setup/tests/publish/test_no_engine_pii.py": "/home/pbrowne\n",
            "publish/scan-allowlist.txt": "x\tghp_ABCDEFGHIJKLMNOPQRSTU\n",
        })
        r = run_scan(d)
        self.assertEqual(r.returncode, 0, f"machinery files must be skipped:\n{r.stderr}")
        # but a non-machinery file with the same pattern still blocks
        d2 = self._tree({"engine/setup/some-real-hook.sh": "cd /home/pbrowne\n"})
        self.assertEqual(run_scan(d2).returncode, 1)

    def test_lan_ip_blocks(self):
        # RFC1918 private addresses are infra residue (a real home/office box) and
        # must not ship in the public engine. All three ranges.
        for ip in ("192.168.0.113", "10.1.2.3", "172.20.0.1", "172.16.255.254", "172.31.0.1"):
            d = self._tree({"x.md": f"the box lives at {ip} on the LAN\n"})
            r = run_scan(d)
            self.assertEqual(r.returncode, 1, f"{ip} should block:\n{r.stdout}")
            self.assertIn("lan-ip", r.stderr, f"{ip} should flag lan-ip rule")

    def test_loopback_and_nonprivate_ips_allowed(self):
        # Loopback (the dashboard server binds 127.0.0.1 deliberately), TEST-NET doc
        # ranges, the 172.16/12 boundary neighbors, and public IPs are NOT residue.
        for ip in ("127.0.0.1", "0.0.0.0", "8.8.8.8", "192.0.2.1", "203.0.113.5",
                   "172.15.0.1", "172.32.0.1"):
            d = self._tree({"x.py": f'HOST = "{ip}"\n'})
            r = run_scan(d)
            self.assertEqual(r.returncode, 0, f"{ip} must not block:\n{r.stderr}")

    def test_modern_secret_shapes_block(self):
        # #169: the guard now catches common vendor key formats it previously missed.
        # Each token is stored split (prefix, body) so the literal secret never
        # appears in this source file -- GitHub secret-scanning push protection would
        # otherwise block the commit. It is reassembled at runtime and written to the
        # scanned tree, so the scanner under test still sees the whole token.
        cases = {
            "stripe-key":   ("sk_", "live_0123456789ABCDEFabcdefKLM"),
            "stripe-whsec": ("whsec", "_0123456789ABCDEFabcdef"),
            "google-api":   ("AIza", "0123456789abcdefghijklmnopqABCDEFxyz"),
            "slack-token":  ("xoxb", "-123456789012-abcdEFGHijkl"),
            "gh-pat":       ("github_pat", "_11ABCDE0000abcdefghij1234567890"),
            "gh-refresh":   ("ghr", "_0123456789ABCDEFabcdefGHIJ"),
            "jwt":          ("eyJ", "hbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcDEF123456"),
            "aws-asia":     ("ASIA", "ABCDEFGHIJKLMNOP"),
        }
        for rule, (pre, rest) in cases.items():
            token = pre + rest
            d = self._tree({"x.md": "SECRET=" + token + "\n"})
            r = run_scan(d)
            self.assertEqual(r.returncode, 1, f"{rule} should block: {token}\n{r.stdout}")
            self.assertIn(rule, r.stderr, f"{token} should flag {rule}")

    def test_openai_project_key_blocks(self):
        # Regression: the interior '-' of sk-proj-... must not truncate the match
        # below the length floor (the old sk-[A-Za-z0-9]{20,} rule missed it). Split
        # in source (see note above) so push protection doesn't flag the fixture.
        token = "sk-" + "proj-abcdefghijklmnopqrstuvwxyz1234"
        d = self._tree({"x.py": 'KEY = "' + token + '"\n'})
        r = run_scan(d)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("openai-sk", r.stderr)

    def test_pii_is_case_insensitive_and_covers_macos_home(self):
        for content in ("cd /Users/pbrowne/Code", "author PATRICK.BROWNE", "path /HOME/PBROWNE/x"):
            d = self._tree({"x.sh": content + "\n"})
            self.assertEqual(run_scan(d).returncode, 1, f"{content!r} should block")

    def test_missing_target_is_setup_error_not_pass(self):
        # Fail CLOSED: a wrong/absent target must be an error (2), never a clean pass.
        r = run_scan(os.path.join(tempfile.gettempdir(), "np-scan-does-not-exist-zzz"))
        self.assertEqual(r.returncode, 2, r.stderr)

    def test_empty_target_is_setup_error_not_pass(self):
        d = tempfile.mkdtemp()  # empty
        r = run_scan(d)
        self.assertEqual(r.returncode, 2, r.stderr)

    def test_git_worktree_pointer_file_is_skipped(self):
        # In a git worktree the repo `.git` is a FILE (a `gitdir:` pointer) holding a
        # /home/... path that the home-path rule would otherwise flag. It is git
        # plumbing, never publishable, so the scanner skips a `.git` file like a `.git`
        # dir. Control: the same /home path in a real file still blocks.
        d = self._tree({".git": "gitdir: /home/pbrowne/Code/nervepack/.git/worktrees/x\n",
                        "engine/setup/foo.sh": "#!/usr/bin/env bash\necho ok\n"})
        self.assertEqual(run_scan(d).returncode, 0,
                         f"a .git pointer file must be skipped:\n{run_scan(d).stdout}")
        d2 = self._tree({"notes.txt": "gitdir: /home/pbrowne/Code/nervepack\n"})
        self.assertEqual(run_scan(d2).returncode, 1)


if __name__ == "__main__":
    unittest.main()
