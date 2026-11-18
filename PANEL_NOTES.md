# Panel notes

## Known bad pixels
| x  | y | Fault            | Symptom                                     | Found      |
|----|---|------------------|---------------------------------------------|------------|
| 32 | 5 | Green LED dead   | Dark when green; white shows purple (R+B)   | 2026-11-17 |

Coordinates are 0-indexed from the top-left corner.
Re-check with: `.venv/bin/python pixel_check.py circle --x 32 --y 5 --radius 5 --hold 2`
