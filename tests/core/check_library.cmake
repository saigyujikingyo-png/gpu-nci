# SPDX-License-Identifier: MIT
# Inspects the built libnci_cpu shared object:
#   * exactly the three ABI v1 functions are exported (no test hooks/tuning),
#   * no fused multiply-add instruction was generated,
#   * no Fortran STOP / external I/O entry point is referenced; release-type
#     builds additionally reference no runtime-error or allocation-abort path.
# Usage: cmake -DLIB=<so> -DNM=<nm> -DOBJDUMP=<objdump> -DCONFIG=<cfg> -P check_library.cmake
if(NOT EXISTS "${LIB}")
  message(FATAL_ERROR "library not found: ${LIB}")
endif()

execute_process(COMMAND "${NM}" -D --defined-only "${LIB}"
                OUTPUT_VARIABLE defined RESULT_VARIABLE rc)
if(NOT rc EQUAL 0)
  message(FATAL_ERROR "nm failed (${rc})")
endif()
string(REGEX MATCHALL "[^\n]+" lines "${defined}")
set(exported "")
foreach(line IN LISTS lines)
  if(line MATCHES "^[0-9a-fA-F]* *[A-Z] ([^ @]+)")
    list(APPEND exported "${CMAKE_MATCH_1}")
  endif()
endforeach()
list(SORT exported)
set(expected nci_context_create_v1 nci_context_destroy_v1 nci_eval_tile_f64_v1)
if(NOT exported STREQUAL expected)
  message(FATAL_ERROR "exported symbols '${exported}' differ from '${expected}'")
endif()

execute_process(COMMAND "${NM}" -D --undefined-only "${LIB}"
                OUTPUT_VARIABLE undefined RESULT_VARIABLE rc)
if(NOT rc EQUAL 0)
  message(FATAL_ERROR "nm --undefined-only failed (${rc})")
endif()
if(undefined MATCHES "(_gfortran_(error_)?stop[a-z_]*|_gfortran_st_(write|read|open)[a-z_]*|_gfortran_transfer_[a-z_]*)")
  message(FATAL_ERROR "library references Fortran STOP/I-O entry point ${CMAKE_MATCH_1}")
endif()
if(NOT CONFIG STREQUAL "Debug")
  if(undefined MATCHES "(_gfortran_(runtime_error|os_error|generate_error)[a-z_]*)")
    message(FATAL_ERROR "release-type library references abort path ${CMAKE_MATCH_1}")
  endif()
endif()

execute_process(COMMAND "${OBJDUMP}" -d --no-show-raw-insn "${LIB}"
                OUTPUT_VARIABLE disasm RESULT_VARIABLE rc)
if(NOT rc EQUAL 0)
  message(FATAL_ERROR "objdump failed (${rc})")
endif()
if(disasm MATCHES "(vfn?m(add|sub)[a-z0-9]*)")
  message(FATAL_ERROR "fused multiply-add instruction found: ${CMAKE_MATCH_1}")
endif()
message(STATUS "exports: ${exported}; no FMA; no STOP/I-O references (${CONFIG})")
