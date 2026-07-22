"""Tolerant timing-report parser for the OSS (OpenSTA) flow.

Replaces the strict parse_timing_report() from Dr_RTL's run_design.py, which
asserts that the counts of Startpoint / Endpoint / slack lines match exactly
and discards the whole report on any mismatch. This version walks the report
path-block by path-block and skips malformed blocks, so one stray path can
never zero out timing_word.json.

Key difference from the original regex: OpenSTA prints the slack value BEFORE
the "slack (MET|VIOLATED)" token, whereas Synopsys DC printed it after. The
regex here matches the OpenSTA ordering.

Emits output/<design>.<version>/timing_word.json with the same schema the
Dr_RTL agents consume: { "startReg -> endReg": worst_slack, ... }.
"""
import os, re, json
from run_design import bit_2_word  # reused from the original Dr_RTL run_design.py


def parse_timing_tolerant(design, version):
    dv = "{}.{}".format(design, version)
    rpt = "./reports/{}/timing.rpt".format(dv)
    outdir = "./output/{}".format(dv)
    os.makedirs(outdir, exist_ok=True)

    start = end = None
    word = {}
    n = 0
    with open(rpt) as f:
        for line in f:
            if "Startpoint:" in line:
                start = line.split("Startpoint:")[1].split()[0]
            elif "Endpoint:" in line:
                end = line.split("Endpoint:")[1].split()[0]
            else:
                # OpenSTA: "<num>   slack (MET|VIOLATED)"  (number BEFORE 'slack')
                m = re.search(r"(-?\d+\.?\d*)\s+slack \([A-Z]+\)", line)
                if m and start is not None and end is not None:
                    slack = float(m.group(1))
                    key = "{} -> {}".format(bit_2_word(start), bit_2_word(end))
                    if key not in word or slack < word[key]:
                        word[key] = slack
                    n += 1
                    start = end = None  # reset for the next path block

    with open(os.path.join(outdir, "timing_word.json"), "w") as f:
        json.dump(word, f, indent=4)
    print("Timing parsed (tolerant): {} paths, {} word-keys".format(n, len(word)))
    return word


if __name__ == "__main__":
    import sys
    parse_timing_tolerant(sys.argv[1], sys.argv[2])
