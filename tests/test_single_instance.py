# test_single_instance.py - a later launch hands its files to the open window, and where they go

import json
import os
import subprocess
import sys
import uuid

import pytest
from PySide6.QtCore import QCoreApplication

from ccgen.utils import single_instance
from ccgen.utils.launch import LaunchPlan, LaunchRequest, parse_arguments, plan_launch
from ccgen.utils.single_instance import SingleInstance

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# What the tab controllers take (task_tabs.py, workflow_ctrl.py): Generate needs video or audio,
# the other tabs take subtitle files too.
_MEDIA = {".mp4", ".mkv", ".mp3", ".wav"}
_SUBTITLES = {".srt", ".vtt", ".ass"}
_ACCEPTED = {
    "generate": _MEDIA,
    "translate": _MEDIA | _SUBTITLES,
    "transliterate": _MEDIA | _SUBTITLES,
    "dub": _MEDIA | _SUBTITLES,
    "workflow": _MEDIA | _SUBTITLES,
}

# The open window and each later launch run in processes of their own, as they do in use: PySide6
# holds the GIL inside QLocalSocket's waitFor* calls, so a sender on a thread of the window's
# process would stall its event loop, and the test process never runs an event loop that would
# deliver what other tests' Qt objects left queued.

# The open window: it takes `count` later launches and prints what it delivered. With `late`, it
# holds them until all have arrived, then attaches, as while the window loads.
_WINDOW = r"""
import json, sys, time
from PySide6.QtCore import QCoreApplication
from ccgen.utils.launch import LaunchRequest
from ccgen.utils.single_instance import SingleInstance

prefix, count, late = sys.argv[1], int(sys.argv[2]), sys.argv[3] == "late"
app = QCoreApplication([])
window = SingleInstance(prefix)
if window.try_forward(LaunchRequest()):
    sys.exit("another window took the launch")
received = []
window.launchReceived.connect(lambda request: received.append([request.tab, list(request.paths)]))
if not late:
    window.attach()
print("listening", flush=True)
before_attach = None
deadline = time.monotonic() + 60
while time.monotonic() < deadline and len(received) < count:
    app.processEvents()
    if late and before_attach is None and len(window._pending) == count:
        before_attach = list(received)
        window.attach()
    time.sleep(0.005)
window.close()
print(json.dumps({"received": received, "before_attach": before_attach}), flush=True)
"""

# A later launch, as Explorer starts one; it prints whether the window took its request.
_SENDER = r"""
import json, sys
from PySide6.QtCore import QCoreApplication
from ccgen.utils.launch import LaunchRequest
from ccgen.utils.single_instance import SingleInstance

prefix, tab, path = sys.argv[1:4]
app = QCoreApplication([])
print(json.dumps({"forwarded": SingleInstance(prefix).try_forward(LaunchRequest(tab, (path,)))}), flush=True)
"""

# A pipe that accepts connections and never answers: a window whose event loop is stuck.
_SILENT_WINDOW = r"""
import sys, time
from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QLocalServer
app = QCoreApplication([])
server = QLocalServer()
server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
print("listening" if server.listen(sys.argv[1]) else "failed", flush=True)
time.sleep(60)
"""


class TestLaunchRequest:
    def test_round_trip(self):
        request = LaunchRequest("translate", ("C:\\a b\\movie_en.srt", "D:\\Teachers' talk.mp4"))
        assert LaunchRequest.decode(request.encode().rstrip(b"\n")) == request

    def test_encoding_is_one_line(self):
        encoded = LaunchRequest("", ("C:\\two\nlines.mp4",)).encode()
        assert encoded.endswith(b"\n") and encoded.count(b"\n") == 1

    @pytest.mark.parametrize("line", [b"not json", b"[1, 2]", b'{"tab": 1}', b'{"paths": "C:\\\\x"}',
                                      b'{"paths": [1]}', b"\xff\xfe"])
    def test_anything_else_is_refused(self, line):
        with pytest.raises(ValueError):
            LaunchRequest.decode(line)

    def test_a_tab_this_copy_does_not_know_still_delivers_the_files(self):
        request = LaunchRequest.decode(b'{"tab": "burn", "paths": ["C:\\\\a.mp4"]}')
        assert request == LaunchRequest("", ("C:\\a.mp4",))


class TestParseArguments:
    @pytest.fixture
    def files(self, tmp_path):
        names = ("movie.mp4", "movie_en.srt", "talk.mp3")
        for name in names:
            (tmp_path / name).write_bytes(b"x")
        return [str(tmp_path / name) for name in names]

    def test_the_menu_names_the_tab_before_the_paths(self, files):
        request = parse_arguments(["--tab", "translate", files[1]])
        assert request == LaunchRequest("translate", (files[1],))

    def test_the_tab_can_be_joined_with_an_equals_sign_in_any_case(self, files):
        assert parse_arguments(["--tab=Transliterate", files[1]]).tab == "transliterate"

    def test_without_a_tab_every_existing_path_is_kept_in_order(self, files):
        assert parse_arguments(files) == LaunchRequest("", tuple(files))

    def test_missing_paths_and_other_arguments_are_dropped(self, files, tmp_path):
        request = parse_arguments([str(tmp_path / "gone.mp4"), files[0], "--verbose"])
        assert request.paths == (files[0],)

    def test_an_unknown_tab_is_ignored(self, files):
        assert parse_arguments(["--tab", "burn", files[0]]) == LaunchRequest("", (files[0],))

    def test_a_tab_flag_without_a_value_is_ignored(self, files):
        assert parse_arguments([files[0], "--tab"]) == LaunchRequest("", (files[0],))

    def test_relative_paths_become_absolute_for_the_open_window(self, files, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert parse_arguments(["movie.mp4"]).paths == (str(tmp_path / "movie.mp4"),)

    def test_folders_are_kept(self, tmp_path):
        assert parse_arguments([str(tmp_path)]).paths == (str(tmp_path),)


class TestPlanLaunch:
    def test_media_goes_to_generate_and_subtitles_to_translate(self):
        plan = plan_launch(LaunchRequest("", ("a.mp4", "a_en.srt", "b.MP3", "b.vtt")), _ACCEPTED)
        assert plan == LaunchPlan("generate", {"generate": ("a.mp4", "b.MP3"), "translate": ("a_en.srt", "b.vtt")})

    def test_subtitle_files_alone_open_translate_not_generate(self):
        plan = plan_launch(LaunchRequest("", ("a_en.srt",)), _ACCEPTED)
        assert plan == LaunchPlan("translate", {"translate": ("a_en.srt",)})

    def test_the_first_file_decides_the_tab_shown(self):
        assert plan_launch(LaunchRequest("", ("a_en.srt", "a.mp4")), _ACCEPTED).tab == "translate"

    @pytest.mark.parametrize("tab", ["translate", "transliterate", "dub", "workflow"])
    def test_a_named_tab_takes_every_file_it_can(self, tab):
        plan = plan_launch(LaunchRequest(tab, ("a_en.srt", "a.mp4")), _ACCEPTED)
        assert plan == LaunchPlan(tab, {tab: ("a_en.srt", "a.mp4")})

    def test_files_a_named_tab_cannot_take_go_to_their_default_tab(self):
        plan = plan_launch(LaunchRequest("generate", ("a.mp4", "a_en.srt")), _ACCEPTED)
        assert plan == LaunchPlan("generate", {"generate": ("a.mp4",), "translate": ("a_en.srt",)})

    def test_a_named_tab_that_got_nothing_is_not_shown(self):
        plan = plan_launch(LaunchRequest("generate", ("a_en.srt",)), _ACCEPTED)
        assert plan == LaunchPlan("translate", {"translate": ("a_en.srt",)})

    def test_folders_and_unknown_types_go_to_the_named_tab_or_generate(self):
        assert plan_launch(LaunchRequest("", ("C:\\Season 1", "notes.txt")), _ACCEPTED).files == {
            "generate": ("C:\\Season 1", "notes.txt")}
        assert plan_launch(LaunchRequest("dub", ("C:\\Season 1",)), _ACCEPTED).files == {"dub": ("C:\\Season 1",)}

    def test_a_tab_without_files_is_still_shown(self):
        assert plan_launch(LaunchRequest("transliterate"), _ACCEPTED) == LaunchPlan("transliterate", {})

    def test_a_bare_launch_changes_nothing(self):
        assert plan_launch(LaunchRequest(), _ACCEPTED) == LaunchPlan("", {})


# ── The pipe between launches ────────────────────────────────────────────────


@pytest.fixture
def qapp():
    """The test session's Qt application (the other tests use a QCoreApplication too)."""
    return QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture
def prefix() -> str:
    """A name prefix of its own, so a test never reaches a CC-Gen-Ultimate window open on this PC."""
    return f"CCGenTest-{uuid.uuid4().hex[:12]}"


@pytest.fixture
def make_instance(qapp, prefix):
    """Factory for SingleInstance objects with the test's prefix, closed on teardown."""
    created: list[SingleInstance] = []

    def factory() -> SingleInstance:
        instance = SingleInstance(prefix)
        created.append(instance)
        return instance

    yield factory
    for instance in created:
        instance.close()


@pytest.fixture
def run_script():
    """Start a Python script in its own process from the repo root; all are stopped on teardown."""
    started: list[subprocess.Popen] = []
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}

    def start(script: str, *args: str) -> subprocess.Popen:
        proc = subprocess.Popen([sys.executable, "-c", script, *args], cwd=_REPO, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        started.append(proc)
        return proc

    yield start
    for proc in started:
        if proc.poll() is None:
            proc.kill()
        proc.communicate()


def _open_window(run_script, prefix: str, count: int, late: bool = False) -> subprocess.Popen:
    """Start the window process and wait until it listens."""
    window = run_script(_WINDOW, prefix, str(count), "late" if late else "now")
    assert window.stdout is not None and window.stdout.readline().strip() == "listening"
    return window


def _send(run_script, prefix: str, tab: str, path: str) -> bool:
    """Run a later launch to its end; whether the window took its request."""
    sender = run_script(_SENDER, prefix, tab, path)
    out, err = sender.communicate(timeout=60)
    assert sender.returncode == 0, err
    return json.loads(out.strip().splitlines()[-1])["forwarded"]


def _delivered(window: subprocess.Popen) -> dict:
    """What the window process delivered, once it has all its launches."""
    out, err = window.communicate(timeout=90)
    assert window.returncode == 0, err
    return json.loads(out.strip().splitlines()[-1])


class TestNames:
    def test_pipe_and_mutex_names_belong_to_this_user_and_session(self, qapp):
        sid = single_instance._own_sid()
        instance = SingleInstance()
        assert sid.startswith("S-1-")
        assert instance._pipe_name == f"CC-Gen-Ultimate-{sid}-{single_instance._session_id()}"
        assert instance._mutex_name == f"Local\\CC-Gen-Ultimate-instance-{sid}"


class TestDelivery:
    def test_a_later_launch_hands_its_files_to_the_window(self, run_script, prefix):
        window = _open_window(run_script, prefix, 1)
        assert _send(run_script, prefix, "translate", "C:\\movie_en.srt") is True
        assert _delivered(window)["received"] == [["translate", ["C:\\movie_en.srt"]]]

    def test_launches_while_the_window_loads_wait_for_attach_in_order(self, run_script, prefix):
        window = _open_window(run_script, prefix, 2, late=True)
        for path in ("C:\\first.mp4", "C:\\second.mp4"):
            assert _send(run_script, prefix, "", path) is True
        report = _delivered(window)
        assert report["before_attach"] == []
        assert report["received"] == [["", ["C:\\first.mp4"]], ["", ["C:\\second.mp4"]]]


class TestFallbacks:
    def test_without_a_window_this_launch_becomes_it(self, make_instance):
        instance = make_instance()
        assert instance.try_forward(LaunchRequest("", ("C:\\a.mp4",))) is False
        assert instance._server is not None and instance._server.isListening()

    def test_an_unanswered_launch_opens_its_own_window(self, make_instance, run_script, monkeypatch):
        sender = make_instance()
        silent = run_script(_SILENT_WINDOW, sender._pipe_name)
        assert silent.stdout is not None and silent.stdout.readline().strip() == "listening"
        monkeypatch.setattr(single_instance, "_ANSWER_MS", 300)
        assert sender.try_forward(LaunchRequest("", ("C:\\a.mp4",))) is False
        assert sender._server is None  # a window exists, so this one doesn't listen as well

    def test_close_frees_the_name_for_a_new_window(self, make_instance):
        first = make_instance()
        assert first.try_forward(LaunchRequest()) is False
        first.close()
        second = make_instance()
        assert second.try_forward(LaunchRequest()) is False
        assert second._server is not None and second._server.isListening()
