"""The Qt layer. Everything with a widget in it lives here and nothing else does.

`core` and `features` never import from this package — which is what lets every
analysis module run under `python -m` without a QApplication.
"""
