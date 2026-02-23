"""
Allow running hook_manager as a module.

Usage:
    python -m hooks.hook_manager
    python -m hooks
"""

from hooks.hook_manager import main

if __name__ == "__main__":
    main()
