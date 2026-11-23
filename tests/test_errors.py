# test_errors.py - raw exceptions become one plain sentence with a next step (ccgen/core/errors.py)

import errno

import pytest

from ccgen.core import errors
from ccgen.core.errors import describe


class OutOfMemoryError(RuntimeError):
    """Named like torch.cuda.OutOfMemoryError, which describe() knows by name."""


class LocalEntryNotFoundError(Exception):
    """Named like huggingface_hub's error for a model that isn't cached and can't be fetched."""


def _wrapped(outer: str, inner: BaseException) -> RuntimeError:
    try:
        raise inner
    except BaseException as cause:
        try:
            raise RuntimeError(outer) from cause
        except RuntimeError as error:
            return error


class TestKinds:
    @pytest.mark.parametrize("error, kind", [
        (OutOfMemoryError("CUDA out of memory. Tried to allocate 2.00 GiB"), errors.KIND_GPU_MEMORY),
        (RuntimeError("CUDA failed with error out of memory"), errors.KIND_GPU_MEMORY),
        (MemoryError(), errors.KIND_MEMORY),
        (RuntimeError("[enforce fail at alloc_cpu.cpp] DefaultCPUAllocator: can't allocate memory"), errors.KIND_MEMORY),
        (OSError(errno.ENOSPC, "No space left on device"), errors.KIND_DISK_FULL),
        (PermissionError(errno.EACCES, "Permission denied", "C:/Out/movie.srt"), errors.KIND_ACCESS_DENIED),
        (FileNotFoundError(errno.ENOENT, "No such file", "C:/In/movie.mp4"), errors.KIND_FILE_MISSING),
        (LocalEntryNotFoundError("Cannot find the requested files in the disk cache"), errors.KIND_NETWORK),
        (ConnectionError("Max retries exceeded with url"), errors.KIND_NETWORK),
        (RuntimeError("Invalid data found when processing input"), errors.KIND_UNREADABLE_MEDIA),
    ])
    def test_kind(self, error, kind):
        problem = describe(error, "C:/In/movie.mp4")
        assert problem.kind == kind
        assert problem.message.endswith(".")
        assert problem.detail  # the original text is kept for the log and "Copy details"

    def test_a_windows_sharing_violation_names_the_file(self):
        error = OSError(errno.EACCES, "The process cannot access the file", "C:/Out/movie.srt")
        error.winerror = 32  # type: ignore[attr-defined]
        problem = describe(error)
        assert problem.kind == errors.KIND_IN_USE and problem.message.startswith("movie.srt is open in another app")

    def test_the_cause_of_a_wrapped_error_decides(self):
        problem = describe(_wrapped("Model load failed (small): boom", OutOfMemoryError("CUDA out of memory")))
        assert problem.kind == errors.KIND_GPU_MEMORY
        assert "Model load failed" in problem.detail and "CUDA out of memory" in problem.detail


class TestPlainMessages:
    def test_the_app_s_own_sentences_pass_through(self):
        problem = describe(ValueError("Choose a target language different from the source language."))
        assert problem.kind == errors.KIND_INVALID
        assert problem.message == "Choose a target language different from the source language."

    def test_a_translation_pair_problem_is_a_language_pair(self):
        problem = describe(ValueError("OPUS-MT has no model from English to Japanese. Choose another translation model."))
        assert problem.kind == errors.KIND_LANGUAGE_PAIR

    def test_unexplained_library_text_becomes_a_next_step(self):
        problem = describe(KeyError("decoder.layers.3"))
        assert problem.kind == errors.KIND_UNKNOWN
        assert problem.message == errors.unknown_message()
        assert "decoder.layers.3" in problem.detail

    def test_text_from_the_api_is_classified_too(self):
        assert describe("[WinError 112] There is not enough space on the disk").kind == errors.KIND_DISK_FULL
        assert describe("Choose the subtitle file to speak.").message == "Choose the subtitle file to speak."


class TestSizes:
    @pytest.mark.parametrize("size, text", [
        (466_000_000, "466 MB"), (3_267_458_000, "3.3 GB"), (120, "1 MB"), (0, "0 MB"), (None, "0 MB"),
    ])
    def test_format_size(self, size, text):
        assert errors.format_size(size) == text

    def test_disk_full_says_how_much_is_needed(self):
        assert "about 3.7 GB free" in errors.disk_full_message(3_700_000_000, "D:\\Models")
