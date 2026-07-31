"""Settings, the frame chain, sources and the worker threads.

Only `worker` imports Qt. `settings`, `pipeline` and `source` stay importable
without a QApplication, which is what makes every module's `_demo` runnable —
except `settings`, which needs Qt only to ask where the config directory is.
"""
