#!/usr/bin/env python3
"""OSS tool layer for Dr_RTL: Yosys + OpenSTA + Yosys-equiv.

Drop-in replacement for run_design.py's Synopsys/Cadence flow. Reuses the
original run_design.py for design config + register-name helpers, and emits
the same three artifacts the Dr_RTL agents consume:

    output/<d>.<v>/PPA_report.json   {Area, WNS, TNS, Power}
    output/<d>.<v>/timing_word.json  {startReg -> endReg: slack}
    output/<d>.<v>/SEC_result.txt    PASSED / FAILED

Place this in the Dr_RTL syn_flow_eda/ directory alongside run_design.py,
parse_timing_oss.py, and scr/{syn.ys,sta.tcl,sec.ys}. Requires yosys and sta
(OpenSTA) on PATH — both ship inside the OpenLane Docker image.

Usage:  python3 run_design_oss.py <design> <version>   e.g. vending_machine v0
"""
import os, re, sys, json, shutil, subprocess

from run_design import get_design_config, bit_2_word          # original Dr_RTL helpers
from parse_timing_oss import parse_timing_tolerant             # OSS tolerant parser

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "lib", "nangate45.lib")
YOSYS = shutil.which("yosys") or "yosys"
STA = shutil.which("sta") or "sta"
CLK_PERIOD = "0.1"   # ns == 100 ps, matches the paper's DC setup


def _sh(cmd, log):
    with open(log, "w") as f:
        return subprocess.call(cmd, shell=True, stdout=f, stderr=subprocess.STDOUT)


def _fill(t, repl):
    for k, v in repl.items():
        t = t.replace(k, v)
    return t


def stage_rtl(design, version, tpe):
    """Copy rtl_dataset/<d>.<v>.<tpe> into ./rtl/ where the scripts read it."""
    os.makedirs("./rtl", exist_ok=True)
    dst = "./rtl/{}.{}.{}".format(design, version, tpe)
    if not os.path.exists(dst):
        src = os.path.join(HERE, "..", "rtl_dataset", "{}.{}.{}".format(design, version, tpe))
        if os.path.exists(src):
            shutil.copy(src, dst)
        else:
            raise FileNotFoundError("RTL missing: {} (no dataset copy at {})".format(dst, src))
    return dst


def run_syn(design, version):
    cfg = get_design_config(design)
    top, tpe = cfg["top"], cfg["tpe"]
    rtl = stage_rtl(design, version, tpe)
    dv = "{}.{}".format(design, version)
    for d in ("./netlist", "./reports/" + dv, "./log", "./output/" + dv):
        os.makedirs(d, exist_ok=True)
    netlist = "./netlist/{}.syn.v".format(dv)
    area_rpt = "./reports/{}/area.rpt".format(dv)
    ys = _fill(open("./scr/syn.ys").read(), {
        "RTL_PATH": rtl, "TOP": top, "LIB": LIB,
        "NETLIST_OUT": netlist, "AREA_RPT": area_rpt})
    tf = "./syn_{}.ys".format(dv)
    open(tf, "w").write(ys)
    _sh("{} -q {}".format(YOSYS, tf), "./log/syn_{}.log".format(dv))
    os.remove(tf)
    return netlist, area_rpt


def run_sta(design, version, netlist):
    cfg = get_design_config(design)
    top, clk = cfg["top"], cfg["clk"]
    dv = "{}.{}".format(design, version)
    timing_rpt = "./reports/{}/timing.rpt".format(dv)
    power_rpt = "./reports/{}/power.rpt".format(dv)
    tcl = _fill(open("./scr/sta.tcl").read(), {
        "LIB": LIB, "NETLIST": netlist, "TOP": top, "CLK_PORT": clk,
        "CLK_PERIOD": CLK_PERIOD, "TIMING_RPT": timing_rpt, "POWER_RPT": power_rpt})
    tf = "./sta_{}.tcl".format(dv)
    open(tf, "w").write(tcl)
    _sh("{} -exit {}".format(STA, tf), "./log/sta_{}.log".format(dv))
    os.remove(tf)
    return timing_rpt, power_rpt


def _parse_area(p):
    try:
        for line in open(p):
            m = re.search(r"[Cc]hip area for.*:\s*([\d.]+)", line)
            if m:
                return float(m.group(1))
    except IOError:
        pass
    return None


def _parse_wns_tns(p):
    s = []
    try:
        for line in open(p):
            m = re.search(r"(-?[\d.]+)\s+slack \([A-Z]+\)", line)
            if m:
                s.append(float(m.group(1)))
    except IOError:
        pass
    if not s:
        return None, None
    return min(s), sum(x for x in s if x < 0)


def _parse_power(p):
    try:
        for line in open(p):
            if line.strip().startswith("Total"):
                n = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", line)
                if len(n) >= 4:
                    return float(n[3])
    except IOError:
        pass
    return None


def write_ppa(design, version, area_rpt, timing_rpt, power_rpt):
    dv = "{}.{}".format(design, version)
    outdir = "./output/" + dv
    os.makedirs(outdir, exist_ok=True)
    area = _parse_area(area_rpt)
    wns, tns = _parse_wns_tns(timing_rpt)
    pwr = _parse_power(power_rpt)
    ppa = {"Area": area, "WNS": wns, "TNS": tns, "Power": pwr}
    json.dump(ppa, open(os.path.join(outdir, "PPA_report.json"), "w"), indent=4)
    print("Design: {}, Area: {}, WNS: {}, TNS: {}, Power: {}".format(design, area, wns, tns, pwr))


def run_sec(design, version):
    cfg = get_design_config(design)
    top, tpe = cfg["top"], cfg["tpe"]
    dv = "{}.{}".format(design, version)
    gold = stage_rtl(design, "v0", tpe)      # golden is always v0
    rev = stage_rtl(design, version, tpe)
    outdir = "./output/" + dv
    os.makedirs(outdir, exist_ok=True)
    ys = _fill(open("./scr/sec.ys").read(), {"GOLD_RTL": gold, "REV_RTL": rev, "TOP": top})
    sf = "./sec_{}.ys".format(dv)
    open(sf, "w").write(ys)
    rc = _sh("{} -q {}".format(YOSYS, sf), "./log/sec_{}.log".format(dv))
    os.remove(sf)
    passed = (rc == 0)
    open(os.path.join(outdir, "SEC_result.txt"), "w").write("PASSED\n" if passed else "FAILED\n")
    print("SEC result: {}".format("PASSED" if passed else "FAILED"))
    return passed


def run_design_oss(design, version):
    netlist, area_rpt = run_syn(design, version)
    timing_rpt, power_rpt = run_sta(design, version, netlist)
    parse_timing_tolerant(design, version)          # -> timing_word.json
    write_ppa(design, version, area_rpt, timing_rpt, power_rpt)
    run_sec(design, version)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 run_design_oss.py <design> <version>   e.g. vending_machine v0")
        sys.exit(1)
    run_design_oss(sys.argv[1], sys.argv[2])
