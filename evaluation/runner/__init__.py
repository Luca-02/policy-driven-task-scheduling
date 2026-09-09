"""
runner: components of the evaluation run harness.

Public entry point is Runner (core.py); run.py builds the CLI and calls it.
"""

from .core import Runner

__all__ = ["Runner"]
