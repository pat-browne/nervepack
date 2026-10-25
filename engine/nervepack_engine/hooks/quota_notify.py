"""Not a lifecycle hook -- the target of the one-shot `at` job np_quota_watch
schedules for resume_epoch. Dispatched the same way (`cli.py hook
quota-notify`) so it reuses the hook table's stdin/argv plumbing, but no
Claude Code event ever fires it directly.
"""
import np_quota_watch


def run(_payload_text, *_args):
    try:
        np_quota_watch.notify_now()
    except Exception:
        pass
    return ""
