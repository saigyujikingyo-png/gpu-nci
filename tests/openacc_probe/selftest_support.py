"""Synthetic protocol records for verifier tests, NEVER native execution evidence."""
import copy
import json
from pathlib import Path

from oracle import QNAN, SIGN, bits, value
from verify import FROZEN, receipt


def corpus():
    return json.loads((FROZEN/"manifest.json").read_text())


def synthetic_result(manifest):
    result={"scalars":[],"rdg":[],"points":[]}
    for c in manifest["scalars"]:
        e=c["expected"]
        result["scalars"].append(dict(finite=e["finite"],exponent=e["exponent"],
            fields=[int(e[k],16) for k in ("fraction","scaled","cbrt")]))
    result["rdg"]=[int(c["expected"],16) for c in manifest["rdg"]]
    for c in manifest["points"]:
        f=[QNAN]*16
        if c["status"]!=1:
            f[:9]=[int(t,16) for t in c["expected"]["grad"]+c["expected"]["hess"]]
        uncertain=1
        if c["status"] in (0,6):
            f[9:12]=[int(t,16) for t in c["expected"]["eigen"]]
            f[12]=int(c["expected"]["rdg"],16)
            f[14]=bits(1e-9)  # Invented selftest bound, not production bound truth.
            f[15]=bits((1e-12+1e-10*max(abs(value(f[9])),abs(value(f[11]))))+value(f[14]))
            uncertain=int(not(abs(value(f[10]))>value(f[15])))
            if c["status"]==0:
                middle=value(f[10]);rho=int(c["center"],16)
                f[13]=rho if middle>0 else rho^SIGN if middle<0 else 0
        result["points"].append(dict(status=c["status"],uncertain=uncertain,fields=f))
    return result


def encode(result,device):
    lines=["M3A1"]
    for i,c in enumerate(result["scalars"],1):
        lines.append(f"S {i} {device} {c['finite']} {c['exponent']} "+" ".join(f"{b:016X}" for b in c["fields"]))
    for i,b in enumerate(result["rdg"],1):
        lines.append(f"R {i} {device} {b:016X}")
    for i,c in enumerate(result["points"],1):
        lines.append(f"P {i} {device} {c['status']} {c['uncertain']}")
        lines.append(" ".join(f"{b:016X}" for b in c["fields"]))
    lines.append("END "+" ".join(str(len(result[k])) for k in ("scalars","rdg","points")))
    return ("\n".join(lines)+"\n").encode("ascii")


def synthetic_evidence(directory):
    manifest=corpus(); result=synthetic_result(manifest)
    (directory/"manifest.json").write_bytes((FROZEN/"manifest.json").read_bytes())
    (directory/"input.m3a1").write_bytes((FROZEN/"input.m3a1").read_bytes())
    evidence=dict(schema_version=1,state="executed",device_count=1,
                  device_identity="SELFTEST SYNTHETIC NO DEVICE EXECUTED")
    for name,marker in (("host",0),("device",1)):
        binary=directory/(name+".not-an-executable")
        stdout=directory/(name+".stdout");stderr=directory/(name+".stderr")
        binary.write_text("SELFTEST PLACEHOLDER: NEVER EXECUTE\n")
        stdout.write_bytes(encode(result,marker))
        stderr.write_text("launch CUDA kernel SELFTEST\nupload SELFTEST\ndownload SELFTEST\n")
        evidence[name]=dict(binary=receipt(binary),stdout=receipt(stdout),stderr=receipt(stderr),
                            returncode=0,input_mode="argument",input=receipt(directory/"input.m3a1"),
                            command=[str(binary),str(directory/"input.m3a1")])
    compiler=directory/"compiler.log";compiler.write_text("SELFTEST ONLY NOT A COMPILER RUN\n")
    evidence["compiler_report"]=receipt(compiler)
    evidence["runtime_evidence"]=evidence["device"]["stderr"]
    evidence["input"]=receipt(directory/"input.m3a1")
    evidence["manifest"]=receipt(directory/"manifest.json")
    save_evidence(directory,evidence)
    return evidence


def save_evidence(directory,evidence):
    (directory/"evidence.json").write_text(json.dumps(evidence,indent=2)+"\n")
