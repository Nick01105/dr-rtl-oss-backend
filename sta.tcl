# OSS timing/power (OpenSTA) — stand-in for Dr_RTL's DC timing/power reports.
# Clock-only constraint: OpenSTA 2.4.0's all_inputs takes no flags, and the
# clock alone constrains the register-to-register paths the flow cares about.
# report_checks output is emitted in the same textual format Dr_RTL's timing
# parser expects (Startpoint/Endpoint/slack), so the parser is reused directly.
read_liberty LIB
read_verilog NETLIST
link_design TOP
create_clock -name clk -period CLK_PERIOD [get_ports CLK_PORT]
set_output_delay 0.0 -clock clk [all_outputs]
report_checks -path_delay max -group_count 100000 > TIMING_RPT
catch { set_power_activity -global -activity 0.1 -duty 0.5 }
catch { report_power > POWER_RPT }
