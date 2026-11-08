"""Run a script with os.linesep forced to CRLF, as on Windows. pandas.to_csv reads os.linesep
at call time when no lineterminator is given. (Path.write_text translation is compiled in on
Windows and cannot be simulated here.)"""
import os, runpy, sys
os.linesep = "\r\n"
script = sys.argv[1]; sys.argv = sys.argv[1:]
runpy.run_path(script, run_name="__main__")
