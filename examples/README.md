# Reviewed packaging examples

These small fixtures intentionally avoid networking, subprocesses, arbitrary project imports and dependencies beyond the standard library (CLI) or PyQt5 (GUI). Review their source before any real build. Packaging and launching remain code-executing actions.

```bash
pyforge build examples/hello_cli.py --name ReviewedCLI --output-dir dist --mode onedir --trust-code
pyforge build examples/hello_gui.py --name ReviewedGUI --output-dir dist --mode onedir --no-console --trust-code
```

Run the resulting CLI with `--name Example` to obtain a JSON greeting and `PYFORGE_SMOKE_OK`. The GUI runs normally until closed; `--smoke-test` exits automatically. `--marker-file PATH` is an explicit opt-in file write during smoke mode, used by native CI when no console output is available. The GUI fixture does not grant PyQt/Qt redistribution rights; review the project's licensing guide before distributing it.
