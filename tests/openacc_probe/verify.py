"""Compare-only M3A1 verifier: no native processes or GPU APIs are invoked."""
import argparse
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
import sys

from fixtures import GATES, digest, input_text
from oracle import ROOT, ETA, QNAN, SIGN, bits, classification, rational, value

CAP=8388608
FROZEN=Path(__file__).with_name("frozen")


class Rejected(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Rejected(message)


def read_small(path):
    with Path(path).open("rb") as f:
        data=f.read(CAP+1)
    require(len(data)<=CAP, f"file exceeds {CAP} bytes: {path}")
    return data


def strict_json(path):
    def pairs(items):
        out={}
        for key,val in items:
            require(key not in out, f"duplicate JSON key {key}")
            out[key]=val
        return out
    def invalid(token):
        raise Rejected(f"nonfinite JSON token {token}")
    return json.loads(read_small(path), object_pairs_hook=pairs, parse_constant=invalid)


def load_corpus(manifest_path, input_path):
    data=read_small(manifest_path)
    require(data==read_small(FROZEN/"manifest.json"), "manifest differs from committed frozen corpus")
    manifest=strict_json(manifest_path)
    require(manifest["schema"]==1 and manifest["protocol"]=="M3A1", "manifest protocol")
    require(manifest["gates"]==GATES, "frozen gates changed")
    require(manifest["counts"]==dict(zip(("NS","NR","NP"),
            [len(manifest[k]) for k in ("scalars","rdg","points")])), "manifest counts")
    require(all(0<=n<=128 for n in manifest["counts"].values()), "record cap")
    for path,sha in manifest["sources"].items():
        require(digest(ROOT/path)==sha, f"frozen oracle source changed: {path}")
    raw=read_small(input_path)
    require(raw==input_text(manifest).encode("ascii"), "input differs from frozen records")
    require(len(raw)==manifest["input"]["bytes"] and
            hashlib.sha256(raw).hexdigest()==manifest["input"]["sha256"], "input digest")
    return manifest


def _integer(text):
    require(re.fullmatch(r"-?[0-9]+",text) is not None, "nondecimal integer")
    return int(text)


def _hex(text):
    require(re.fullmatch(r"[0-9a-fA-F]{16}",text) is not None, "binary64 token must be 16 hex digits")
    return int(text,16)


def parse_output(data, counts, device):
    try:
        lines=data.decode("ascii").splitlines()
    except UnicodeError as exc:
        raise Rejected("output is not ASCII") from exc
    require(lines and lines.pop(0)=="M3A1", "missing output protocol header")
    out={"scalars":[], "rdg":[], "points":[]}
    def take():
        require(bool(lines), "truncated output")
        return lines.pop(0).split()
    for kind,key,count in zip(("S","R","P"),out,counts):
        for index in range(1,count+1):
            row=take()
            require(len(row)==dict(S=8,R=4,P=5)[kind], "record width")
            require(row[0]==kind and _integer(row[1])==index, "record kind/index/order")
            require(_integer(row[2])==device, "calculation device marker")
            if kind=="S":
                finite,exponent=_integer(row[3]),_integer(row[4])
                require(finite in (0,1), "finite logical must be 0 or 1")
                out[key].append(dict(finite=finite, exponent=exponent,
                                    fields=[_hex(s) for s in row[5:]]))
            elif kind=="R":
                out[key].append(_hex(row[3]))
            else:
                status,uncertain=_integer(row[3]),_integer(row[4])
                require(0<=status<=6 and uncertain in (0,1), "point status/logical")
                fields=take()
                require(len(fields)==16,"point needs exactly 16 fields")
                out[key].append(dict(status=status,uncertain=uncertain,
                                    fields=[_hex(s) for s in fields]))
    end=take()
    require(len(end)==4 and end[0]=="END" and tuple(_integer(x) for x in end[1:])==tuple(counts),
            "missing or incorrect final END counts")
    require(not lines,"excess records after END")
    return out


def ulp_distance(a,b):
    def ordered(n):
        return (~n & ((1<<64)-1)) if n & SIGN else n | SIGN
    return abs(ordered(a)-ordered(b))


def finite(raw,label):
    require(math.isfinite(value(raw)),f"{label}: expected finite")


def close_bits(actual, expected, atol, rtol, label):
    finite(actual,label); finite(expected,label)
    a,b=rational(actual),rational(expected)
    require(abs(a-b)<=Fraction(atol)+Fraction(rtol)*abs(b), f"{label}: numerical gate")


def check_scalar(case,result,label):
    expected=case["expected"]
    require(result["finite"]==expected["finite"] and result["exponent"]==expected["exponent"],
            f"{label}: finite/exponent")
    fraction,scaled,cbrt=result["fields"]
    require(fraction==int(expected["fraction"],16),f"{label}: fraction bits")
    want=int(expected["scaled"],16)
    if expected["finite"]:
        require(scaled==want,f"{label}: scaled bits")
    else:
        require(classification(scaled)==classification(want),f"{label}: nonfinite scaling class")
    want=int(expected["cbrt"],16)
    kind=classification(want)
    if kind in ("nan","+inf","-inf","+zero","-zero"):
        require(classification(cbrt)==kind,f"{label}: cbrt special class/sign")
    else:
        finite(cbrt,label)
        require(ulp_distance(cbrt,want)<=1,f"{label}: cbrt exceeds 1 ULP")


def check_rdg(case,actual,label):
    expected=int(case["expected"],16)
    kind=case["expected_class"]
    require(classification(actual)==kind,f"{label}: RDG class (zero/NaN/Inf cannot pass tolerance)")
    if kind in ("+zero","-zero","+inf","-inf","nan"):
        return
    require(value(actual)>0,f"{label}: RDG must be positive")
    gate=case["gate"]
    if gate=="relative16eps":
        close_bits(actual,expected,"0",Fraction(16,1<<52),label)
    elif gate=="subnormal1ulp":
        require(kind=="subnormal" and ulp_distance(actual,expected)<=1,
                f"{label}: subnormal RDG exceeds 1 ULP")
    else:
        require(gate=="standard",f"{label}: undeclared RDG gate")
        close_bits(actual,expected,"1e-11","1e-9",label)


def check_tau(result,label):
    f=result["fields"]
    bound,tau=value(f[14]),value(f[15])
    require(math.isfinite(bound) and math.isfinite(tau) and bound>=0 and tau>=0,
            f"{label}: bound/tau must be finite nonnegative")
    expected=(1e-12 + 1e-10*max(abs(value(f[9])),abs(value(f[11])))) + bound
    require(bits(tau)==bits(expected), f"{label}: exact tau relation")
    require(result["uncertain"]==int(not(abs(value(f[10]))>tau)),f"{label}: self uncertainty")


def check_point(case,result,label):
    require(result["status"]==case["status"], f"{label}: independent expected failure/status")
    f=result["fields"]; status=result["status"]
    if status==1:
        require(all(classification(x)=="nan" for x in f),f"{label}: derivative failure fields")
        require(result["uncertain"]==1,f"{label}: failure uncertainty")
        return
    for i,want in enumerate(case["expected"]["grad"]+case["expected"]["hess"]):
        close_bits(f[i],int(want,16),"1e-12","1e-10",f"{label}: derivative {i}")
    if status==4:
        require(all(classification(x)=="nan" for x in f[9:]),f"{label}: nonconvergence tail fields")
        require(result["uncertain"]==1,f"{label}: failure uncertainty")
        return
    require(value(f[9])<=value(f[10])<=value(f[11]),f"{label}: sorted roots")
    for i,want in enumerate(case["expected"]["eigen"]):
        close_bits(f[9+i],int(want,16),"1e-12","1e-10",f"{label}: eigen {i}")
    check_tau(result,label)
    if status==6:
        require(classification(f[12])=="+inf" and classification(f[13])=="nan",
                f"{label}: result failure RDG/signedrho classes")
        return
    require(status==0,f"{label}: unsupported status fixture")
    for x in f:
        finite(x,label)
    check_rdg(dict(expected=case["expected"]["rdg"],
                   expected_class=classification(int(case["expected"]["rdg"],16)),gate="standard"),f[12],label)
    middle=value(f[10]); rho=int(case["center"],16)
    want=(rho if middle>0 else rho^SIGN if middle<0 else 0)
    require(f[13]==want,f"{label}: raw middle-root signed density")
    reference=value(int(case["expected"]["eigen"][1],16))
    if abs(reference)>1e-9:
        require(f[13]==(rho if reference>0 else rho^SIGN),f"{label}: reference sign away from fixed band")


def compare(manifest,host,device):
    differences=[]
    for name,result in (("host",host),("device",device)):
        require(all(len(result[k])==len(manifest[k]) for k in ("scalars","rdg","points")),
                f"{name}: result counts")
        for i,(case,r) in enumerate(zip(manifest["scalars"],result["scalars"]),1):
            check_scalar(case,r,f"{name} S{i}")
        for i,(case,r) in enumerate(zip(manifest["rdg"],result["rdg"]),1):
            check_rdg(case,r,f"{name} R{i}")
        for i,(case,r) in enumerate(zip(manifest["points"],result["points"]),1):
            check_point(case,r,f"{name} P{i}")
    for i,(h,d) in enumerate(zip(host["points"],device["points"]),1):
        require((h["status"],h["uncertain"])==(d["status"],d["uncertain"]),f"P{i}: host/device status uncertainty")
        if h["status"] in (0,6):
            for j in (14,15):
                close_bits(d["fields"][j],h["fields"][j],8*ETA,"1e-10",f"P{i}: host/device bound/tau")
            hs,ds=value(h["fields"][10]),value(d["fields"][10])
            if (hs>0)-(hs<0)!=(ds>0)-(ds<0):
                differences.append(dict(point=i,label=manifest["points"][i-1]["label"],
                    host_middle=f"{h['fields'][10]:016X}",device_middle=f"{d['fields'][10]:016X}"))
    return differences


def receipt(path):
    path=Path(path).resolve(strict=True)
    sha=hashlib.sha256(); count=0
    with path.open("rb") as f:
        for block in iter(lambda:f.read(65536),b""):
            sha.update(block); count+=len(block)
    return dict(path=str(path),sha256=sha.hexdigest(),bytes=count)


def verify_files(manifest_path,input_path,host_output,device_output,evidence_path):
    manifest=load_corpus(manifest_path,input_path)
    evidence=strict_json(evidence_path)
    require(type(evidence.get("schema_version")) is int and evidence["schema_version"]==1,"evidence schema")
    checked=[]
    def check(r):
        require(type(r) is dict and set(r)=={"path","sha256","bytes"},"receipt schema")
        require(type(r["path"]) is str and Path(r["path"]).is_absolute(),"receipt absolute path")
        require(type(r["bytes"]) is int and r["bytes"]>=0 and
                type(r["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}",r["sha256"]) is not None,
                "receipt hash/size types")
        actual=receipt(r["path"])
        require(actual==r,"artifact receipt mismatch: "+r["path"])
        checked.append(actual)
        return Path(r["path"])
    for key,path in (("input",input_path),("manifest",manifest_path)):
        require(check(evidence[key])==Path(path).resolve(),f"{key} receipt path binding")
    base=dict(schema_version=1,scope="finite synthetic M3A1 evaluator portability only",
        public_gpu_backend="NOT_IMPLEMENTED", scientific_acceptance=False,
        counts=manifest["counts"], verifier=receipt(__file__), evidence=receipt(evidence_path))
    if evidence.get("state")=="no_device":
        require("host" not in evidence and "device" not in evidence,
                "no_device evidence cannot contain executed host/device runs")
        require(type(evidence.get("device_count")) is int and evidence["device_count"]==0 and
                type(evidence.get("reason")) is str and bool(evidence["reason"].strip()),"missing device evidence")
        require(all(receipt(r["path"])==r for r in checked) and
                receipt(evidence_path)==base["evidence"],"missing-device evidence changed")
        base.update(state="NOT_TESTED",message=evidence["reason"],artifacts=checked)
        return base
    require(evidence.get("state")=="executed","unknown execution evidence state")
    require(type(evidence.get("device_count")) is int and evidence["device_count"]>0 and
            type(evidence.get("device_identity")) is str and bool(evidence["device_identity"].strip()),
            "nonzero NVIDIA device identity/count required")
    for key,output in (("host",host_output),("device",device_output)):
        run=evidence[key]
        require(type(run["returncode"]) is int and run["returncode"]==0,f"{key}: process exit")
        binary=check(run["binary"])
        require(run["binary"]["bytes"]>0,f"{key}: empty binary receipt")
        mode=run.get("input_mode")
        require(mode in ("stdin","argument"),f"{key}: explicit input_mode required")
        check(run.get("input"))
        require(run["input"]==evidence["input"],f"{key}: run input must equal frozen input receipt")
        expected_command=[str(binary)]
        if mode=="argument":
            require("stdin" not in run,f"{key}: argument mode forbids stdin receipt")
            expected_command.append(evidence["input"]["path"])
        else:
            check(run.get("stdin"))
            require(run["stdin"]==run["input"],f"{key}: stdin payload must equal run input receipt")
        require(run.get("command")==expected_command,
                f"{key}: command must exactly bind binary and {mode} frozen input")
        require(check(run["stdout"])==Path(output).resolve(),f"{key}: output receipt binding")
        check(run["stderr"])
    compiler=check(evidence["compiler_report"])
    runtime=check(evidence["runtime_evidence"])
    require(runtime==Path(evidence["device"]["stderr"]["path"]),
            "runtime evidence must be the recorded device stderr")
    require(compiler.stat().st_size>0,"compiler report is empty")
    log=read_small(runtime).decode("utf-8",errors="replace").lower()
    require(re.search(r"launch[^\n]*kernel",log) is not None and "upload" in log and "download" in log,
            "runtime evidence needs kernel launch, upload and download; markers alone are insufficient")
    counts=list(manifest["counts"].values())
    host=parse_output(read_small(host_output),counts,0)
    device=parse_output(read_small(device_output),counts,1)
    differences=compare(manifest,host,device)
    # Rehash all supplied evidence after reading/comparison; originals are read only.
    require(all(receipt(r["path"])==r for r in checked),"evidence changed during verification")
    require(receipt(evidence_path)==base["evidence"],"evidence receipt changed during verification")
    base.update(state="PASS",message="finite numerical portability gates passed; no public backend/scientific claim",
                artifacts=checked,raw_middle_sign_differences=differences)
    return base


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify",action="store_true",required=True)
    for key in ("manifest","input","evidence","report"):
        parser.add_argument("--"+key,type=Path,required=True)
    for key in ("host-output","device-output"):
        parser.add_argument("--"+key,type=Path)
    args=parser.parse_args(argv)
    try:
        report=verify_files(args.manifest,args.input,args.host_output,args.device_output,args.evidence)
    except (Rejected,OSError,ValueError,KeyError,TypeError,OverflowError) as exc:
        report=dict(schema_version=1,state="FAILED",message=str(exc),
                    scope="finite synthetic M3A1 evaluator portability only",
                    public_gpu_backend="NOT_IMPLEMENTED",scientific_acceptance=False)
        report["artifacts"]=[]
        for path in (args.manifest,args.input,args.host_output,args.device_output,args.evidence,Path(__file__)):
            if path is not None:
                try:
                    report["artifacts"].append(receipt(path))
                except OSError:
                    pass
    try:
        with args.report.open("x",encoding="ascii") as f:
            json.dump(report,f,indent=2,allow_nan=False); f.write("\n")
    except OSError as exc:
        print(f"report not written: {exc}",file=sys.stderr)
        return 1
    print(report["state"],report["message"])
    return dict(PASS=0,FAILED=1,NOT_TESTED=2)[report["state"]]


if __name__=="__main__":
    raise SystemExit(main())
