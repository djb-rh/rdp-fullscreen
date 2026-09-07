#!/bin/sh
# Build the standalone 68010 / TMS34010 disassembler against MAME's own cores.
M=${MAME:-$HOME/Developer/mame}
clang++ -std=c++20 -O1 -o dasm dasm.cpp \
  -I "$M/src/lib/util" -I "$M/src/devices/cpu/m68000" -I "$M/src/devices/cpu/tms34010" \
  -I "$M/src/devices" -I "$M/src/osd" -I "$M/3rdparty" \
  "$M/build/osx_clang/obj/x64/Release/src/devices/cpu/m68000/m68kdasm.o" \
  "$M/build/osx_clang/obj/x64/Release/src/devices/cpu/tms34010/34010dsm.o" \
  "$M/build/osx_clang/bin/x64/Release/libutils.a"
