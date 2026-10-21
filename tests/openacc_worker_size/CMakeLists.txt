# Opt-in compiled-size probe. It is never a worker dependency or a CTest test.
if(NOT TARGET nci_openacc_objects OR NOT TARGET nci_driver_openacc OR NOT TARGET nci_cube_input)
  message(FATAL_ERROR "The size fixture needs the optional worker, its exact backend objects and reader")
endif()
add_executable(nci_openacc_worker_size compiled_sizes.f90)
target_link_libraries(nci_openacc_worker_size PRIVATE nci_openacc_objects nci_cube_input)
set_target_properties(nci_openacc_worker_size PROPERTIES
  Fortran_MODULE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/modules")
# The same sanitized loader environment must resolve the exact SDK libraries.
get_target_property(_worker_rpath nci_driver_openacc BUILD_RPATH)
set_target_properties(nci_openacc_worker_size PROPERTIES BUILD_RPATH "${_worker_rpath}" BUILD_RPATH_USE_ORIGIN FALSE)
target_link_options(nci_openacc_worker_size PRIVATE "LINKER:--disable-new-dtags")
