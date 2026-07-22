# Dr_RTL — Open-Source Evaluation Backend

An open-source reimplementation of the **evaluation backend** for [Dr_RTL],
the LLM-agent framework for RTL timing/PPA optimization. The original relies on
commercial EDA tools (Synopsys Design Compiler + Formality, Cadence JasperGold);
this replaces that layer with a fully open stack — **Yosys + OpenSTA +
Yosys `equiv`** — so the agent loop can run without commercial licenses, and so
every synthesis / timing / equivalence stage is scriptable and inspectable.

Built as part of ongoing work on **LLM-based RTL rewriting for PPA
optimization**. The motivation for going open isn't just cost: a black-box
commercial flow can't be instrumented, perturbed, or ablated, which is exactly
what studying *why* an LLM rewrite helps or fails requires.

[Dr_RTL]: (link to the Dr_RTL paper / repo)

---

## What this is

The Dr_RTL agents only ever consume three artifacts per design/version:

| Artifact | Contents |
|---|---|
| `PPA_report.json` | `{Area, WNS, TNS, Power}` |
| `timing_word.json` | `{ "startReg -> endReg": worst_slack, ... }` |
| `SEC_result.txt` | `PASSED` / `FAILED` |

So the entire port is a **tool layer** that emits those three files from open
tools instead of commercial ones. The agent definitions and orchestration are
otherwise untouched.

### Toolchain mapping

| Stage | Dr_RTL (original) | This repo (OSS) |
|---|---|---|
| Synthesis / area | Synopsys Design Compiler | Yosys (`synth`, `abc`, Nangate45) |
| Timing / power | Design Compiler reports | OpenSTA (`report_checks`, `report_power`) |
| Equivalence (SEC) | Cadence JasperGold | Yosys `equiv_make` / `equiv_induct` (+ `async2sync`) |
| Library | Nangate45 `.db` | Nangate45 `.lib` (`NangateOpenCellLibrary_typical`) |
| Clock target | 0.1 ns (100 ps) | 0.1 ns (100 ps) — unchanged |

All tools ship inside the [OpenLane] Docker image, so no separate installs are
needed.

[OpenLane]: https://github.com/The-OpenROAD-Project/OpenLane

---

## Files

```
tool_layer/
├── run_design_oss.py     # driver: synth -> STA -> parse -> SEC, emits the 3 artifacts
├── parse_timing_oss.py   # tolerant OpenSTA timing-report parser
└── scr/
    ├── syn.ys            # Yosys synthesis
    ├── sta.tcl           # OpenSTA timing + power
    └── sec.ys            # Yosys equivalence (SEC)
```

These drop into the Dr_RTL `syn_flow_eda/` directory alongside the original
`run_design.py` (which is reused for `get_design_config` and `bit_2_word`). You
also need the Nangate45 liberty at `syn_flow_eda/lib/nangate45.lib`.

---

## Setup / usage

The tools run inside the OpenLane container; the agent orchestrator runs on the
host and reaches the tools over `docker exec`.

```bash
# inside the OpenLane container, from syn_flow_eda/
python3 run_design_oss.py vending_machine v0

# or from the host, against a running container:
docker exec <container> bash -lc \
  'cd /path/to/DR_RTL/syn_flow_eda && python3 run_design_oss.py vending_machine v0'
```

Outputs land in `output/<design>.<version>/`.

---

## Changes vs. original Dr_RTL

High level (not exhaustive):

- **New tool layer** — `run_design_oss.py`, `parse_timing_oss.py`, and
  `scr/{syn.ys, sta.tcl, sec.ys}` replace the DC/Formality/JasperGold flow in
  `run_design.py`.
- **Synthesis hardening** — `syn.ys` adds `async2sync` + `dfflegalize` to
  normalize async-reset / async-load flops into Nangate-mappable types, and
  `write_verilog -noexpr` to emit a structural netlist OpenSTA can parse
  (its reader rejects `reg`-typed ports). Needed across several RTL construct
  classes (async reset, inferred memory, SystemVerilog, reg-typed ports,
  async set+reset).
- **Tolerant timing parser** — the original strict parser discards the whole
  report on any Startpoint/Endpoint/slack count mismatch; the OSS version skips
  malformed path blocks. Also flips the slack regex to OpenSTA's ordering
  (value **before** the `slack (...)` token, vs. after in DC).
- **SEC via Yosys `equiv`** — combinational + inductive equivalence with
  `memory` and `async2sync` lowering, in place of JasperGold SEC.
- **Agent / orchestration glue** — the synthesis-evaluator agent invokes the
  OSS driver via `docker exec` into the OpenLane container; internal paths
  repointed from the original remote-host layout to the local `syn_flow_eda/`
  tree.

---

## Coverage

**17 of 20 designs** run clean end-to-end (correct synthesis, complete
zero-black-box timing, passing SEC).

Excluded:
- **SPI, UART** — clockless transparent latches on datapath outputs; no faithful
  flop-only Nangate mapping (forcing it would misrepresent the circuit).
- **LSTM** — the original flow simulates rather than SEC-checks this design.

The full optimization loop (analyze → rewrite → synth → SEC → score) was
validated by hand: an equivalence-preserving rewrite that cut area ~32% passed
SEC and scored as an improvement, while a rewrite that regressed timing scored
as a loss (i.e. the loop correctly accepts good rewrites and rejects bad ones),
and SEC holds on genuinely-different RTL.

---

## Findings / open questions

Two shortcomings surfaced during the port that are relevant to LLM-rewriting
research:

1. **SEC admissibility is the binding constraint, and it's weakest where the PPA
   wins are largest.** The high-value rewrites (pipelining, retiming) are
   sequential, which combinational + inductive equivalence struggles to clear.
   Worth quantifying: what fraction of an LLM's *good* proposals die at the
   equivalence checker vs. are actually wrong.

2. **The critical path is opaque to the LLM.** `timing_word.json` currently
   carries synthesizer-mangled net names with no reliable mapping back to RTL
   identifiers (the `bit_2_word` helper does not recover names from Yosys-style
   netlists). The optimizer is effectively asked to fix a path it can only see
   as anonymous gates. A name-mapping fix + an ablation (RTL-mapped vs.
   anonymous path context) is a clean, testable improvement.

---

## Attribution

This is an independent open-source backend for the Dr_RTL method. Original
method, agent design, and RTL dataset belong to the Dr_RTL authors — see the
Dr_RTL paper/repo for the source framework. This repo redistributes only the
open-source tool-layer code written for the port; run it against your own
Dr_RTL checkout.
