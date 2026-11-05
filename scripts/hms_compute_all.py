# Jython script for HEC-HMS 4.14:  hec-hms.sh -s scripts/hms_compute_all.py
# Computes every run of HMS/Raymore_Trib12, or of the project copy whose .hms
# path is written in scripts/HMS_PROJECT (git-ignored) if that file exists.
# Run from the repository root.
import os
from hms.model import Project
from hms import Hms

RUNS = ["FEMA_10yr", "FEMA_25yr", "FEMA_50yr", "FEMA_100yr", "FEMA_100yr_plus", "FEMA_500yr",
        "Point_10yr", "Point_25yr", "Point_50yr", "Point_100yr", "Point_100yr_plus", "Point_500yr"]
cands = []
try:
    cands.append(os.path.dirname(os.path.abspath(__file__)))     # scripts/
except NameError:                                                # Jython execfile: no __file__
    pass
cands += [os.path.join(os.getcwd(), "scripts"), os.getcwd()]
prj = None
for d in cands:
    if os.path.exists(os.path.join(d, "HMS_PROJECT")):
        prj = open(os.path.join(d, "HMS_PROJECT")).read().strip()
        break
if prj is None:
    for d in cands:
        for up in (os.path.dirname(d), d):
            f = os.path.join(up, "HMS", "Raymore_Trib12", "Raymore_Trib12.hms")
            if prj is None and os.path.exists(f):
                prj = f
print("PROJECT " + prj)
p = Project.open(prj)
for r in RUNS:
    p.computeRun(r)
    print("COMPUTED " + r)
p.close()
Hms.shutdownEngine()
