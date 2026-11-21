"""Start the Torti GUI:  .venv\\Scripts\\python -m torti [--mic "Wave:3"] [--image never] ...

Options given here override and are saved to %LOCALAPPDATA%\\Torti\\settings.json for next time.
"""

import sys

from .config import Settings, build_parser


def main() -> int:
    args = build_parser("Torti").parse_args()
    settings = Settings.load().apply_args(args)
    if args.project:
        settings.last_project = args.project
    settings.save()
    from .gui import run

    return run(settings)


if __name__ == "__main__":
    sys.exit(main())
