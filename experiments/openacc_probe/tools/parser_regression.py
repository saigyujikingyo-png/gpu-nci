"""Finite host-only parser tests. Never launch the host/device numerical probes."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

CAP=8388608
FROZEN_SHA="ad9fd786113d8db5d7760475ab1be110eb7f042d576206efdcdd13535607c7f5"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(parser,input_path,output):
    parser=parser.resolve(strict=True);input_path=input_path.resolve(strict=True)
    if parser.name!="m3a_parse_only":
        raise ValueError("only the parser-only executable is authorized here")
    original=input_path.read_bytes()
    if sha(original)!=FROZEN_SHA:
        raise ValueError("input must match the original 36/9/9 frozen corpus")
    output.mkdir()  # exclusive, including failed attempts
    tokens=original.split()
    short=list(tokens);short[138]=short[138][:-1]
    long=list(tokens);long[4]=b"0"*33
    invalid=original.replace(b"3FF0000000000000",b"3FF0000\x0000000000",1)
    cases=[("original-long-lines",original,0),
           ("legal-whitespace",b" \t\r\n".join(tokens)+b"\r\n",0),
           ("token-across-4096",b" "*4095+original,0),
           ("no-final-newline",original.rstrip(b"\n"),0),
           ("truncated-hex",b" ".join(short)+b"\n",2),
           ("overlong-token",b" ".join(long)+b"\n",2),
           ("excess-token",original+b"0\n",2),
           ("non-ascii-separator",invalid,2),
           ("exact-byte-cap",original+b" "*(CAP-len(original)),0),
           ("byte-cap-plus-one",original+b" "*(CAP-len(original)+1),2)]
    assert sum(len(data) for _,data,_ in cases)<64*1024*1024
    records=[]
    for index,(label,data,expected) in enumerate(cases,1):
        prefix=f"{index:02d}-{label}"
        (output/(prefix+".stdin")).write_bytes(data)
        try:
            p=subprocess.run([str(parser)],input=data,capture_output=True,timeout=10,check=False)
            rc,stdout,stderr,timed_out=p.returncode,p.stdout,p.stderr,False
        except subprocess.TimeoutExpired as exc:
            rc,stdout,stderr,timed_out=None,exc.stdout or b"",exc.stderr or b"",True
        (output/(prefix+".stdout")).write_bytes(stdout)
        (output/(prefix+".stderr")).write_bytes(stderr)
        expected_tokens=tokens if expected==0 else []
        parsed_tokens=stdout.split()
        passed=(not timed_out and rc==expected and parsed_tokens==expected_tokens
                and (expected==0 or stdout==b""))
        records.append(dict(case=label,command=[str(parser)],timeout_seconds=10,
            returncode=rc,expected_returncode=expected,timed_out=timed_out,passed=passed,
            parsed_token_count=len(parsed_tokens),expected_token_count=len(expected_tokens),
            stdin=dict(bytes=len(data),sha256=sha(data)),
            stdout=dict(bytes=len(stdout),sha256=sha(stdout)),
            stderr=dict(bytes=len(stderr),sha256=sha(stderr))))
    report=dict(scope="host parser only; no numerical evaluator or GPU executed",
        parser=dict(path=str(parser),sha256=sha(parser.read_bytes())),
        source_input=dict(path=str(input_path),sha256=sha(original)),cases=records)
    if input_path.read_bytes()!=original:
        raise ValueError("original frozen input changed")
    with (output/"report.json").open("x") as f:
        json.dump(report,f,indent=2);f.write("\n")
    print(json.dumps(dict(passed=sum(c["passed"] for c in records),total=len(records),output=str(output))))
    return 0 if all(c["passed"] for c in records) else 1


if __name__=="__main__":
    args=argparse.ArgumentParser(description=__doc__)
    args.add_argument("--parser",type=Path,required=True)
    args.add_argument("--input",type=Path,required=True)
    args.add_argument("--output-dir",type=Path,required=True)
    a=args.parse_args()
    raise SystemExit(run(a.parser,a.input,a.output_dir))
