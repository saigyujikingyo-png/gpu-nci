"""Verifier rejection checks on invented protocol data, no native/GPU execution."""
import copy
import json

import pytest

from oracle import INF, QNAN, SIGN, bits, value
from selftest_support import corpus, encode, save_evidence, synthetic_evidence, synthetic_result
from verify import (Rejected, compare, main, parse_output, receipt, verify_files)


def pair():
    manifest=corpus();host=synthetic_result(manifest)
    return manifest,host,copy.deepcopy(host)


def reset_tau(p):
    f=p["fields"]
    f[15]=bits((1e-12+1e-10*max(abs(value(f[9])),abs(value(f[11]))))+value(f[14]))
    p["uncertain"]=int(not(abs(value(f[10]))>value(f[15])))


def test_invented_protocol_baseline_checks_all_records():
    m,h,d=pair()
    assert compare(m,h,d)==[]
    counts=list(m["counts"].values())
    assert parse_output(encode(h,0),counts,0)==h
    assert parse_output(encode(d,1),counts,1)==d


@pytest.mark.parametrize("mutation", ["header","truncated","excess","end_counts","duplicate_index",
    "wrong_device","logical2","hex_width","point_width","blank_after_end","wrong_order"])
def test_strict_protocol_rejects_malformed_records(mutation):
    m,h,d=pair();text=encode(d,1).decode()
    if mutation=="header":text=text.replace("M3A1","M3A2",1)
    elif mutation=="truncated":text=text.rsplit("END",1)[0]
    elif mutation=="excess":text+="R 1 1 0000000000000000\n"
    elif mutation=="end_counts":text=text.replace("END 36 9 9","END 35 9 9")
    elif mutation=="duplicate_index":text=text.replace("S 2 1 ","S 1 1 ",1)
    elif mutation=="wrong_device":text=text.replace("S 1 1 ","S 1 0 ",1)
    elif mutation=="logical2":text=text.replace("S 1 1 1 ","S 1 1 2 ",1)
    elif mutation=="hex_width":text=text.replace("0000000000000000","000000000000000",1)
    elif mutation=="point_width":
        lines=text.splitlines();index=next(i for i,line in enumerate(lines) if line.startswith("P 1 "))
        lines[index+1]=" ".join(lines[index+1].split()[:-1]);text="\n".join(lines)+"\n"
    elif mutation=="wrong_order":text=text.replace("S 1 1 ","R 1 1 ",1)
    else:text+="\n"
    with pytest.raises(Rejected):
        parse_output(text.encode(),list(m["counts"].values()),1)


@pytest.mark.parametrize("mutation", ["finite","exponent","fraction","scaled","cbrt2ulp","signedzero"])
def test_scalar_helper_and_cbrt_errors_fail(mutation):
    m,h,d=pair()
    if mutation=="finite":d["scalars"][2]["finite"]=0
    elif mutation=="exponent":d["scalars"][2]["exponent"]+=1
    elif mutation=="fraction":d["scalars"][2]["fields"][0]+=1
    elif mutation=="scaled":d["scalars"][2]["fields"][1]+=1
    elif mutation=="cbrt2ulp":d["scalars"][2]["fields"][2]+=2
    else:d["scalars"][1]["fields"][2]=0
    with pytest.raises(Rejected):compare(m,h,d)


@pytest.mark.parametrize("bad", [0,SIGN,QNAN,INF,bits(-1.)])
def test_subnormal_rdg_cannot_be_zero_or_nonfinite(bad):
    m,h,d=pair();d["rdg"][6]=bad
    with pytest.raises(Rejected):compare(m,h,d)


def test_extreme_rdg_relative_gate_is_not_large_absolute_slack():
    m,h,d=pair();d["rdg"][3]=bits(value(d["rdg"][3])*1.00000001)
    with pytest.raises(Rejected):compare(m,h,d)


@pytest.mark.parametrize("field", [0,8,9,10,11,12,13,14,15])
@pytest.mark.parametrize("bad", [QNAN,INF])
def test_success_fields_cannot_hide_nan_or_inf(field,bad):
    m,h,d=pair();d["points"][1]["fields"][field]=bad
    with pytest.raises(Rejected):compare(m,h,d)


@pytest.mark.parametrize("point,field,replacement", [(7,0,0),(7,15,0),
    (6,9,0),(6,15,0),(6,0,QNAN),(8,12,0),(8,13,0),(8,9,QNAN)])
def test_failure_path_fields_are_checked_not_blanket_ignored(point,field,replacement):
    m,h,d=pair();d["points"][point]["fields"][field]=replacement
    with pytest.raises(Rejected):compare(m,h,d)


@pytest.mark.parametrize("mutation", ["hidden_bound","tau","uncertain","rawsign","status","negative_bound","counts"])
def test_point_semantics_and_tight_host_bound_tau_gates(mutation):
    m,h,d=pair();p=d["points"][1]
    if mutation=="hidden_bound":
        p["fields"][14]=bits(value(p["fields"][14])*1.00001)
        reset_tau(p)  # A consistent wrong bound/tau must still fail host comparison.
    elif mutation=="tau":p["fields"][15]+=1
    elif mutation=="uncertain":p["uncertain"]=1-p["uncertain"]
    elif mutation=="rawsign":p["fields"][13]^=SIGN
    elif mutation=="status":p["status"]=4
    elif mutation=="negative_bound":p["fields"][14]=bits(-1e-9);reset_tau(p)
    else:d["points"].pop()
    with pytest.raises(Rejected):compare(m,h,d)


def test_allowed_raw_sign_difference_inside_band_is_recorded_separately():
    m,h,d=pair();p=d["points"][0]
    p["fields"][9:12]=[bits(1e-16)]*3
    p["fields"][13]=int(m["points"][0]["center"],16)
    reset_tau(p)
    differences=compare(m,h,d)
    assert len(differences)==1 and differences[0]["point"]==1


def paths(directory):
    return [directory/"manifest.json",directory/"input.m3a1",directory/"host.stdout",
            directory/"device.stdout",directory/"evidence.json"]


def test_evidence_hash_pipeline_preserves_all_originals(tmp_path):
    synthetic_evidence(tmp_path)
    before={p:p.read_bytes() for p in tmp_path.iterdir()}
    report=verify_files(*paths(tmp_path))
    assert report["state"]=="PASS" and report["scientific_acceptance"] is False
    assert all(p.read_bytes()==content for p,content in before.items())


@pytest.mark.parametrize("host_mode", ["stdin","argument"])
@pytest.mark.parametrize("device_mode", ["stdin","argument"])
def test_each_run_explicitly_binds_frozen_input_in_both_modes(tmp_path,host_mode,device_mode):
    e=synthetic_evidence(tmp_path)
    for name,mode in (("host",host_mode),("device",device_mode)):
        run=e[name];run["input_mode"]=mode
        run["input"]=dict(e["input"])
        run["command"]=[run["binary"]["path"]]+([e["input"]["path"]] if mode=="argument" else [])
        if mode=="stdin":run["stdin"]=dict(run["input"])
    save_evidence(tmp_path,e)
    assert verify_files(*paths(tmp_path))["state"]=="PASS"


@pytest.mark.parametrize("name", ["host","device"])
@pytest.mark.parametrize("mode", ["stdin","argument"])
@pytest.mark.parametrize("mutation", ["missing_input_mode","inherited_mode","missing_input_receipt",
    "wrong_path_same_content","wrong_digest","missing_argv","wrong_argv","extra_args",
    "missing_command"])
def test_per_run_input_binding_cannot_be_inferred_or_substituted(tmp_path,name,mode,mutation):
    e=synthetic_evidence(tmp_path);run=e[name]
    run["input_mode"]=mode;run["input"]=dict(e["input"])
    run["command"]=[run["binary"]["path"]]+([e["input"]["path"]] if mode=="argument" else [])
    if mode=="stdin":run["stdin"]=dict(run["input"])
    alternate=tmp_path/"different path identical input.m3a1"
    alternate.write_bytes((tmp_path/"input.m3a1").read_bytes())
    if mutation=="missing_input_mode":del run["input_mode"]
    elif mutation=="inherited_mode":run["input_mode"]="inherit"
    elif mutation=="missing_input_receipt":del run["input"]
    elif mutation=="wrong_path_same_content":
        run["input"]=receipt(alternate)
        if mode=="argument":run["command"][1]=str(alternate)
    elif mutation=="wrong_digest":run["input"]["sha256"]="0"*64
    elif mutation=="missing_argv":run["command"]=[run["binary"]["path"]] if mode=="argument" else []
    elif mutation=="wrong_argv":
        if mode=="argument":run["command"][1]=str(alternate)
        else:run["command"][0]="/different/binary"
    elif mutation=="extra_args":run["command"].append("--unfrozen-extra")
    else:del run["command"]
    save_evidence(tmp_path,e)
    with pytest.raises(Rejected):verify_files(*paths(tmp_path))


@pytest.mark.parametrize("name", ["host","device"])
@pytest.mark.parametrize("mutation", ["missing","wrong_path_same_content","wrong_digest"])
def test_stdin_payload_receipt_must_match_exact_run_input(tmp_path,name,mutation):
    e=synthetic_evidence(tmp_path);run=e[name]
    run.update(input_mode="stdin",command=[run["binary"]["path"]],stdin=dict(run["input"]))
    if mutation=="missing":del run["stdin"]
    elif mutation=="wrong_path_same_content":
        alternate=tmp_path/"identical stdin payload different path.m3a1"
        alternate.write_bytes((tmp_path/"input.m3a1").read_bytes())
        run["stdin"]=receipt(alternate)
    else:run["stdin"]["sha256"]="0"*64
    save_evidence(tmp_path,e)
    with pytest.raises(Rejected):verify_files(*paths(tmp_path))


@pytest.mark.parametrize("name", ["host","device"])
def test_argument_mode_forbids_even_null_stdin_key(tmp_path,name):
    e=synthetic_evidence(tmp_path);e[name]["stdin"]=None
    save_evidence(tmp_path,e)
    with pytest.raises(Rejected):verify_files(*paths(tmp_path))


@pytest.mark.parametrize("mutation", ["exit","binary_hash","input_hash","manifest_gate",
    "marker_only","no_upload","no_download","no_count","no_identity","command_binding",
    "runtime_binding","schema_bool","empty_binary"])
def test_evidence_requires_real_receipts_exit_and_runtime_not_just_marker(tmp_path,mutation):
    e=synthetic_evidence(tmp_path)
    if mutation=="exit":e["device"]["returncode"]=1
    elif mutation=="binary_hash":(tmp_path/"device.not-an-executable").write_text("changed")
    elif mutation=="input_hash":(tmp_path/"input.m3a1").write_text("M3A1\n0 0 0\n")
    elif mutation=="manifest_gate":
        file=tmp_path/"manifest.json";m=json.loads(file.read_text());m["gates"]["rdg"]["rtol"]="1"
        file.write_text(json.dumps(m));e["manifest"]=receipt(file)
    elif mutation in ("marker_only","no_upload","no_download"):
        file=tmp_path/"device.stderr"
        text=dict(marker_only="DEVICE=1\n",no_upload="launch CUDA kernel\ndownload\n",
                  no_download="launch CUDA kernel\nupload\n")[mutation]
        file.write_text(text);e["runtime_evidence"]=e["device"]["stderr"]=receipt(file)
    elif mutation=="no_count":e["device_count"]=0
    elif mutation=="no_identity":e["device_identity"]=""
    elif mutation=="runtime_binding":
        f=tmp_path/"unbound-runtime.log";f.write_bytes((tmp_path/"device.stderr").read_bytes())
        e["runtime_evidence"]=receipt(f)
    elif mutation=="schema_bool":e["schema_version"]=True
    elif mutation=="empty_binary":
        f=tmp_path/"device.not-an-executable";f.write_bytes(b"");e["device"]["binary"]=receipt(f)
    else:e["device"]["command"]=["/different/executable"]
    save_evidence(tmp_path,e)
    with pytest.raises(Rejected):verify_files(*paths(tmp_path))


def argv(directory,report):
    return ["--verify","--manifest",str(directory/"manifest.json"),"--input",str(directory/"input.m3a1"),
            "--host-output",str(directory/"host.stdout"),"--device-output",str(directory/"device.stdout"),
            "--evidence",str(directory/"evidence.json"),"--report",str(report)]


def test_no_device_is_not_tested_exit2_and_no_report_overwrite(tmp_path):
    e=synthetic_evidence(tmp_path)
    e={k:e[k] for k in ("schema_version","input","manifest")}
    e.update(state="no_device",device_count=0,reason="SELFTEST missing device")
    save_evidence(tmp_path,e)
    report=tmp_path/"report.json"
    assert main(argv(tmp_path,report))==2
    assert json.loads(report.read_text())["state"]=="NOT_TESTED"
    before=report.read_bytes()
    assert main(argv(tmp_path,report))==1
    assert report.read_bytes()==before


def test_failed_process_report_is_failed_and_keeps_digests(tmp_path):
    e=synthetic_evidence(tmp_path);e["host"]["returncode"]=-9;save_evidence(tmp_path,e)
    report=tmp_path/"failed.json"
    assert main(argv(tmp_path,report))==1
    r=json.loads(report.read_text())
    assert r["state"]=="FAILED" and len(r["artifacts"])==6
