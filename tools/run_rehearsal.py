"""Run the existing rehearsal with flushed progress; preserve its frozen code/cache."""

import sys
import threading
import time
from pathlib import Path

import rehearse


def progress(root, company, stopped, main_thread):
    started = time.monotonic()
    while not stopped.is_set():
        directory = root / company
        count = sum(1 for _ in (directory / "decisions").glob("*.json"))
        frame = sys._current_frames().get(main_thread)
        stage = "starting"
        while frame is not None:
            filename = Path(frame.f_code.co_filename)
            if filename.is_relative_to(rehearse.REPO):
                stage = f"{filename.name}:{frame.f_lineno} ({frame.f_code.co_name})"
                break
            frame = frame.f_back
        print(f"[progress] {company}: {count:,} saved decisions; "
              f"elapsed {time.monotonic() - started:.0f}s; stage {stage}",
              file=sys.stderr, flush=True)
        stopped.wait(15)


def main():
    # Read only observer options here; the existing CLI validates all arguments.
    arguments = sys.argv[1:]
    company = arguments[arguments.index("--company") + 1] if "--company" in arguments else "A"
    root = (Path(arguments[arguments.index("--rehearsal-root") + 1]) if "--rehearsal-root" in arguments
            else rehearse.REPO / "private/rehearsal/v2")
    stopped = threading.Event()
    observer = threading.Thread(target=progress, args=(root, company, stopped, threading.get_ident()), daemon=True)
    print("Starting rehearsal with visible progress. Existing successful decisions will be reused.",
          file=sys.stderr, flush=True)
    observer.start()
    try:
        return rehearse.main()
    finally:
        stopped.set()
        observer.join()


if __name__ == "__main__":
    raise SystemExit(main())
