"""Pure metadata acceptance includes a literal legacy seven-field CPU fixture."""
import pytest

from checks import check_build_info


def legacy():
    return dict(protocol_version=1, source_revision="fixture", compiler_id="GNU",
                compiler_version="fixture", build_type="Debug", fp_policy="strict",
                backend_library="/fixture/libnci_cpu.so")


@pytest.mark.parametrize("capabilities", [None, ["cpu"], ["cpu", "openacc"]])
def test_legacy_and_new_capability_metadata(capabilities):
    build = legacy()
    if capabilities is not None:
        build["supported_backends"] = capabilities
    assert check_build_info(build) == (capabilities or ["cpu"])


@pytest.mark.parametrize("capabilities", [[], ["openacc"], ["openacc", "cpu"],
    ["cpu", "cpu"], ["cpu", "cuda"], ["cpu", 1], "cpu", None])
def test_malformed_capabilities_are_rejected(capabilities):
    build = legacy()
    build["supported_backends"] = capabilities
    with pytest.raises(AssertionError):
        check_build_info(build)


def test_legacy_cannot_satisfy_openacc_request():
    with pytest.raises(AssertionError):
        check_build_info(legacy(), ["cpu", "openacc"])
