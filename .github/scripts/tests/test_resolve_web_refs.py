import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "resolve-web-refs.py"
SPEC = importlib.util.spec_from_file_location("resolve_web_refs", SCRIPT)
resolver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(resolver)


class ResolveWebRefsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repositories = {}
        for component in ("lina", "luna", "web"):
            repository = Path(self.directory.name) / component
            subprocess.run(
                ["git", "init", "--quiet", "--initial-branch=dev", str(repository)],
                check=True,
                capture_output=True,
            )
            self.git(repository, "commit", "--quiet", "--allow-empty", "-m", "Initial commit")
            self.repositories[component] = str(repository)

    @staticmethod
    def git(repository, *args):
        return subprocess.run(
            [
                "git", "-C", str(repository),
                "-c", "user.name=Branch Resolver Test",
                "-c", "user.email=branch-resolver@example.com",
                *args,
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def test_same_name_has_priority_over_base_and_dev(self):
        repository = self.repositories["lina"]
        self.git(repository, "branch", "ferror@v4.10.19-lts")
        self.git(repository, "branch", "v4.10.19-lts")
        self.assertEqual(
            resolver.resolve_branch(repository, "ferror@v4.10.19-lts"),
            "ferror@v4.10.19-lts",
        )

    def test_base_branch_has_priority_over_dev(self):
        repository = self.repositories["lina"]
        self.git(repository, "branch", "v4.10.19-lts")
        self.assertEqual(
            resolver.resolve_branch(repository, "ferror@v4.10.19-lts"),
            "v4.10.19-lts",
        )

    def test_dev_is_the_last_fallback(self):
        for source in ("ferror@v4.10.19-lts", "ferror", "dev"):
            with self.subTest(source=source):
                self.assertEqual(resolver.resolve_branch(self.repositories["lina"], source), "dev")

    def test_same_name_without_at_and_full_ref_with_slashes(self):
        repository = self.repositories["lina"]
        for branch in ("ferror", "customer/ferror@release/v4"):
            self.git(repository, "branch", branch)
            with self.subTest(branch=branch):
                self.assertEqual(resolver.resolve_branch(repository, f"refs/heads/{branch}"), branch)

    def test_tags_are_not_selected_as_branches(self):
        repository = self.repositories["lina"]
        self.git(repository, "tag", "ferror@v4.10.19-lts")
        self.git(repository, "tag", "v4.10.19-lts")
        self.assertEqual(resolver.resolve_branch(repository, "ferror@v4.10.19-lts"), "dev")

    def test_no_available_candidate_fails(self):
        repository = self.repositories["lina"]
        self.git(repository, "branch", "-m", "main")
        with self.assertRaisesRegex(RuntimeError, "No matching branch"):
            resolver.resolve_branch(repository, "ferror@v4.10.19-lts")

    def test_remote_query_failure_does_not_fall_back_to_dev(self):
        with self.assertRaises(subprocess.CalledProcessError):
            resolver.resolve_branch(str(Path(self.directory.name) / "missing"), "ferror")

    def test_each_trigger_preserves_revision_and_resolves_peers_independently(self):
        source = "ferror@v4.10.19-lts"
        self.git(self.repositories["lina"], "branch", source)
        self.git(self.repositories["luna"], "branch", "v4.10.19-lts")
        expected = {"LINA_REF": source, "LUNA_REF": "v4.10.19-lts", "WEB_REF": "dev"}
        with patch.dict(resolver.REPOSITORIES, self.repositories, clear=True):
            for component in self.repositories:
                with self.subTest(component=component):
                    revision = self.git(self.repositories[component], "rev-parse", "HEAD")
                    refs = resolver.resolve_refs(component, source, revision)
                    self.assertEqual(refs, {**expected, f"{component.upper()}_REF": revision})

    def test_manual_build_matches_each_component_independently(self):
        branch = 'ferror@v4.10.19-lts'
        self.git(self.repositories['lina'], 'branch', branch)
        self.git(self.repositories['luna'], 'branch', 'v4.10.19-lts')
        with patch.dict(resolver.REPOSITORIES, self.repositories, clear=True):
            self.assertEqual(resolver.resolve_refs(None, branch, None), {
                'LINA_REF': branch, 'LUNA_REF': 'v4.10.19-lts', 'WEB_REF': 'dev',
            })

    def test_manual_explicit_sha_and_dev_override_automatic_matching(self):
        branch = 'ferror@v4.10.19-lts'
        for repository in self.repositories.values():
            self.git(repository, 'branch', branch)
        sha = self.git(self.repositories['luna'], 'rev-parse', 'HEAD')
        with patch.dict(resolver.REPOSITORIES, self.repositories, clear=True):
            self.assertEqual(resolver.resolve_refs(None, branch, None,
                                                  {'lina': 'dev', 'luna': sha}), {
                'LINA_REF': 'dev', 'LUNA_REF': sha, 'WEB_REF': branch,
            })

    def test_manual_cli_preserves_explicit_tag_overrides_without_remote_queries(self):
        args = ['resolve-web-refs.py', '--source-branch', 'ferror@v4.10.19-lts',
                '--lina-ref', 'refs/tags/v4.10.19-lts', '--luna-ref', 'dev',
                '--web-ref', 'a' * 40]
        output = io.StringIO()
        with patch('sys.argv', args), patch('sys.stdout', output), \
                patch.object(resolver, 'resolve_branch') as query:
            self.assertEqual(resolver.main(), 0)
        query.assert_not_called()
        self.assertIn('LINA_REF=refs/tags/v4.10.19-lts', output.getvalue())

    def test_cli_rejects_incomplete_trigger_and_multiline_refs(self):
        for extra in [['--component', 'web'], ['--source-ref', 'a' * 40],
                      ['--lina-ref', 'dev\nWEB_REF=other']]:
            with self.subTest(extra=extra), \
                    patch('sys.argv', ['resolve-web-refs.py', '--source-branch', 'dev', *extra]), \
                    patch('sys.stderr', io.StringIO()), self.assertRaises(SystemExit) as error:
                resolver.main()
            self.assertEqual(error.exception.code, 2)

    def test_workflow_shell_selects_manual_refs_and_preserves_automatic_sha(self):
        branch = 'ferror@v4.10.19-lts'
        self.git(self.repositories['lina'], 'branch', branch)
        self.git(self.repositories['luna'], 'branch', 'v4.10.19-lts')
        root = Path(self.directory.name) / 'workflow'
        scripts = root / '.github/scripts'
        scripts.mkdir(parents=True)
        # Use actual local repositories through the CLI invoked by the YAML shell.
        program = SCRIPT.read_text().replace(
            '    args = parser.parse_args()',
            f'    REPOSITORIES.update({self.repositories!r})\n    args = parser.parse_args()')
        (scripts / SCRIPT.name).write_text(program)
        workflow = SCRIPT.parents[1] / 'workflows/build-web-image.yml'
        step = workflow.read_text().split('      - name: Resolve matching component branches\n', 1)[1]
        shell = textwrap.dedent(step.split('        run: |\n', 1)[1].split('\n      - name:', 1)[0])
        output = root / 'github-env'
        for event in ('workflow_dispatch', 'push'):
            with self.subTest(event=event):
                output.write_text('')
                result = subprocess.run(['bash', '-c', shell], cwd=root, capture_output=True,
                                        text=True, check=True, timeout=15, env={
                    **os.environ, 'EVENT_NAME': event, 'WEB_BRANCH': branch,
                    'LINA_OVERRIDE': '', 'LUNA_OVERRIDE': '', 'WEB_OVERRIDE': '',
                    'TRIGGER_REF': 'a' * 40, 'GITHUB_ENV': str(output),
                })
                actual = dict(line.split('=', 1) for line in output.read_text().splitlines())
                self.assertEqual(actual, {
                    'LINA_REF': branch, 'LUNA_REF': 'v4.10.19-lts',
                    'WEB_REF': 'dev' if event == 'workflow_dispatch' else 'a' * 40,
                }, result.stderr)


if __name__ == "__main__":
    unittest.main()
