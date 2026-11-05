import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
import unittest


WORKFLOW = Path(__file__).resolve().parents[1] / 'workflows' / 'docker-image.yml'


class ImageTagWorkflowTest(unittest.TestCase):
    def run_tags(self, tag, latest='false'):
        workflow = WORKFLOW.read_text()
        step = workflow.split('      - name: Determine tags\n', 1)[1].split('\n      - name:', 1)[0]
        script = textwrap.dedent(step.split('        run: |\n', 1)[1])
        context = {'${{ inputs.tag }}': tag, '${{ inputs.push_latest }}': latest}
        step_env = {key: context.get(value, value) for key, value in
                    re.findall(r'^          ([A-Z_]+): (.+)$', step, re.MULTILINE)}
        for expr, value in context.items():
            script = script.replace(expr, value)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'output'
            env = {key: value for key, value in os.environ.items()
                   if key not in ('IMAGE_TAG', 'PUSH_LATEST')}
            env.update({**step_env, 'GITHUB_OUTPUT': str(output)})
            result = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', script],
                                    env=env, capture_output=True, text=True)
            return result, output.read_text() if output.exists() else ''

    def test_valid_tag_and_latest_behavior(self):
        result, output = self.run_tags('1.2.3', 'true')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('tags=quay.io/krkn-chaos/krkn-ai:1.2.3,quay.io/krkn-chaos/krkn-ai:latest', output)
        result, output = self.run_tags('0.0.x')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(':latest', output)

    def test_invalid_tag_is_rejected_without_executing_shell(self):
        for tag in ['$(printf TAG_EXECUTED >&2)', 'bad tag', 'bad\ntag', '.bad', 'x' * 129]:
            with self.subTest(tag=tag):
                result, output = self.run_tags(tag)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('TAG_EXECUTED', result.stderr)
                self.assertEqual(output, '')


if __name__ == '__main__':
    unittest.main()
