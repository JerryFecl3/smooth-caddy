import os
"""Bounded process observation without service changes or actual sleeps."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

@unittest.skipIf(os.name=='nt', 'Target service shell behavior is tested on Linux')
class ObservationTests(unittest.TestCase):
    def run_observation(self, pattern, exclude=False):
        template=Path('app/network/templates/manage.sh').read_text()
        function=template[template.index('observe() {'):template.index('\nlock() {')]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'pids'
            # The shell's parent is a live PID; $$ is the simulated old process.
            lines=['echo '+ ('$$' if value=='old' else '$PPID' if value=='new' else "''")+' >> "$pids"' for value in pattern]
            script='''set -eu
pids=$1
'''+ '\n'.join(lines)+'''
manager_pid() {
 head -n 1 "$pids"
 tail -n +2 "$pids" > "$pids.next"
 mv "$pids.next" "$pids"
}
sleep() { :; }
'''+function+('\nobserve "$$"\n' if exclude else '\nobserve\n')
            return subprocess.run(['sh','-c',script,'test',str(path)],capture_output=True,timeout=5).returncode

    def test_restart_waits_through_old_pid_gap_and_new_pid(self):
        self.assertEqual(self.run_observation(['old','old','','new','new','new','new'],True),0)

    def test_old_pid_alone_cannot_confirm_restart(self):
        self.assertEqual(self.run_observation(['old']*30,True),1)

    def test_flapping_process_does_not_pass(self):
        self.assertEqual(self.run_observation(['new','','new']*10,True),1)

    def test_status_can_accept_current_stable_process(self):
        self.assertEqual(self.run_observation(['new']*4),0)
